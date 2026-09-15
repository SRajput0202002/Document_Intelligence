#!/usr/bin/env python3
"""
Test script for OCR providers.

Tests all available OCR providers against a sample PDF document.
Usage: python test_ocr_providers.py /path/to/document.pdf
"""

import sys
import time
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Import the registry
from core.registry import ProviderRegistry
from core.providers import ocr  # This triggers provider registration


def test_ocr_providers(pdf_path: str, providers_to_test: list = None):
    """
    Test OCR providers against a PDF document.

    Args:
        pdf_path: Path to PDF document to test
        providers_to_test: Optional list of provider names to test.
                          If None, tests all available providers.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        logger.error(f"PDF file not found: {pdf_path}")
        return

    logger.info(f"Testing OCR providers with: {pdf_path.name}")
    logger.info("=" * 60)

    # Get all OCR providers
    all_providers = ProviderRegistry.list_ocr_providers()

    logger.info(f"\nFound {len(all_providers)} OCR providers:")
    for info in all_providers:
        status = "✓ Available" if info.is_available else f"✗ Unavailable: {info.error}"
        logger.info(f"  - {info.display_name} ({info.name}): {status}")

    logger.info("\n" + "=" * 60)

    # Filter to available providers or specific providers
    if providers_to_test:
        providers_to_test = [p.lower() for p in providers_to_test]
        available = [p for p in all_providers if p.name in providers_to_test]
    else:
        available = [p for p in all_providers if p.is_available]

    if not available:
        logger.warning("No available providers to test!")
        return

    logger.info(f"\nTesting {len(available)} available providers...")
    results = []

    for provider_info in available:
        logger.info(f"\n{'='*60}")
        logger.info(f"Testing: {provider_info.display_name} ({provider_info.name})")
        logger.info(f"Type: {provider_info.provider_type.value}, Cost: {provider_info.cost_tier.value}")
        logger.info("-" * 40)

        try:
            # Get processor instance
            processor = ProviderRegistry.get_ocr_processor(provider_info.name)

            if processor is None:
                logger.error(f"  Failed to get processor for {provider_info.name}")
                results.append({
                    "provider": provider_info.name,
                    "success": False,
                    "error": "Failed to instantiate processor",
                    "time": 0,
                    "pages": 0,
                    "chars": 0,
                })
                continue

            # Process PDF
            start_time = time.time()
            result = processor.process_pdf(str(pdf_path))
            elapsed = time.time() - start_time

            if result.success:
                text_sample = result.full_text[:500] + "..." if len(result.full_text) > 500 else result.full_text
                logger.info(f"  ✓ Success!")
                logger.info(f"  Pages: {result.total_pages}")
                logger.info(f"  Characters: {len(result.full_text)}")
                logger.info(f"  Time: {elapsed:.2f}s")
                logger.info(f"  Model: {result.model}")
                if result.usage_info:
                    logger.info(f"  Usage: {result.usage_info}")
                logger.info(f"\n  Sample output:\n  {text_sample[:300]}...")

                results.append({
                    "provider": provider_info.name,
                    "success": True,
                    "error": None,
                    "time": elapsed,
                    "pages": result.total_pages,
                    "chars": len(result.full_text),
                    "model": result.model,
                })
            else:
                logger.error(f"  ✗ Failed: {result.error}")
                results.append({
                    "provider": provider_info.name,
                    "success": False,
                    "error": result.error,
                    "time": elapsed,
                    "pages": 0,
                    "chars": 0,
                })

        except Exception as e:
            logger.exception(f"  ✗ Exception: {e}")
            results.append({
                "provider": provider_info.name,
                "success": False,
                "error": str(e),
                "time": 0,
                "pages": 0,
                "chars": 0,
            })

    # Print summary
    logger.info("\n" + "=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)

    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]

    logger.info(f"\nSuccessful: {len(successful)}/{len(results)}")
    for r in successful:
        logger.info(f"  ✓ {r['provider']}: {r['chars']} chars in {r['time']:.2f}s")

    if failed:
        logger.info(f"\nFailed: {len(failed)}/{len(results)}")
        for r in failed:
            logger.info(f"  ✗ {r['provider']}: {r['error']}")

    return results


def list_providers():
    """List all registered OCR providers."""
    providers = ProviderRegistry.list_ocr_providers()

    print("\n" + "=" * 70)
    print("Available OCR Providers")
    print("=" * 70)

    cloud_providers = [p for p in providers if p.provider_type.value == "cloud"]
    local_providers = [p for p in providers if p.provider_type.value == "local"]

    print("\n📡 Cloud Providers:")
    for p in cloud_providers:
        status = "✅" if p.is_available else "❌"
        print(f"  {status} {p.display_name} ({p.name})")
        print(f"      Cost: {p.cost_tier.value}, API Key: {p.api_key_env_var or 'N/A'}")
        if not p.is_available:
            print(f"      Error: {p.error}")

    print("\n💻 Local Providers:")
    for p in local_providers:
        status = "✅" if p.is_available else "❌"
        print(f"  {status} {p.display_name} ({p.name})")
        print(f"      Cost: {p.cost_tier.value}")
        if not p.is_available:
            print(f"      Error: {p.error}")

    print("\n" + "=" * 70)
    available_count = sum(1 for p in providers if p.is_available)
    print(f"Total: {len(providers)} providers ({available_count} available)")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_ocr_providers.py <pdf_path> [provider1,provider2,...]")
        print("       python test_ocr_providers.py --list")
        print("\nExamples:")
        print("  python test_ocr_providers.py invoice.pdf")
        print("  python test_ocr_providers.py invoice.pdf tesseract,easyocr,pymupdf")
        print("  python test_ocr_providers.py --list")
        sys.exit(1)

    if sys.argv[1] == "--list":
        list_providers()
    else:
        pdf_path = sys.argv[1]
        providers = sys.argv[2].split(",") if len(sys.argv) > 2 else None
        test_ocr_providers(pdf_path, providers)
