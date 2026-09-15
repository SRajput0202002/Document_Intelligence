#!/usr/bin/env python3
"""
Bill of Entry Extractor
Handles extraction of import clearance documents (7 parts: Parts 0-6)
"""

from typing import List
from bill_of_entry_extractor.core.base_extractor import BaseDocumentExtractor
from bill_of_entry_extractor.core.document_types import BILL_OF_ENTRY_CONFIG
from bill_of_entry_extractor.utils.api_key_manager import APIKeyManager
from bill_of_entry_extractor.bill_of_entry.analyzer import analyze_bill_of_entry
from bill_of_entry_extractor.bill_of_entry.prompts import BillOfEntryPromptBuilder
from bill_of_entry_extractor.extractor.pipeline import ExtractionResult


class BillOfEntryExtractor(BaseDocumentExtractor):
    """
    Bill of Entry extractor
    Extracts all 7 parts (Parts 0-6) from Indian Customs import documents
    """

    def __init__(self, api_manager: APIKeyManager, output_dir: str = None):
        """
        Initialize Bill of Entry extractor

        Args:
            api_manager: API key manager instance
            output_dir: Output directory (optional override)
        """
        super().__init__(
            config=BILL_OF_ENTRY_CONFIG,
            api_manager=api_manager,
            output_dir=output_dir,
            prompt_builder=BillOfEntryPromptBuilder
        )

    def analyze(self, pdf_path: str):
        """
        Analyze Bill of Entry document structure

        Args:
            pdf_path: Path to PDF file

        Returns:
            DocumentStructure with detected parts (PART-0 through PART-VI)
        """
        return analyze_bill_of_entry(pdf_path)

    def extract_all_parts(
        self,
        pdf_path: str,
        structure,
        save_intermediate: bool
    ) -> List[ExtractionResult]:
        """
        Extract all parts from Bill of Entry

        Args:
            pdf_path: Path to PDF file
            structure: DocumentStructure from analyze()
            save_intermediate: Whether to save intermediate results

        Returns:
            List of ExtractionResult objects
        """
        results = []

        # Process Part 0 (header details)
        part0_section = structure.get_section('PART-0')
        if part0_section:
            result = self.pipeline.extract_part(pdf_path, 'part-0', part0_section)
            results.append(result)
            if save_intermediate:
                self._save_part_result(None, result)

        # Process Part I
        part1_section = structure.get_section('PART-I')
        if part1_section:
            result = self.pipeline.extract_part(pdf_path, 'part-1', part1_section)
            results.append(result)
            if save_intermediate:
                self._save_part_result(None, result)

        # Process Part II (may have multiple invoices)
        invoices = structure.get_invoices()
        if invoices:
            for inv_section in invoices:
                context = {
                    'invoice_number': inv_section.invoice_number,
                    'total_invoices': inv_section.total_invoices
                }
                result = self.pipeline.extract_part(pdf_path, 'part-2', inv_section, context, use_text_extraction=True)
                results.append(result)
                if save_intermediate:
                    self._save_part_result(None, result, suffix=f"_invoice{inv_section.invoice_number}")
        else:
            # Fallback: single Part II extraction
            part2_section = structure.get_section('PART-II')
            if part2_section:
                result = self.pipeline.extract_part(pdf_path, 'part-2', part2_section, use_text_extraction=True)
                results.append(result)
                if save_intermediate:
                    self._save_part_result(None, result)

        # Process Part III (DUTIES - may need chunking if too large)
        part3_section = structure.get_section('PART-III')
        if part3_section:
            page_count = part3_section.end - part3_section.start + 1

            # Use chunking for large Part III (>10 pages)
            if page_count > 1:
                self.logger.info(f"    Part III has {page_count} pages - using chunked multimodal extraction")
                result = self.pipeline.extract_part_with_chunking(
                    pdf_path, 'part-3', part3_section, chunk_size=1, use_text_extraction=False
                )
            else:
                result = self.pipeline.extract_part(pdf_path, 'part-3', part3_section, use_text_extraction=False)

            results.append(result)
            if save_intermediate:
                self._save_part_result(None, result)

        # Process Part IV (Additional Details - use chunking if large)
        part4_section = structure.get_section('PART-IV')
        if part4_section:
            page_count = part4_section.end - part4_section.start + 1
            
            # Use chunking for large Part IV (>5 pages) to avoid timeouts
            if page_count > 5:
                self.logger.info(f"    Part IV has {page_count} pages - using chunked extraction")
                result = self.pipeline.extract_part_with_chunking(
                    pdf_path, 'part-4', part4_section, chunk_size=2, use_text_extraction=True
                )
            else:
                result = self.pipeline.extract_part(pdf_path, 'part-4', part4_section, use_text_extraction=True)
            
            results.append(result)
            if save_intermediate:
                self._save_part_result(None, result)

        # Process Part V
        part5_section = structure.get_section('PART-V')
        if part5_section:
            result = self.pipeline.extract_part(pdf_path, 'part-5', part5_section)
            results.append(result)
            if save_intermediate:
                self._save_part_result(None, result)

        # Process Part VI
        part6_section = structure.get_section('PART-VI')
        if part6_section:
            result = self.pipeline.extract_part(pdf_path, 'part-6', part6_section)
            results.append(result)
            if save_intermediate:
                self._save_part_result(None, result)

        return results

    def _combine_results(self, results: List[ExtractionResult], structure) -> dict:
        """
        Combine Bill of Entry extraction results
        Handles special case of multiple Part II invoices

        Args:
            results: List of ExtractionResult objects
            structure: DocumentStructure

        Returns:
            Combined data dictionary
        """
        # Start with base combination
        combined = super()._combine_results(results, structure)

        # Special handling for Part II: merge multiple invoices
        part2_results = [r for r in results if r.part_name == 'part-2' and r.success and r.data]
        if len(part2_results) > 1:
            # Multiple invoices detected - merge them
            merged_invoices = []
            for result in part2_results:
                invoice_data = result.data.get('part_2_invoice_valuation', {})
                invoices = invoice_data.get('invoices', [])
                merged_invoices.extend(invoices)

            # Replace with merged version
            combined['parts']['part-2'] = {
                'part_2_invoice_valuation': {
                    'invoices': merged_invoices
                }
            }

        return combined
