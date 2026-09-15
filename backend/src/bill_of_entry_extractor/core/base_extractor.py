#!/usr/bin/env python3
"""
Abstract base class for document extractors
Provides common interface and shared functionality for all document types
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
from core.utils.datetime_util import ist_isoformat
import time
import json

from bill_of_entry_extractor.core.document_types import DocumentConfig
from bill_of_entry_extractor.utils.api_key_manager import APIKeyManager
from bill_of_entry_extractor.utils.logger import get_logger
from bill_of_entry_extractor.validation.validator import SchemaValidator, CrossValidator
from bill_of_entry_extractor.extractor.pipeline import ExtractionPipeline, ExtractionResult


class BaseDocumentExtractor(ABC):
    """
    Abstract base class for document extractors

    All document-specific extractors (BillOfEntryExtractor, ShippingBillExtractor)
    inherit from this class and implement document-specific logic.
    """

    def __init__(
        self,
        config: DocumentConfig,
        api_manager: APIKeyManager,
        output_dir: Optional[str] = None,
        prompt_builder = None
    ):
        """
        Initialize base extractor

        Args:
            config: Document-specific configuration
            api_manager: API key manager instance
            output_dir: Base output directory (optional override)
            prompt_builder: Document-specific prompt builder class
        """
        self.config = config
        self.api_manager = api_manager
        self.logger = get_logger()

        # Output directory
        if output_dir:
            self.output_dir = Path(output_dir)
        else:
            self.output_dir = Path(config.output_base_dir) / config.output_subdir

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Current document directory (set during extraction)
        self.current_doc_dir = None

        # Initialize components
        schema_full_path = str(Path(config.schema_dir))
        self.validator = SchemaValidator(schema_dir=schema_full_path)
        self.cross_validator = CrossValidator()
        self.pipeline = ExtractionPipeline(
            self.api_manager,
            self.validator,
            prompt_builder=prompt_builder,
            schema_dir=schema_full_path
        )

    @abstractmethod
    def analyze(self, pdf_path: str):
        """
        Analyze document structure and detect parts

        Args:
            pdf_path: Path to PDF file

        Returns:
            DocumentStructure object with detected parts
        """
        pass

    @abstractmethod
    def extract_all_parts(
        self,
        pdf_path: str,
        structure,
        save_intermediate: bool
    ) -> List[ExtractionResult]:
        """
        Extract all parts from the document

        Args:
            pdf_path: Path to PDF file
            structure: DocumentStructure from analyze()
            save_intermediate: Whether to save intermediate results

        Returns:
            List of ExtractionResult objects
        """
        pass

    def extract(self, pdf_path: str, save_intermediate: bool = True) -> Dict:
        """
        Main extraction method - orchestrates the complete extraction pipeline

        Args:
            pdf_path: Path to PDF file
            save_intermediate: Save intermediate results for each part

        Returns:
            Dictionary with all extracted data

        Raises:
            FileNotFoundError: If PDF file doesn't exist
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        # Create document-specific directory
        doc_id = self._get_document_id(pdf_path)
        self.current_doc_dir = self.output_dir / doc_id
        self.current_doc_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info(f"📁 Output directory: {self.current_doc_dir}")
        self.logger.extraction_start(str(pdf_path))

        start_time = time.time()

        # Step 1: Analyze document structure
        self.logger.info(f"\n[1/4] Analyzing {self.config.display_name} structure...")
        structure = self.analyze(str(pdf_path))
        self._log_structure(structure)

        # Step 2: Extract each part
        self.logger.info(f"\n[2/4] Extracting parts from {self.config.display_name}...")
        results = self.extract_all_parts(str(pdf_path), structure, save_intermediate)

        # Step 3: Validate individual parts
        self.logger.info("\n[3/4] Validating extracted data...")
        self._log_validation_summary(results)

        # Step 4: Cross-validate
        self.logger.info("\n[4/4] Cross-validating parts...")
        all_parts_data = {r.part_name: r.data for r in results if r.success and r.data}
        cross_validation = self.cross_validator.validate(all_parts_data)

        if cross_validation.warnings:
            self.logger.warning(f"    Cross-validation found {len(cross_validation.warnings)} warnings")
            for warning in cross_validation.warnings[:3]:
                self.logger.warning(f"      - {warning.message}")

        # Combine results
        combined_data = self._combine_results(results, structure)

        # Save final output
        output_file = self._save_final_output(pdf_path, combined_data)

        duration = time.time() - start_time
        self.logger.extraction_complete(str(pdf_path), duration)

        # Print summary
        self._print_summary(results, output_file, duration)

        return combined_data

    def _get_document_id(self, pdf_path: Path) -> str:
        """
        Extract document ID from PDF filename
        Override in subclass if needed

        Args:
            pdf_path: Path to PDF file

        Returns:
            Document ID (default: filename stem)
        """
        return pdf_path.stem

    def _log_structure(self, structure):
        """Log document structure information"""
        self.logger.info(f"    Total pages: {structure.total_pages}")

        # Group sections by part for cleaner logging
        parts = {}
        for section in structure.sections:
            if section.part_name not in parts:
                parts[section.part_name] = {'start': section.start, 'end': section.end, 'count': 1}
            else:
                parts[section.part_name]['start'] = min(parts[section.part_name]['start'], section.start)
                parts[section.part_name]['end'] = max(parts[section.part_name]['end'], section.end)
                parts[section.part_name]['count'] += 1

        self.logger.info(f"    Parts found: {len(parts)}")
        for part_name in sorted(parts.keys(), key=lambda x: parts[x]['start']):
            part_range = parts[part_name]
            page_count = part_range['end'] - part_range['start'] + 1
            self.logger.info(
                f"    {part_name}: pages {part_range['start']}-{part_range['end']} "
                f"({page_count} page{'s' if page_count > 1 else ''})"
            )

    def _combine_results(self, results: List[ExtractionResult], structure) -> Dict:
        """
        Combine all extraction results into final output

        Args:
            results: List of ExtractionResult objects
            structure: DocumentStructure object

        Returns:
            Combined data dictionary
        """
        combined = {
            'metadata': {
                'extraction_date': ist_isoformat(datetime.utcnow()),
                'document_type': str(self.config.document_type.value),
                'document_metadata': structure.metadata if hasattr(structure, 'metadata') else {},
                'total_pages': structure.total_pages,
                'extraction_summary': {
                    'total_parts': len(results),
                    'successful_parts': sum(1 for r in results if r.success),
                    'failed_parts': sum(1 for r in results if not r.success),
                }
            },
            'parts': {}
        }

        # Add each extracted part
        for result in results:
            if result.success and result.data:
                combined['parts'][result.part_name] = result.data

        return combined

    def _save_part_result(self, pdf_path: Path, result: ExtractionResult, suffix: str = ""):
        """Save intermediate result for a single part"""
        if not result.data:
            return

        filename = f"{result.part_name}{suffix}.json"
        output_path = self.current_doc_dir / filename

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result.data, f, indent=2, ensure_ascii=False)

        self.logger.save_file(str(output_path), "part JSON")

    def _save_final_output(self, pdf_path: Path, combined_data: Dict) -> Path:
        """Save final combined output"""
        filename = "all_parts.json"
        output_path = self.current_doc_dir / filename

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(combined_data, f, indent=2, ensure_ascii=False)

        self.logger.save_file(str(output_path), "final JSON")
        return output_path

    def _log_validation_summary(self, results: List[ExtractionResult]):
        """Log validation summary for all parts"""
        for result in results:
            if result.validation_result:
                status = "✅" if result.validation_result.is_valid else "❌"
                self.logger.info(
                    f"    {status} {result.part_name}: "
                    f"errors={len(result.validation_result.errors)}, "
                    f"warnings={len(result.validation_result.warnings)}"
                )

    def _print_summary(self, results: List[ExtractionResult], output_file: Path, duration: float):
        """Print extraction summary to console"""
        print("\n" + "=" * 80)
        print(f"{self.config.display_name.upper()} EXTRACTION SUMMARY")
        print("=" * 80)

        successful = sum(1 for r in results if r.success)
        total = len(results)

        print(f"Parts processed: {successful}/{total} successful")
        print(f"Duration: {duration:.2f} seconds")
        print(f"Output: {output_file}")
        
        # Token usage summary
        total_input_tokens = sum(r.input_tokens for r in results)
        total_output_tokens = sum(r.output_tokens for r in results)
        
        print(f"\n📊 TOKEN USAGE:")
        print(f"   Input tokens:  {total_input_tokens:,}")
        print(f"   Output tokens: {total_output_tokens:,}")
        
        # Show per-part breakdown
        print(f"\n📋 Per-part breakdown:")
        for result in results:
            if result.input_tokens > 0 or result.output_tokens > 0:
                status = "✅" if result.success else "❌"
                print(f"   {status} {result.part_name:8} - Input: {result.input_tokens:6,}, Output: {result.output_tokens:6,}")

        # Show failed parts
        failed = [r for r in results if not r.success]
        if failed:
            print("\n⚠️  Failed parts:")
            for r in failed:
                print(f"  - {r.part_name}: {r.error}")

        # Show validation warnings
        warned = [r for r in results if r.validation_result and r.validation_result.warnings]
        if warned:
            print(f"\n⚠️  Parts with validation warnings: {len(warned)}")

        # API stats
        stats = self.api_manager.get_stats()
        print(f"\nAPI Usage:")
        print(f"  Total requests: {stats['total_requests']}")
        print(f"  Keys used: {stats['available_keys']}/{stats['total_keys']}")

        print("=" * 80 + "\n")
