#!/usr/bin/env python3
"""
Shipping Bill Extractor
Handles extraction of export clearance documents (5 parts: Parts I-V)
"""

from typing import List
from bill_of_entry_extractor.core.base_extractor import BaseDocumentExtractor
from bill_of_entry_extractor.core.document_types import SHIPPING_BILL_CONFIG
from bill_of_entry_extractor.utils.api_key_manager import APIKeyManager
from bill_of_entry_extractor.shipping_bill.analyzer import analyze_shipping_bill
from bill_of_entry_extractor.shipping_bill.prompts import ShippingBillPromptBuilder
from bill_of_entry_extractor.extractor.pipeline import ExtractionResult


class ShippingBillExtractor(BaseDocumentExtractor):
    """
    Shipping Bill extractor
    Extracts all 5 parts (Parts I-V) from Indian Customs export documents
    """

    def __init__(self, api_manager: APIKeyManager, output_dir: str = None):
        """
        Initialize Shipping Bill extractor

        Args:
            api_manager: API key manager instance
            output_dir: Output directory (optional override)
        """
        super().__init__(
            config=SHIPPING_BILL_CONFIG,
            api_manager=api_manager,
            output_dir=output_dir,
            prompt_builder=ShippingBillPromptBuilder
        )

    def analyze(self, pdf_path: str):
        """
        Analyze Shipping Bill document structure

        Args:
            pdf_path: Path to PDF file

        Returns:
            DocumentStructure with detected parts (PART-I through PART-V)
        """
        return analyze_shipping_bill(pdf_path)

    def extract_all_parts(
        self,
        pdf_path: str,
        structure,
        save_intermediate: bool
    ) -> List[ExtractionResult]:
        """
        Extract all parts from Shipping Bill

        Args:
            pdf_path: Path to PDF file
            structure: DocumentStructure from analyze()
            save_intermediate: Whether to save intermediate results

        Returns:
            List of ExtractionResult objects
        """
        results = []

        # Process Part 0 (Header Information)
        part0_section = structure.get_section('PART-0')
        if part0_section:
            result = self.pipeline.extract_part(pdf_path, 'part-0', part0_section)
            results.append(result)
            if save_intermediate:
                self._save_part_result(None, result)

        # Process Part I (Summary - typically 2 pages)
        part1_section = structure.get_section('PART-I')
        if part1_section:
            result = self.pipeline.extract_part(pdf_path, 'part-1', part1_section)
            results.append(result)
            if save_intermediate:
                self._save_part_result(None, result)

        # Process Part II (Invoice Details - use multimodal for multiple invoice tables)
        part2_section = structure.get_section('PART-II')
        if part2_section:
            result = self.pipeline.extract_part(pdf_path, 'part-2', part2_section, use_text_extraction=True)
            results.append(result)
            if save_intermediate:
                self._save_part_result(None, result)

        # Process Part III (Item Details - may need chunking if large)
        part3_section = structure.get_section('PART-III')
        if part3_section:
            page_count = part3_section.end - part3_section.start + 1

            # Use multimodal extraction (text + images) for better table accuracy
            if page_count > 8:
                self.logger.info(f"    Part III has {page_count} pages - using chunked multimodal extraction")
                result = self.pipeline.extract_part_with_chunking(
                    pdf_path, 'part-3', part3_section, chunk_size=4, use_text_extraction=True
                )
            else:
                result = self.pipeline.extract_part(pdf_path, 'part-3', part3_section, use_text_extraction=True)

            results.append(result)
            if save_intermediate:
                self._save_part_result(None, result)

        # Process Part IV (Export Scheme Details - use chunking if large)
        part4_section = structure.get_section('PART-IV')
        if part4_section:
            page_count = part4_section.end - part4_section.start + 1
            
            # Use chunking for large Part IV (>5 pages) to avoid timeouts
            if page_count > 5:
                self.logger.info(f"    Part IV has {page_count} pages - using chunked multimodal extraction")
                result = self.pipeline.extract_part_with_chunking(
                    pdf_path, 'part-4', part4_section, chunk_size=2, use_text_extraction=True
                )
            else:
                result = self.pipeline.extract_part(pdf_path, 'part-4', part4_section, use_text_extraction=True)
            
            results.append(result)
            if save_intermediate:
                self._save_part_result(None, result)

        # Process Part V (Declarations - always use Gemini Vision as per user requirement)
        part5_section = structure.get_section('PART-V')
        if part5_section:
            result = self.pipeline.extract_part(pdf_path, 'part-5', part5_section)
            results.append(result)
            if save_intermediate:
                self._save_part_result(None, result)

        return results

    def _combine_results(self, results: List[ExtractionResult], structure) -> dict:
        """
        Combine Shipping Bill extraction results

        Args:
            results: List of ExtractionResult objects
            structure: DocumentStructure

        Returns:
            Combined data dictionary
        """
        # Use base combination logic
        combined = super()._combine_results(results, structure)

        # Add Shipping Bill specific metadata if present
        if structure.metadata:
            combined['metadata'] = {
                'shipping_bill_metadata': structure.metadata
            }

        # Validate cross-part consistency for Shipping Bill
        self._validate_shipping_bill_consistency(combined)

        return combined

    def _validate_shipping_bill_consistency(self, combined: dict):
        """
        Validate consistency across Shipping Bill parts

        Args:
            combined: Combined extraction results
        """
        parts = combined.get('parts', {})

        # Get key values from different parts
        part1_data = parts.get('part-1', {}).get('part_1_summary', {})
        part2_data = parts.get('part-2', {}).get('part_2_invoice_valuation', {})
        part3_data = parts.get('part-3', {}).get('part_3_item_details', {})

        # Cross-validate FOB values across parts
        part1_fob = part1_data.get('value_summary', {}).get('total_fob_value_inr', 0)

        # Sum of invoice FOB values from Part II
        part2_invoices = part2_data.get('invoices', [])
        part2_fob_total = sum(inv.get('valuation', {}).get('fob_value_inr', 0) for inv in part2_invoices)

        # Sum of item FOB values from Part III
        part3_summary = part3_data.get('summary', {})
        part3_fob = part3_summary.get('total_fob_value_inr', 0)

        # Log warnings if values don't match (allow 1% variance)
        if part1_fob and part2_fob_total:
            variance = abs(part1_fob - part2_fob_total) / part1_fob if part1_fob else 0
            if variance > 0.01:
                self.logger.warning(
                    f"FOB value mismatch: Part I ({part1_fob}) vs Part II ({part2_fob_total})"
                )

        if part1_fob and part3_fob:
            variance = abs(part1_fob - part3_fob) / part1_fob if part1_fob else 0
            if variance > 0.01:
                self.logger.warning(
                    f"FOB value mismatch: Part I ({part1_fob}) vs Part III ({part3_fob})"
                )

        # Validate scheme amounts between Part III and Part IV
        part4_data = parts.get('part-4', {}).get('part_4_export_scheme_details', {})

        # DBK validation
        part3_total_dbk = part3_summary.get('total_dbk', 0)
        part4_dbk = part4_data.get('duty_drawback', {}).get('dbk_amount', 0)
        if part3_total_dbk and part4_dbk:
            variance = abs(part3_total_dbk - part4_dbk) / part3_total_dbk if part3_total_dbk else 0
            if variance > 0.01:
                self.logger.warning(
                    f"DBK amount mismatch: Part III ({part3_total_dbk}) vs Part IV ({part4_dbk})"
                )

        # RODTEP validation
        part3_total_rodtep = part3_summary.get('total_rodtep', 0)
        part4_rodtep = part4_data.get('rodtep', {}).get('rodtep_amount', 0)
        if part3_total_rodtep and part4_rodtep:
            variance = abs(part3_total_rodtep - part4_rodtep) / part3_total_rodtep if part3_total_rodtep else 0
            if variance > 0.01:
                self.logger.warning(
                    f"RODTEP amount mismatch: Part III ({part3_total_rodtep}) vs Part IV ({part4_rodtep})"
                )
