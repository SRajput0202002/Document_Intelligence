#!/usr/bin/env python3
"""
Main Bill of Entry Extractor - CLI Entry Point
Orchestrates the complete extraction pipeline for import documents
"""

import argparse
import sys

from bill_of_entry_extractor.config import config
from bill_of_entry_extractor.utils.api_key_manager import APIKeyManager
from bill_of_entry_extractor.bill_of_entry.extractor import BillOfEntryExtractor as BEExtractor


# Maintain backward compatibility - expose BillOfEntryExtractor at module level
class BillOfEntryExtractor(BEExtractor):
    """
    Backward compatibility wrapper for BillOfEntryExtractor
    Delegates to the new bill_of_entry.extractor.BillOfEntryExtractor
    """

    def __init__(self, output_dir: str = "output"):
        """
        Initialize Bill of Entry extractor with simplified interface

        Args:
            output_dir: Output directory for extraction results
        """
        # Initialize API manager
        api_manager = APIKeyManager(
            api_keys=config.gemini.api_keys,
            requests_per_minute=config.gemini.requests_per_minute
        )

        # Call parent constructor
        super().__init__(api_manager=api_manager, output_dir=output_dir)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Extract structured data from Indian Customs Bill of Entry PDFs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract a Bill of Entry
  python bill_of_entry_extractor.py invoice.pdf

  # Specify output directory
  python bill_of_entry_extractor.py invoice.pdf --output results/

  # Don't save intermediate results
  python bill_of_entry_extractor.py invoice.pdf --no-intermediate
        """
    )

    parser.add_argument('pdf', help='Path to Bill of Entry PDF file')
    parser.add_argument('--output', '-o', default='output', help='Output directory (default: output/)')
    parser.add_argument('--no-intermediate', action='store_true', help='Don\'t save intermediate part results')

    args = parser.parse_args()

    try:
        # Validate config
        config.validate()

        # Create extractor (now with automatic API manager setup)
        extractor = BillOfEntryExtractor(output_dir=args.output)

        # Extract
        result = extractor.extract(
            args.pdf,
            save_intermediate=not args.no_intermediate
        )

        sys.exit(0)

    except FileNotFoundError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Fatal error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
