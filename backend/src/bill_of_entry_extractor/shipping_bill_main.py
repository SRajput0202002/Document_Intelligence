#!/usr/bin/env python3
"""
Main Shipping Bill Extractor - CLI Entry Point
Orchestrates the complete extraction pipeline for export documents
"""

import argparse
import sys

from bill_of_entry_extractor.config import config
from bill_of_entry_extractor.utils.api_key_manager import APIKeyManager
from bill_of_entry_extractor.shipping_bill.extractor import ShippingBillExtractor as SBExtractor


# Maintain backward compatibility - expose ShippingBillExtractor at module level
class ShippingBillExtractor(SBExtractor):
    """
    Backward compatibility wrapper for ShippingBillExtractor
    Delegates to the new shipping_bill.extractor.ShippingBillExtractor
    """

    def __init__(self, output_dir: str = "output"):
        """
        Initialize Shipping Bill extractor with simplified interface

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
        description='Extract structured data from Indian Customs Shipping Bill PDFs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract a Shipping Bill
  python shipping_bill_main.py export_doc.pdf

  # Specify output directory
  python shipping_bill_main.py export_doc.pdf --output results/

  # Don't save intermediate results
  python shipping_bill_main.py export_doc.pdf --no-intermediate
        """
    )

    parser.add_argument('pdf', help='Path to Shipping Bill PDF file')
    parser.add_argument('--output', '-o', default='output', help='Output directory (default: output/)')
    parser.add_argument('--no-intermediate', action='store_true', help='Don\'t save intermediate part results')

    args = parser.parse_args()

    try:
        # Validate config
        config.validate()

        # Create extractor (now with automatic API manager setup)
        extractor = ShippingBillExtractor(output_dir=args.output)

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
