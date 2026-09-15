#!/usr/bin/env python3
"""
Hierarchical Extraction Pipeline with Retry Logic
Core extraction engine for Bill of Entry documents
"""

import json
import time
import re
from typing import Dict, Optional, Tuple, List
from pathlib import Path
from dataclasses import dataclass
import google.generativeai as genai
import PIL.Image
import pdfplumber

from bill_of_entry_extractor.config import config
from bill_of_entry_extractor.utils.api_key_manager import APIKeyManager
from bill_of_entry_extractor.core.models import DocumentStructure, PageRange
from bill_of_entry_extractor.core.prompts import BasePromptBuilder
from bill_of_entry_extractor.validation.validator import SchemaValidator, ValidationResult
from bill_of_entry_extractor.utils.logger import get_logger

# Import part6 extractor for Bill of Entry documents
# This is a special case - Part 6 only exists in BE, not SB
from bill_of_entry_extractor.bill_of_entry.part6_extractor import extract_part6


@dataclass
class ExtractionResult:
    """Result of extracting a single part"""
    part_name: str
    success: bool
    data: Optional[Dict]
    raw_response: Optional[str]
    validation_result: Optional[ValidationResult]
    duration: float
    attempts: int
    error: Optional[str] = None
    
    # Token usage tracking (from Gemini API)
    input_tokens: int = 0
    output_tokens: int = 0


