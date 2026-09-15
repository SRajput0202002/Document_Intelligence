"""
Chandra OCR Provider - Self-contained implementation.

Chandra OCR is an open-source OCR model that converts images and PDFs
into structured formats: Markdown, HTML, and JSON.

Features:
- High accuracy (83.1% on olmOCR benchmark)
- Complex table handling
- Form processing with checkbox detection
- Multi-language support (40+ languages)
"""

import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple, Union, List

from ...base.models import ProviderInfo, ProviderType, CostTier, OCRResult, OCRPage
from ...base.ocr_processor import BaseOCRProcessor
from ...registry import ProviderRegistry

logger = logging.getLogger(__name__)


@dataclass
class ChandraConfig:
    """Chandra OCR configuration."""
    method: str = field(default_factory=lambda: os.getenv("CHANDRA_OCR_METHOD", "hf"))
    max_output_tokens: int = field(
        default_factory=lambda: int(os.getenv("CHANDRA_MAX_OUTPUT_TOKENS", "8192"))
    )
    vllm_api_base: str = field(
        default_factory=lambda: os.getenv("VLLM_API_BASE", "http://localhost:8000/v1")
    )
    model_checkpoint: str = field(
        default_factory=lambda: os.getenv("MODEL_CHECKPOINT", "datalab-to/chandra")
    )
    include_images: bool = True
    include_headers_footers: bool = False
    max_retries: int = 3
    retry_delay: float = 1.0


