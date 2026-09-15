#!/usr/bin/env python3
"""
Comprehensive Logging System
Provides structured logging with file and console output
"""

import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional


class ExtractionLogger:
    """Custom logger for extraction pipeline"""

    def __init__(self, name: str = "bill_of_entry_extractor", log_file: Optional[str] = None, log_level: str = "INFO"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, log_level.upper()))

        # Remove existing handlers
        self.logger.handlers.clear()

        # Create formatters
        detailed_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        simple_formatter = logging.Formatter(
            '%(levelname)s: %(message)s'
        )

        # Console handler (simple format)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(simple_formatter)
        self.logger.addHandler(console_handler)

        # File handler (detailed format)
        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(detailed_formatter)
            self.logger.addHandler(file_handler)

    def debug(self, message: str):
        self.logger.debug(message)

    def info(self, message: str):
        self.logger.info(message)

    def warning(self, message: str):
        self.logger.warning(message)

    def error(self, message: str):
        self.logger.error(message)

    def critical(self, message: str):
        self.logger.critical(message)

    def extraction_start(self, pdf_path: str):
        self.info(f"=" * 80)
        self.info(f"EXTRACTION STARTED: {Path(pdf_path).name}")
        self.info(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.info(f"=" * 80)

    def extraction_complete(self, pdf_path: str, duration: float):
        self.info(f"=" * 80)
        self.info(f"EXTRACTION COMPLETED: {Path(pdf_path).name}")
        self.info(f"Duration: {duration:.2f} seconds")
        self.info(f"=" * 80)

    def part_start(self, part_name: str, page_range: Optional[str] = None):
        page_info = f" (pages {page_range})" if page_range else ""
        self.info(f"\n>>> Processing {part_name.upper()}{page_info}")

    def part_complete(self, part_name: str, success: bool, duration: float):
        status = "✅ SUCCESS" if success else "❌ FAILED"
        self.info(f"<<< {part_name.upper()} completed: {status} ({duration:.2f}s)")

    def validation_result(self, part_name: str, is_valid: bool, error_count: int, warning_count: int):
        if is_valid:
            self.info(f"    Validation: ✅ PASSED (warnings: {warning_count})")
        else:
            self.warning(f"    Validation: ❌ FAILED (errors: {error_count}, warnings: {warning_count})")

    def api_request(self, api_key_preview: str, model: str):
        self.debug(f"    API Request: key={api_key_preview}, model={model}")

    def api_response(self, duration: float, token_count: Optional[int] = None):
        token_info = f", tokens={token_count}" if token_count else ""
        self.debug(f"    API Response: {duration:.2f}s{token_info}")

    def retry_attempt(self, attempt: int, max_retries: int, error: str):
        self.warning(f"    Retry {attempt}/{max_retries} after error: {error}")

    def save_file(self, file_path: str, file_type: str):
        self.debug(f"    Saved {file_type}: {file_path}")


# Global logger instance
_logger: Optional[ExtractionLogger] = None


def get_logger() -> ExtractionLogger:
    """Get or create global logger instance"""
    global _logger
    if _logger is None:
        # Create logs directory
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        # Generate log filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = log_dir / f"extraction_{timestamp}.log"

        _logger = ExtractionLogger(log_file=str(log_file))

    return _logger


if __name__ == "__main__":
    # Test logger
    logger = get_logger()

    logger.extraction_start("test_invoice.pdf")
    logger.part_start("part-1", "1-3")
    logger.api_request("AIza****", "gemini-2.0-flash")
    logger.api_response(2.5, 1500)
    logger.part_complete("part-1", True, 3.2)
    logger.validation_result("part-1", True, 0, 2)
    logger.extraction_complete("test_invoice.pdf", 45.7)