class ExtractionPipeline:
    """Main extraction pipeline with retry logic"""

    def __init__(self, api_key_manager: APIKeyManager, validator: SchemaValidator, prompt_builder=None, schema_dir: str = "schema"):
        self.api_manager = api_key_manager
        self.validator = validator
        self.prompt_builder = prompt_builder  # Document-specific prompt builder must be provided
        self.schema_dir = schema_dir
        self.logger = get_logger()

    def extract_part(
        self,
        pdf_path: str,
        part_name: str,
        page_range: PageRange,
        context: Optional[Dict] = None,
        max_retries: int = 3,
        use_text_extraction: bool = False
    ) -> ExtractionResult:
        """
        Extract a single part with retry logic

        Args:
            pdf_path: Path to PDF file
            part_name: Part identifier (e.g., 'part-1')
            page_range: Pages to extract
            context: Optional context (e.g., invoice number)
            max_retries: Maximum retry attempts
            use_text_extraction: If True, extract text with pdfplumber and send to LLM instead of images

        Returns:
            ExtractionResult
        """
        # Special handling for Part 6 - use pdfplumber instead of Gemini
        if part_name == 'part-6':
            return self._extract_part6_with_pdfplumber(pdf_path, part_name, page_range)
        
        # Use text extraction for specified parts (better accuracy for complex tables)
        if use_text_extraction:
            return self._extract_part_with_text(pdf_path, part_name, page_range, context, max_retries)

        page_info = f"{page_range.start}-{page_range.end}"
        self.logger.part_start(part_name, page_info)

        start_time = time.time()
        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                # Get available API key
                api_key = self.api_manager.get_available_key(wait=True, max_wait=60.0)
                api_key_preview = f"{api_key[:8]}...{api_key[-4:]}"

                # Get model
                model = self._get_model()
                self.logger.api_request(api_key_preview, model.model_name)

                # Build prompt
                schema_path = f"{self.schema_dir}/{part_name}.json"
                prompt = self.prompt_builder.build_prompt(part_name, schema_path, context)

                # Extract pages as images
                images = self._extract_pages_as_images(pdf_path, page_range)

                # Make API call
                api_start = time.time()
                response = model.generate_content([prompt] + images, stream=False)
                api_duration = time.time() - api_start

                self.logger.api_response(api_duration)
                
                # Extract token usage from Gemini API response
                input_tokens = 0
                output_tokens = 0
                
                if hasattr(response, 'usage_metadata'):
                    input_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0)
                    output_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0)
                    self.logger.info(f"    Tokens - Input: {input_tokens}, Output: {output_tokens}")

                # Check if response was blocked (e.g., RECITATION, SAFETY)
                if not response.candidates:
                    raise ValueError("Response blocked: No candidates returned")

                candidate = response.candidates[0]

                # Check finish_reason
                # 1 = STOP (normal), 2 = MAX_TOKENS, 3 = SAFETY, 4 = RECITATION, 5 = OTHER
                finish_reason = candidate.finish_reason

                if finish_reason == 4:  # RECITATION - copyrighted content detected
                    self.logger.warning(f"    Gemini detected potential copyrighted content (RECITATION)")

                    # For PART-6, try to work around by returning minimal valid JSON
                    if part_name == 'part-6':
                        self.logger.warning(f"    PART-6 RECITATION workaround: returning minimal schema-compliant JSON")
                        # Return minimal valid structure for Part 6
                        raw_response = json.dumps({
                            "part_6_declaration": {
                                "declaration_statements": [],
                                "authorized_signatory": {
                                    "cha_name": "",
                                    "date": "",
                                    "place": "",
                                    "signatory_name": ""
                                }
                            }
                        })
                    else:
                        # For other parts, try to extract from parts
                        self.logger.warning(f"    Attempting to extract from parts instead of response.text")
                        if candidate.content and candidate.content.parts:
                            raw_response = "".join(part.text for part in candidate.content.parts if hasattr(part, 'text'))
                            if not raw_response:
                                raise ValueError("RECITATION block: No extractable text from response parts")
                        else:
                            raise ValueError("RECITATION block: Response was blocked due to copyrighted material detection")

                elif finish_reason == 3:  # SAFETY
                    raise ValueError("SAFETY block: Response blocked by safety filters")

                elif finish_reason not in [1, 2]:  # Not STOP or MAX_TOKENS
                    raise ValueError(f"Response blocked with finish_reason: {finish_reason}")

                else:
                    # Normal response - safe to use response.text
                    raw_response = response.text

                # Record success
                self.api_manager.record_success(api_key)

                # Parse response
                data = self._parse_json_response(raw_response)

                # Fix Part 4 empty arrays if needed
                data = self._fix_part4_empty_arrays(data, part_name)

                # Fix empty challan_details if needed (only for part-1)
                data = self._fix_empty_challan_details(data, part_name)

                # Validate
                validation_result = self.validator.validate(data, part_name)

                duration = time.time() - start_time
                success = not validation_result.has_critical_errors()

                self.logger.part_complete(part_name, success, duration)
                self.logger.validation_result(
                    part_name,
                    validation_result.is_valid,
                    len(validation_result.errors),
                    len(validation_result.warnings)
                )

                return ExtractionResult(
                    part_name=part_name,
                    success=success,
                    data=data,
                    raw_response=raw_response,
                    validation_result=validation_result,
                    duration=duration,
                    attempts=attempt,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens
                )

            except json.JSONDecodeError as e:
                last_error = f"JSON parsing error: {str(e)}"
                self.logger.retry_attempt(attempt, max_retries, last_error)

            except Exception as e:
                last_error = f"Extraction error: {str(e)}"
                self.logger.retry_attempt(attempt, max_retries, last_error)

                # Record failure for API key
                if 'api_key' in locals():
                    self.api_manager.record_failure(api_key, last_error)

            # Wait before retry (exponential backoff)
            if attempt < max_retries:
                wait_time = config.gemini.retry_delay * (2 ** (attempt - 1))
                time.sleep(wait_time)

        # All retries failed
        duration = time.time() - start_time
        self.logger.part_complete(part_name, False, duration)
        self.logger.error(f"    Failed after {max_retries} attempts: {last_error}")

        return ExtractionResult(
            part_name=part_name,
            success=False,
            data=None,
            raw_response=None,
            validation_result=None,
            duration=duration,
            attempts=max_retries,
            error=last_error
        )

    def _fix_empty_challan_details(self, data: Dict, part_name: str) -> Dict:
        """
        Ensure challan_details has proper structure if empty.
        Only fixes empty arrays or missing field - doesn't modify existing data.
        Uses field names from schema: sr_no, challan_no, paymt_dt, amount
        Values are set to empty strings as per requirement.
        """
        if part_name == 'part-1' and 'part_1_shipping_bill_summary' in data:
            summary = data['part_1_shipping_bill_summary']
            challan_details = summary.get('challan_details', [])
            
            # Fix if missing or empty array - don't touch if it has data
            if not challan_details or (isinstance(challan_details, list) and len(challan_details) == 0):
                summary['challan_details'] = [{
                    "sr_no": "",
                    "challan_no": "",
                    "paymt_dt": "",
                    "amount": ""
                }]
                self.logger.info("    Fixed empty challan_details - added structure with empty string values")
        
        return data

    def _fix_part4_empty_arrays(self, data: Dict, part_name: str) -> Dict:
        """
        Ensure Part 4 arrays have proper structure if empty.
        Similar to challan_details - if an array is empty, add one object with all fields as empty strings.
        Uses exact field names from schema (e.g., "1.INVSNO", "2.ITMSNO", etc.).
        Only fixes empty arrays or missing fields - doesn't modify existing data.
        """
        if part_name == 'part-4' and 'part_4_additional_details' in data:
            details = data['part_4_additional_details']
            
            # Mapping of field names to their schema field labels (exact as in schema)
            field_mappings = {
                'svb_details': [
                    "1.INVSNO", "2.ITMSNO", "3.REF NO", "4.REF DT", "5.PRT CD", 
                    "6.LAB", "7.P/F", "8.LOAD DATE", "9. P/F"
                ],
                'previous_bes': [
                    "1.INVSNO", "2.ITMSNO", "3.BE NO", "4.BE DATE", "5.PRT CD", 
                    "6.UNITPRICE", "7.CURRENCY CODE"
                ],
                'reimport_after_export': [
                    "1.INVSNO", "2.ITMSNO", "3.NOTN NO", "4.SLNO", "5.FRT", 
                    "6.INS", "7.DUTY", "8.SB NO", "9.SB DT", "10.PORTCD", 
                    "11.SINV", "12.SITEMN"
                ],
                'item_manufacturer_details': [
                    "1.INVSNO", "2.ITMSNO", "3.TYPE", "4.MANUFACT CD", 
                    "5.SOURCE CY", "6.TRANS CY", "7.ADDRESS"
                ],
                'accessory_status': [
                    "1.INVSNO", "2.ITMSNO", "3.ACESSORY ITEM DETAILS"
                ],
                'licence_details': [
                    "1.INVSNO", "2.ITMSNO", "3.LIC SLNO", "4.LIC NO", 
                    "5.LIC DATE", "6.CODE", "7.PORT", "8.DEBIT VALUE", 
                    "9.QTY", "10.UQC", "11.DEBIT DUTY"
                ],
                'certificate_details': [
                    "1.CERTIFICATE NUMBER", "2.DATE", "3.TYPE"
                ],
                'hss_details': [
                    "1.PRC LEVEL", "2.IEC", "3.BRANCH SLNO"
                ],  # Empty fields array in schema
                'single_window_declaration': [
                    "1.INVSN", "2.ITMSNO", "3.INFO TYP", "4.QUALIFIER", 
                    "5.INFO CD", "6.INFO TEXT", "7.INFO MSR", "8.UQC"
                ],
                'single_window_constituents': [
                    "1.INVSN", "2.ITMSNO", "3.C SNO", "4.NAME", "5.CODE", 
                    "6.PERCENTAGE", "7.YIELD PCT", "8.ING"
                ],
                'single_window_control': [
                    "1.INVSN", "2.ITMSNO", "3.CONTROL TYPE", "4.LOCATION", 
                    "5.SRT DT", "6.END DT", "7.RES CD", "8.RES TEXT"
                ],
                'supporting_documents': [
                    "1.INVSN", "2.ITMSNO", "3.TYP", "4.ICEGATE ID", "5.IRN", 
                    "6.DOC CODE", "7.ISSUE PLACE", "8.ISSUE DT", "9.EXP DT"
                ],
                'container_details': [
                    "1.CONTAINER NUMBER", "2.TRUCK NUMBER", "3.SEAL NUMBER", "4.FCL/LCL"
                ],
                'invoice_details': [
                    "1.S NO", "2.INVOICE NO", "3.INVOICE AMOUNT", "4.CUR"
                ]
            }
            
            # Process each field
            for field_name, field_list in field_mappings.items():
                field_value = details.get(field_name)
                
                # Check if field is missing, empty array, or has nested empty records
                is_empty = False
                
                if field_value is None:
                    # Field is missing
                    is_empty = True
                elif isinstance(field_value, list):
                    # Direct array - check if empty
                    if len(field_value) == 0:
                        is_empty = True
                elif isinstance(field_value, dict):
                    # Nested structure - check if it has empty records
                    if 'records' in field_value:
                        if not field_value['records'] or len(field_value['records']) == 0:
                            is_empty = True
                    elif len(field_value) == 0:
                        # Empty object like hss_details: {}
                        is_empty = True
                
                # Fix if empty - don't touch if it has data
                if is_empty:
                    if field_list:  # Only create object if there are fields defined
                        empty_object = {field: "" for field in field_list}
                        details[field_name] = [empty_object]
                        self.logger.info(f"    Fixed empty {field_name} - added structure with empty string values")
                    else:
                        # For hss_details which has no fields, set to empty array
                        details[field_name] = []
                        self.logger.info(f"    Fixed empty {field_name} - set to empty array")
        
        return data

    def _get_model(self):
        """Get first available Gemini model with safety settings"""
        # Configure safety settings to reduce false positives for document extraction
        # These settings prevent blocking of legitimate business documents
        safety_settings = {
            'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE',
            'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE',
            'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE',
            'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE',
        }

        # Generation config for better JSON extraction
        generation_config = {
            'temperature': 0,  # high temperature for diverse outputs
            'top_p': 0.95,
            'top_k': 40
        }

        for model_name in config.gemini.model_preferences:
            try:
                model = genai.GenerativeModel(
                    model_name,
                    safety_settings=safety_settings,
                    generation_config=generation_config
                )
                return model
            except Exception:
                continue

        raise RuntimeError("No suitable Gemini model available")

    def _extract_pages_as_images(self, pdf_path: str, page_range: PageRange) -> List[PIL.Image.Image]:
        """
        Extract specified pages from PDF as images

        Args:
            pdf_path: Path to PDF
            page_range: Pages to extract (1-indexed, inclusive)

        Returns:
            List of PIL Images
        """
        images = []

        with pdfplumber.open(pdf_path) as pdf:
            # Convert to 0-indexed
            start_idx = page_range.start - 1
            end_idx = page_range.end  # end is inclusive, so no -1 needed for slicing

            for page_num in range(start_idx, end_idx):
                if page_num < len(pdf.pages):
                    page = pdf.pages[page_num]

                    # Convert page to image (96 DPI for optimal performance)
                    pil_image = page.to_image(resolution=200).original
                    images.append(pil_image)

        return images

    def _parse_json_response(self, response_text: str) -> Dict:
        """
        Parse JSON from Gemini response, handling markdown code blocks

        Args:
            response_text: Raw response from Gemini

        Returns:
            Parsed JSON as dictionary

        Raises:
            json.JSONDecodeError: If JSON is invalid
        """
        # Remove markdown code blocks
        text = response_text.strip()

        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]

        if text.endswith("```"):
            text = text[:-3]

        text = text.strip()

        # Parse JSON
        return json.loads(text)

    def extract_part_with_chunking(
        self,
        pdf_path: str,
        part_name: str,
        page_range: PageRange,
        chunk_size: int = 5,
        use_text_extraction: bool = False
    ) -> ExtractionResult:
        """
        Extract a large part in chunks (for Part III with many pages)

        Args:
            pdf_path: Path to PDF
            part_name: Part name
            page_range: Total page range
            chunk_size: Number of pages per chunk
            use_text_extraction: If True, use text extraction mode

        Returns:
            Combined ExtractionResult
        """
        extraction_mode = "text extraction" if use_text_extraction else "image"
        self.logger.info(f"    Using chunked extraction ({extraction_mode} mode): {chunk_size} pages per chunk")

        total_pages = page_range.end - page_range.start + 1
        chunks = []
        all_items = []

        # Process in chunks
        for chunk_start in range(page_range.start, page_range.end + 1, chunk_size):
            chunk_end = min(chunk_start + chunk_size - 1, page_range.end)

            chunk_range = PageRange(
                start=chunk_start,
                end=chunk_end,
                part_name=part_name,
                part_number=page_range.part_number
            )

            self.logger.info(f"    Processing chunk: pages {chunk_start}-{chunk_end}")

            result = self.extract_part(pdf_path, part_name, chunk_range, use_text_extraction=use_text_extraction)

            if not result.success:
                self.logger.error(f"    Chunk {chunk_start}-{chunk_end} failed")
                return result

            # Extract items from this chunk
            if part_name == 'part-3':
                # Support both Shipping Bill and Bill of Entry structures
                chunk_items = (
                    result.data.get('part_3_item_details', {}).get('invoice_items', []) or
                    result.data.get('part_3_duties', {}).get('item_duties', [])
                )
                all_items.extend(chunk_items)
                self.logger.info(f"    Extracted {len(chunk_items)} items from chunk")
            
            elif part_name == 'part-4':
                # For Part-4, just log success - we'll merge all sections later
                if result.data:
                    self.logger.info(f"    Chunk {chunk_start}-{chunk_end} extracted successfully")

            chunks.append(result)

        # Combine all chunks
        if part_name == 'part-3':
            # Detect document type from first chunk's structure
            if chunks and chunks[0].data:
                if 'part_3_item_details' in chunks[0].data:
                    # Shipping Bill structure
                    combined_data = {
                        'part_3_item_details': {
                            'invoice_items': all_items
                        }
                    }
                else:
                    # Bill of Entry structure
                    combined_data = {
                        'part_3_duties': {
                            'item_duties': all_items
                        }
                    }
            else:
                # Fallback to Bill of Entry structure
                combined_data = {
                    'part_3_duties': {
                        'item_duties': all_items
                    }
                }

            # Validate combined result
            validation_result = self.validator.validate(combined_data, part_name)

            total_duration = sum(c.duration for c in chunks)
            total_input_tokens = sum(c.input_tokens for c in chunks)
            total_output_tokens = sum(c.output_tokens for c in chunks)

            self.logger.info(f"    Combined {len(all_items)} total items from {len(chunks)} chunks")
            self.logger.info(f"    Total Tokens - Input: {total_input_tokens}, Output: {total_output_tokens}")

            return ExtractionResult(
                part_name=part_name,
                success=not validation_result.has_critical_errors(),
                data=combined_data,
                raw_response="[Combined from chunks]",
                validation_result=validation_result,
                duration=total_duration,
                attempts=1,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens
            )
        
        elif part_name == 'part-4':
            # Combine Part-4 chunks (inline, consistent with Part-3 pattern)
            if not chunks or not chunks[0].data:
                # Error case - no valid chunks
                duration = time.time() - start_time
                return ExtractionResult(
                    part_name=part_name,
                    success=False,
                    data=None,
                    raw_response=None,
                    validation_result=None,
                    duration=duration,
                    attempts=len(chunks),
                    error="No valid chunks"
                )
            
            # Detect schema structure from first chunk
            first_data = chunks[0].data
            if 'part_4_export_scheme_details' in first_data:
                base_key = 'part_4_export_scheme_details'
            elif 'part_4_additional_details' in first_data:
                base_key = 'part_4_additional_details'
            else:
                # Fallback - just return first chunk
                return chunks[0]
            
            # Initialize merged structure with all section keys
            combined_data = {base_key: {}}
            section_keys = first_data[base_key].keys()
            
            # Initialize each section (arrays as empty lists, others from first chunk)
            for key in section_keys:
                if isinstance(first_data[base_key][key], list):
                    combined_data[base_key][key] = []
                else:
                    combined_data[base_key][key] = first_data[base_key][key]
            
            # Merge arrays from all chunks
            for chunk in chunks:
                if not chunk.success or not chunk.data:
                    continue
                
                chunk_sections = chunk.data.get(base_key, {})
                for key in section_keys:
                    if key in chunk_sections and isinstance(chunk_sections[key], list):
                        combined_data[base_key][key].extend(chunk_sections[key])
            
            # Validate combined result
            validation_result = self.validator.validate(combined_data, part_name)
            
            total_duration = sum(c.duration for c in chunks)
            total_input_tokens = sum(c.input_tokens for c in chunks)
            total_output_tokens = sum(c.output_tokens for c in chunks)
            
            self.logger.info(f"    Combined Part-4 from {len(chunks)} chunks")
            self.logger.info(f"    Total Tokens - Input: {total_input_tokens}, Output: {total_output_tokens}")
            
            return ExtractionResult(
                part_name=part_name,
                success=not validation_result.has_critical_errors(),
                data=combined_data,
                raw_response="[Combined from chunks]",
                validation_result=validation_result,
                duration=total_duration,
                attempts=1,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens
            )

        # For other parts, just return first chunk
        return chunks[0] if chunks else None

    def _extract_part_with_text(
        self,
        pdf_path: str,
        part_name: str,
        page_range: PageRange,
        context: Optional[Dict] = None,
        max_retries: int = 3
    ) -> ExtractionResult:
        """
        Extract a part using pdfplumber text extraction + LLM
        Better for complex tables where image-based extraction struggles

        Args:
            pdf_path: Path to PDF
            part_name: Part identifier (e.g., 'part-3')
            page_range: Pages to extract
            context: Optional context
            max_retries: Maximum retry attempts

        Returns:
            ExtractionResult
        """
        page_info = f"{page_range.start}-{page_range.end}"
        self.logger.part_start(part_name, page_info)
        self.logger.info(f"    Using multimodal extraction (text + images)")

        start_time = time.time()
        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                # Get available API key
                api_key = self.api_manager.get_available_key(wait=True, max_wait=60.0)
                api_key_preview = f"{api_key[:8]}...{api_key[-4:]}"

                # Get model
                model = self._get_model()
                self.logger.api_request(api_key_preview, model.model_name)

                # Build prompt
                schema_path = f"{self.schema_dir}/{part_name}.json"
                prompt = self.prompt_builder.build_prompt(part_name, schema_path, context)

                # Extract text using pdfplumber
                extracted_text = self._extract_text_from_pages(pdf_path, page_range)
                
                # Combine prompt with extracted text
                full_prompt = f"{prompt}\n\n**EXTRACTED TEXT FROM DOCUMENT:**\n\n{extracted_text}"

                # Also extract pages as images
                images = self._extract_pages_as_images(pdf_path, page_range)

                # Make API call with prompt + text + images (multimodal)
                api_start = time.time()
                response = model.generate_content([full_prompt] + images, stream=False)
                api_duration = time.time() - api_start

                self.logger.api_response(api_duration)
                
                # Extract token usage from Gemini API response
                input_tokens = 0
                output_tokens = 0
                
                if hasattr(response, 'usage_metadata'):
                    input_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0)
                    output_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0)
                    self.logger.info(f"    Tokens - Input: {input_tokens}, Output: {output_tokens}")

                # Parse response (same logic as image-based extraction)
                raw_response = response.text
                data = self._parse_json_response(raw_response)

                # Fix Part 4 empty arrays if needed
                data = self._fix_part4_empty_arrays(data, part_name)

                # Fix empty challan_details if needed (only for part-1)
                data = self._fix_empty_challan_details(data, part_name)

                # Validate
                validation_result = self.validator.validate(data, part_name)

                duration = time.time() - start_time
                success = not validation_result.has_critical_errors()

                self.logger.part_complete(part_name, success, duration)
                self.logger.validation_result(
                    part_name,
                    validation_result.is_valid,
                    len(validation_result.errors),
                    len(validation_result.warnings)
                )

                return ExtractionResult(
                    part_name=part_name,
                    success=success,
                    data=data,
                    raw_response=raw_response,
                    validation_result=validation_result,
                    duration=duration,
                    attempts=attempt,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens
                )

            except json.JSONDecodeError as e:
                last_error = f"JSON parsing error: {str(e)}"
                self.logger.retry_attempt(attempt, max_retries, last_error)

            except Exception as e:
                last_error = f"Extraction error: {str(e)}"
                self.logger.retry_attempt(attempt, max_retries, last_error)

            # Wait before retry (exponential backoff)
            if attempt < max_retries:
                wait_time = config.gemini.retry_delay * (2 ** (attempt - 1))
                time.sleep(wait_time)

        # All retries failed
        duration = time.time() - start_time
        self.logger.part_complete(part_name, False, duration)

        return ExtractionResult(
            part_name=part_name,
            success=False,
            data=None,
            raw_response=None,
            validation_result=None,
            duration=duration,
            attempts=max_retries,
            error=last_error
        )

    def _extract_text_from_pages(self, pdf_path: str, page_range: PageRange) -> str:
        """
        Extract text from specified pages using pdfplumber

        Args:
            pdf_path: Path to PDF
            page_range: Pages to extract

        Returns:
            Concatenated text from all pages
        """
        text_parts = []

        with pdfplumber.open(pdf_path) as pdf:
            # Convert to 0-indexed
            start_idx = page_range.start - 1
            end_idx = page_range.end  # end is inclusive

            for page_num in range(start_idx, end_idx):
                if page_num < len(pdf.pages):
                    page = pdf.pages[page_num]
                    text = page.extract_text()
                    if text:
                        text_parts.append(f"=== PAGE {page_num + 1} ===\n{text}\n")

        return "\n".join(text_parts)

    def _extract_part6_with_pdfplumber(
        self,
        pdf_path: str,
        part_name: str,
        page_range: PageRange
    ) -> ExtractionResult:
        """
        Extract Part 6 using pdfplumber text extraction
        Avoids Gemini RECITATION issues by parsing text directly

        Args:
            pdf_path: Path to PDF
            part_name: Should be 'part-6'
            page_range: Pages to extract

        Returns:
            ExtractionResult
        """
        page_info = f"{page_range.start}-{page_range.end}"
        self.logger.part_start(part_name, page_info)
        self.logger.info(f"    Using pdfplumber text extraction (avoids RECITATION issues)")

        start_time = time.time()

        try:
            # Extract using pdfplumber
            data = extract_part6(pdf_path, page_range)

            # Validate
            validation_result = self.validator.validate(data, part_name)

            duration = time.time() - start_time
            success = not validation_result.has_critical_errors()

            self.logger.part_complete(part_name, success, duration)
            self.logger.validation_result(
                part_name,
                validation_result.is_valid,
                len(validation_result.errors),
                len(validation_result.warnings)
            )

            # Log extraction stats
            decl_count = len(data.get("part_6_declaration", {}).get("declaration_statement", []))
            self.logger.info(f"    Extracted {decl_count} declaration statements")

            return ExtractionResult(
                part_name=part_name,
                success=success,
                data=data,
                raw_response="[Extracted via pdfplumber]",
                validation_result=validation_result,
                duration=duration,
                attempts=1
            )

        except Exception as e:
            duration = time.time() - start_time
            error_msg = f"pdfplumber extraction error: {str(e)}"

            self.logger.part_complete(part_name, False, duration)
            self.logger.error(f"    {error_msg}")

            return ExtractionResult(
                part_name=part_name,
                success=False,
                data=None,
                raw_response=None,
                validation_result=None,
                duration=duration,
                attempts=1,
                error=error_msg
            )


if __name__ == "__main__":
    # Test extraction pipeline
    from bill_of_entry_extractor.bill_of_entry.analyzer import analyze_bill_of_entry

    pdf_path = "data/invoices/bill_of_entry.pdf"

    # Analyze document
    structure = analyze_bill_of_entry(pdf_path)
    print(structure)

    # Initialize components
    api_manager = APIKeyManager(config.gemini.api_keys, config.gemini.requests_per_minute)
    validator = SchemaValidator()
    pipeline = ExtractionPipeline(api_manager, validator)

    # Test extracting Part I
    part1_section = structure.get_section('PART-I')
    if part1_section:
        print(f"\nExtracting {part1_section}")
        result = pipeline.extract_part(pdf_path, 'part-1', part1_section)
        print(f"\nResult: {result.success}")
        if result.validation_result:
            print(result.validation_result)