class ChandraOCRAdapter(BaseOCRProcessor):
    """
    Self-contained Chandra OCR adapter.

    Features:
        - Local text extraction using Chandra model
        - FREE - no API costs
        - Requires NVIDIA GPU with CUDA
        - Good for complex documents

    Requires:
        - chandra package
        - NVIDIA GPU with CUDA support
    """

    def __init__(self, config: Optional[ChandraConfig] = None):
        """
        Initialize the Chandra OCR adapter.

        Args:
            config: ChandraConfig or None (uses defaults)
        """
        self._config = config or ChandraConfig()
        super().__init__(self._config)

    def process_pdf(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """
        Process a PDF using Chandra OCR.

        Args:
            pdf_path: Path to PDF file
            page_range: Optional (start, end) page numbers (1-indexed)

        Returns:
            OCRResult with extracted text
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            return self._create_error_result(f"PDF file not found: {pdf_path}")

        start_time = time.time()
        logger.info(f"Processing PDF with Chandra OCR: {pdf_path.name}")

        try:
            result = self._process_with_cli(pdf_path, page_range)
            result.processing_time = time.time() - start_time

            logger.info(
                f"OCR completed: {result.total_pages} pages in {result.processing_time:.2f}s"
            )
            return result

        except Exception as e:
            logger.error(f"Chandra OCR failed: {e}")
            return self._create_error_result(str(e), time.time() - start_time)

    def _process_with_cli(
        self,
        pdf_path: Path,
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """Process PDF using Chandra CLI command."""

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            # Find chandra CLI in the same directory as python executable
            python_dir = Path(sys.executable).parent
            chandra_cli = python_dir / "chandra"

            if not chandra_cli.exists():
                # Fallback to PATH
                chandra_cli = "chandra"

            # Build CLI command
            cmd = [
                str(chandra_cli),
                str(pdf_path.absolute()),
                str(output_dir),
                "--method", self._config.method,
            ]

            # Add page range if specified
            if page_range:
                start, end = page_range
                cmd.extend(["--page-range", f"{start}-{end}"])

            # Add other options
            if not self._config.include_images:
                cmd.append("--no-images")
            if self._config.include_headers_footers:
                cmd.append("--include-headers-footers")

            logger.info(f"Running Chandra CLI: {' '.join(cmd)}")
            logger.info("Note: First run may take 10-15 minutes to download model (~7GB)")

            # Run Chandra OCR with extended timeout (30 minutes for first run)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=1800,  # 30 minute timeout for model download
            )

            if result.returncode != 0:
                error_msg = result.stderr or result.stdout or "Unknown error"
                logger.error(f"Chandra CLI failed: {error_msg}")
                return OCRResult(
                    success=False,
                    error=f"Chandra OCR failed: {error_msg}",
                    model="chandra",
                )

            # Check for CUDA error in output
            output_text = result.stdout + result.stderr
            if "Torch not compiled with CUDA enabled" in output_text:
                logger.error("Chandra OCR requires NVIDIA GPU with CUDA support")
                return OCRResult(
                    success=False,
                    error="Chandra OCR requires NVIDIA GPU with CUDA. Use Mistral, Marker, or Surya OCR instead on Mac/CPU.",
                    model="chandra",
                )

            # Parse output files
            return self._parse_output_directory(output_dir, pdf_path.stem)

    def _parse_output_directory(self, output_dir: Path, doc_name: str) -> OCRResult:
        """Parse Chandra output directory for results."""
        pages = []

        # Look for markdown files in output directory
        md_files = sorted(output_dir.glob("*.md"))

        if not md_files:
            # Try looking in subdirectory named after document
            md_files = sorted(output_dir.glob(f"{doc_name}/*.md"))

        if not md_files:
            # Look for any markdown content recursively
            md_files = sorted(output_dir.rglob("*.md"))

        # If still no files, try reading combined output
        combined_md = output_dir / f"{doc_name}.md"
        if not combined_md.exists():
            # Try without extension matching
            for f in output_dir.iterdir():
                if f.suffix == ".md":
                    combined_md = f
                    break

        if combined_md.exists():
            content = combined_md.read_text()
            # Split by page markers if present
            page_contents = content.split("---PAGE BREAK---")
            if len(page_contents) == 1:
                page_contents = content.split("\n---\n")
            if len(page_contents) == 1:
                # Single page or no markers - treat as one page
                page_contents = [content]

            for idx, page_content in enumerate(page_contents):
                if page_content.strip():
                    pages.append(OCRPage(
                        index=idx,
                        markdown=page_content.strip(),
                    ))
        elif md_files:
            for idx, md_file in enumerate(md_files):
                content = md_file.read_text()
                pages.append(OCRPage(
                    index=idx,
                    markdown=content,
                ))

        # Try JSON output for metadata
        json_files = list(output_dir.rglob("*.json"))
        if json_files:
            try:
                with open(json_files[0]) as f:
                    metadata = json.load(f)
                logger.debug(f"Found metadata: {json_files[0]}")
            except Exception as e:
                logger.debug(f"Could not parse JSON metadata: {e}")

        if not pages:
            # List directory contents for debugging
            all_files = list(output_dir.rglob("*"))
            logger.error(f"No output files found. Directory contents: {all_files}")
            return OCRResult(
                success=False,
                error="No output files found from Chandra OCR. Check if model is downloaded.",
                model="chandra",
            )

        return OCRResult(
            success=True,
            pages=pages,
            model="chandra",
            total_pages=len(pages),
        )

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get Chandra provider information."""
        # Check if chandra CLI is available
        is_available = True
        error = None

        python_dir = Path(sys.executable).parent
        chandra_cli = python_dir / "chandra"

        if not chandra_cli.exists():
            # Check PATH
            import shutil
            if not shutil.which("chandra"):
                is_available = False
                error = "chandra package not installed"

        return ProviderInfo(
            name="chandra",
            display_name="Chandra OCR",
            description="Local OCR using Chandra model. FREE, requires NVIDIA GPU with CUDA.",
            provider_type=ProviderType.LOCAL,
            cost_tier=CostTier.FREE,
            requires_api_key=False,
            is_available=is_available,
            error=error,
            capabilities=[
                "pdf",
                "text_extraction",
                "tables",
                "complex_layouts",
            ],
            config_options={
                "method": {
                    "type": "string",
                    "default": "hf",
                    "description": "OCR method (hf or vllm)",
                },
            },
        )


def _get_config():
    """Factory function to create config."""
    return ChandraConfig()


# Register with the provider registry
ProviderRegistry.register_ocr_provider(
    "chandra",
    ChandraOCRAdapter,
    _get_config,
)
