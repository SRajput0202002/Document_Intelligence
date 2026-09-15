"""
Document Converter - Multi-Format to PDF Conversion.

Converts various document formats to PDF for consistent viewing
and OCR processing in the IDP platform.

Supported formats:
- Images: JPG, JPEG, PNG, TIFF, TIF, BMP, WEBP, HEIC, HEIF, GIF
- Documents: DOCX, XLSX, DOC, XLS, TXT, RTF, CSV
- PDF: Passed through as-is

The converter creates a PDF that can be:
1. Rendered in the PDF viewer
2. Processed by OCR providers
3. Used for text position indexing
"""

import io
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, List, Union
import shutil

logger = logging.getLogger(__name__)

# Supported format definitions
SUPPORTED_IMAGE_FORMATS = {
    ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp",
    ".webp", ".heic", ".heif", ".gif"
}

SUPPORTED_DOCUMENT_FORMATS = {
    ".docx", ".xlsx", ".doc", ".xls", ".txt", ".rtf", ".csv"
}

SUPPORTED_PDF_FORMATS = {".pdf"}

SUPPORTED_FORMATS = SUPPORTED_IMAGE_FORMATS | SUPPORTED_DOCUMENT_FORMATS | SUPPORTED_PDF_FORMATS

# MIME type mappings
MIME_TO_EXTENSION = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/tiff": ".tiff",
    "image/bmp": ".bmp",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heif",
    "image/gif": ".gif",
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/msword": ".doc",
    "application/vnd.ms-excel": ".xls",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "application/rtf": ".rtf",
}


def is_supported_format(filename: str) -> bool:
    """Check if a filename has a supported extension."""
    ext = Path(filename).suffix.lower()
    return ext in SUPPORTED_FORMATS


def get_format_category(filename: str) -> Optional[str]:
    """Get the category of a file format."""
    ext = Path(filename).suffix.lower()
    if ext in SUPPORTED_IMAGE_FORMATS:
        return "image"
    elif ext in SUPPORTED_DOCUMENT_FORMATS:
        return "document"
    elif ext in SUPPORTED_PDF_FORMATS:
        return "pdf"
    return None


def validate_processable_pdf(pdf_path: Union[str, Path]) -> None:
    """
    Validate that a PDF can be processed without a password and is structurally readable.

    Uses PyMuPDF to reject password-protected PDFs and obviously corrupt/unreadable files
    before OCR or extraction runs.

    Raises:
        ValueError: User-facing message suitable for API ``detail`` responses.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise ValueError("PDF file not found.")

    import fitz

    doc = None
    try:
        try:
            doc = fitz.open(str(pdf_path))
        except Exception as e:
            err = str(e).lower()
            if (
                "password" in err
                or "incorrect password" in err
                or ("encrypt" in err and "cannot" in err)
                or "encryption" in err
            ):
                raise ValueError(
                    "This PDF is password-protected. Remove the password or use an unencrypted copy."
                ) from e
            raise ValueError(
                "This PDF is damaged, invalid, or could not be opened. Try re-exporting or repairing the file."
            ) from e

        if getattr(doc, "needs_pass", False):
            raise ValueError(
                "This PDF is password-protected. Remove the password or use an unencrypted copy."
            )

        n = int(doc.page_count) if hasattr(doc, "page_count") else len(doc)
        size = pdf_path.stat().st_size
        if n == 0 and size > 0:
            raise ValueError(
                "This PDF has no readable pages or appears corrupted."
            )

        if n > 0:
            try:
                doc.load_page(0)
            except Exception as e:
                raise ValueError(
                    "This PDF is damaged or could not be read. Try re-exporting or repairing the file."
                ) from e
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass


@dataclass
class ConversionResult:
    """Result of document conversion."""
    success: bool
    pdf_path: Optional[Path] = None
    original_path: Optional[Path] = None
    original_format: Optional[str] = None
    page_count: int = 0
    error: Optional[str] = None
    was_converted: bool = False  # True if conversion was performed


class DocumentConverter:
    """
    Converts various document formats to PDF.

    This enables consistent handling of all document types in the IDP pipeline,
    as all OCR and viewing operations work on PDFs.
    """

    def __init__(self, temp_dir: Optional[Path] = None):
        """
        Initialize the document converter.

        Args:
            temp_dir: Directory for temporary files. If None, uses system temp.
        """
        self.temp_dir = temp_dir or Path(tempfile.gettempdir())
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def convert(
        self,
        input_path: Union[str, Path],
        output_path: Optional[Union[str, Path]] = None,
    ) -> ConversionResult:
        """
        Convert a document to PDF.

        Args:
            input_path: Path to the input document
            output_path: Optional output path. If None, creates in temp_dir.

        Returns:
            ConversionResult with success status and output path
        """
        input_path = Path(input_path)

        if not input_path.exists():
            return ConversionResult(
                success=False,
                error=f"Input file not found: {input_path}"
            )

        ext = input_path.suffix.lower()

        if ext not in SUPPORTED_FORMATS:
            return ConversionResult(
                success=False,
                original_path=input_path,
                original_format=ext,
                error=f"Unsupported format: {ext}. Supported: {', '.join(sorted(SUPPORTED_FORMATS))}"
            )

        # PDF files don't need conversion
        if ext == ".pdf":
            try:
                validate_processable_pdf(input_path)
            except ValueError as e:
                return ConversionResult(
                    success=False,
                    original_path=input_path,
                    original_format=ext,
                    error=str(e),
                )
            return ConversionResult(
                success=True,
                pdf_path=input_path,
                original_path=input_path,
                original_format=ext,
                page_count=self._count_pdf_pages(input_path),
                was_converted=False
            )

        # Determine output path
        if output_path is None:
            output_path = self.temp_dir / f"{input_path.stem}_converted.pdf"
        else:
            output_path = Path(output_path)

        # Route to appropriate converter
        try:
            if ext in SUPPORTED_IMAGE_FORMATS:
                return self._convert_image(input_path, output_path)
            elif ext in {".docx", ".doc"}:
                return self._convert_word(input_path, output_path)
            elif ext in {".xlsx", ".xls", ".csv"}:
                return self._convert_spreadsheet(input_path, output_path)
            elif ext in {".txt", ".rtf"}:
                return self._convert_text(input_path, output_path)
            else:
                return ConversionResult(
                    success=False,
                    original_path=input_path,
                    original_format=ext,
                    error=f"No converter available for format: {ext}"
                )
        except Exception as e:
            logger.error(f"Conversion failed for {input_path}: {e}")
            return ConversionResult(
                success=False,
                original_path=input_path,
                original_format=ext,
                error=str(e)
            )

    def convert_bytes(
        self,
        data: bytes,
        filename: str,
        output_path: Optional[Union[str, Path]] = None,
    ) -> ConversionResult:
        """
        Convert document bytes to PDF.

        Args:
            data: File bytes
            filename: Original filename (for extension detection)
            output_path: Optional output path

        Returns:
            ConversionResult with success status and output path
        """
        ext = Path(filename).suffix.lower()

        if ext not in SUPPORTED_FORMATS:
            return ConversionResult(
                success=False,
                original_format=ext,
                error=f"Unsupported format: {ext}"
            )

        # Save bytes to temp file
        temp_input = self.temp_dir / f"input_{Path(filename).stem}{ext}"
        try:
            with open(temp_input, "wb") as f:
                f.write(data)

            result = self.convert(temp_input, output_path)
            result.original_path = None  # Don't expose temp path
            return result
        finally:
            # Clean up temp input if it was converted (output is different file)
            if temp_input.exists() and result.was_converted:
                try:
                    temp_input.unlink()
                except Exception:
                    pass

    def _convert_image(self, input_path: Path, output_path: Path) -> ConversionResult:
        """Convert image file(s) to PDF using Pillow's native PDF support."""
        from PIL import Image

        ext = input_path.suffix.lower()

        # Handle HEIC/HEIF separately
        if ext in {".heic", ".heif"}:
            return self._convert_heic(input_path, output_path)

        # Handle multi-page TIFF
        if ext in {".tiff", ".tif"}:
            return self._convert_tiff(input_path, output_path)

        # Standard image conversion using Pillow's direct PDF save
        # This creates PDFs that are more compatible with OCR services
        try:
            with Image.open(input_path) as img:
                # Convert to RGB if necessary (for RGBA, P mode, etc.)
                if img.mode in ("RGBA", "LA", "P"):
                    # Create white background for transparency
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    if img.mode == "P":
                        img = img.convert("RGBA")
                    if img.mode in ("RGBA", "LA"):
                        background.paste(img, mask=img.split()[-1])
                    else:
                        background.paste(img)
                    img = background
                elif img.mode != "RGB":
                    img = img.convert("RGB")

                # Use Pillow's native PDF save - creates standard PDF/A compatible output
                # Resolution is set to maintain quality while being processable
                img.save(
                    str(output_path),
                    "PDF",
                    resolution=150.0,  # 150 DPI for good quality
                )

                return ConversionResult(
                    success=True,
                    pdf_path=output_path,
                    original_path=input_path,
                    original_format=ext,
                    page_count=1,
                    was_converted=True
                )

        except Exception as e:
            logger.error(f"Image conversion failed: {e}")
            return ConversionResult(
                success=False,
                original_path=input_path,
                original_format=ext,
                error=f"Image conversion failed: {e}"
            )

    def _convert_heic(self, input_path: Path, output_path: Path) -> ConversionResult:
        """Convert HEIC/HEIF image to PDF using Pillow's native PDF support."""
        try:
            # Try pillow-heif first
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except ImportError:
                return ConversionResult(
                    success=False,
                    original_path=input_path,
                    original_format=input_path.suffix.lower(),
                    error="HEIC support requires pillow-heif package. Install with: pip install pillow-heif"
                )

            from PIL import Image

            with Image.open(input_path) as img:
                # Convert to RGB
                if img.mode != "RGB":
                    img = img.convert("RGB")

                # Use Pillow's native PDF save for better OCR compatibility
                img.save(
                    str(output_path),
                    "PDF",
                    resolution=150.0,
                )

                return ConversionResult(
                    success=True,
                    pdf_path=output_path,
                    original_path=input_path,
                    original_format=input_path.suffix.lower(),
                    page_count=1,
                    was_converted=True
                )

        except Exception as e:
            logger.error(f"HEIC conversion failed: {e}")
            return ConversionResult(
                success=False,
                original_path=input_path,
                original_format=input_path.suffix.lower(),
                error=f"HEIC conversion failed: {e}"
            )

    def _convert_tiff(self, input_path: Path, output_path: Path) -> ConversionResult:
        """Convert TIFF (including multi-page) to PDF using Pillow's native PDF support."""
        from PIL import Image

        try:
            frames = []
            page_count = 0

            with Image.open(input_path) as img:
                # Iterate through all frames (pages) in TIFF
                frame_idx = 0
                while True:
                    try:
                        img.seek(frame_idx)

                        # Convert frame to RGB
                        frame = img.copy()
                        if frame.mode in ("RGBA", "LA", "P"):
                            background = Image.new("RGB", frame.size, (255, 255, 255))
                            if frame.mode == "P":
                                frame = frame.convert("RGBA")
                            if frame.mode in ("RGBA", "LA"):
                                background.paste(frame, mask=frame.split()[-1])
                            else:
                                background.paste(frame)
                            frame = background
                        elif frame.mode != "RGB":
                            frame = frame.convert("RGB")

                        frames.append(frame)
                        page_count += 1
                        frame_idx += 1

                    except EOFError:
                        break

            if not frames:
                return ConversionResult(
                    success=False,
                    original_path=input_path,
                    original_format=".tiff",
                    error="No frames found in TIFF file"
                )

            # Save all frames to PDF using Pillow's native PDF support
            first_frame = frames[0]
            if len(frames) > 1:
                first_frame.save(
                    str(output_path),
                    "PDF",
                    resolution=150.0,
                    save_all=True,
                    append_images=frames[1:],
                )
            else:
                first_frame.save(
                    str(output_path),
                    "PDF",
                    resolution=150.0,
                )

            return ConversionResult(
                success=True,
                pdf_path=output_path,
                original_path=input_path,
                original_format=".tiff",
                page_count=page_count,
                was_converted=True
            )

        except Exception as e:
            logger.error(f"TIFF conversion failed: {e}")
            return ConversionResult(
                success=False,
                original_path=input_path,
                original_format=".tiff",
                error=f"TIFF conversion failed: {e}"
            )

    def _convert_word(self, input_path: Path, output_path: Path) -> ConversionResult:
        """Convert Word document to PDF."""
        ext = input_path.suffix.lower()

        try:
            # Try using python-docx + reportlab for DOCX
            if ext == ".docx":
                return self._convert_docx_native(input_path, output_path)
            else:
                # For .doc files, we need LibreOffice or similar
                return self._convert_with_libreoffice(input_path, output_path)

        except Exception as e:
            logger.error(f"Word conversion failed: {e}")
            return ConversionResult(
                success=False,
                original_path=input_path,
                original_format=ext,
                error=f"Word conversion failed: {e}"
            )

    def _convert_docx_native(self, input_path: Path, output_path: Path) -> ConversionResult:
        """Convert DOCX using python-docx and reportlab."""
        try:
            from docx import Document
            from reportlab.lib.pagesizes import letter, landscape
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
            from reportlab.lib import colors
            from reportlab.lib.units import inch
        except ImportError as e:
            logger.error(f"python-docx or reportlab not installed: {e}")
            return ConversionResult(
                success=False,
                original_path=input_path,
                original_format=".docx",
                error=f"Missing dependencies for DOCX conversion: {e}. Install python-docx and reportlab."
            )

        try:
            doc = Document(input_path)

            # Check if document has tables to decide orientation
            has_wide_tables = any(len(table.columns) > 3 for table in doc.tables)
            page_size = landscape(letter) if has_wide_tables else letter

            # Create PDF with appropriate orientation
            pdf_doc = SimpleDocTemplate(
                str(output_path),
                pagesize=page_size,
                rightMargin=36,
                leftMargin=36,
                topMargin=36,
                bottomMargin=36
            )

            # Calculate available width
            available_width = page_size[0] - 72  # page width minus margins

            styles = getSampleStyleSheet()
            story = []

            # Create a style for table cells with word wrap
            cell_style = ParagraphStyle(
                'CellStyle',
                parent=styles['Normal'],
                fontSize=8,
                leading=10,
                wordWrap='LTR',
            )

            # Helper to escape XML special characters for reportlab
            def escape_text(text: str) -> str:
                """Escape XML special characters for reportlab Paragraph."""
                if not text:
                    return ""
                return (text
                    .replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                )

            for para in doc.paragraphs:
                if para.text.strip():
                    # Determine style based on paragraph style
                    style_name = para.style.name if para.style else "Normal"

                    if "Heading 1" in style_name:
                        style = styles["Heading1"]
                    elif "Heading 2" in style_name:
                        style = styles["Heading2"]
                    elif "Heading" in style_name:
                        style = styles["Heading3"]
                    else:
                        style = styles["Normal"]

                    try:
                        escaped_text = escape_text(para.text)
                        story.append(Paragraph(escaped_text, style))
                        story.append(Spacer(1, 6))
                    except Exception as e:
                        # Skip problematic paragraphs but continue
                        logger.warning(f"Skipping paragraph due to error: {e}")

            # Handle tables
            for table in doc.tables:
                data = []
                num_cols = len(table.columns) if table.columns else 0

                for row in table.rows:
                    row_data = []
                    for cell in row.cells:
                        # Use Paragraph for word wrapping
                        cell_text = escape_text(cell.text)
                        row_data.append(Paragraph(cell_text, cell_style))
                    data.append(row_data)

                if data and num_cols > 0:
                    try:
                        # Calculate column widths to fit page
                        col_width = available_width / num_cols
                        col_widths = [col_width] * num_cols

                        t = Table(data, colWidths=col_widths)
                        t.setStyle(TableStyle([
                            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                            ('PADDING', (0, 0), (-1, -1), 4),
                            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                            ('FONTSIZE', (0, 0), (-1, -1), 8),
                        ]))
                        story.append(t)
                        story.append(Spacer(1, 12))
                    except Exception as e:
                        logger.warning(f"Skipping table due to error: {e}")

            if story:
                pdf_doc.build(story)
            else:
                # Empty document - create single blank page
                from reportlab.pdfgen import canvas
                c = canvas.Canvas(str(output_path), pagesize=letter)
                c.drawString(72, 750, "(Empty document)")
                c.save()

            return ConversionResult(
                success=True,
                pdf_path=output_path,
                original_path=input_path,
                original_format=".docx",
                page_count=self._count_pdf_pages(output_path),
                was_converted=True
            )

        except Exception as e:
            logger.error(f"DOCX native conversion failed: {e}", exc_info=True)
            # Return error instead of falling back to LibreOffice
            # Native conversion should work for most DOCX files
            return ConversionResult(
                success=False,
                original_path=input_path,
                original_format=".docx",
                error=f"DOCX conversion failed: {str(e)}"
            )

    def _convert_spreadsheet(self, input_path: Path, output_path: Path) -> ConversionResult:
        """Convert spreadsheet (XLSX, XLS, CSV) to PDF."""
        ext = input_path.suffix.lower()

        try:
            if ext == ".csv":
                return self._convert_csv(input_path, output_path)
            elif ext == ".xlsx":
                result = self._convert_xlsx_native(input_path, output_path)
                if result.success:
                    return result
                logger.info(
                    "XLSX native conversion failed (%s), trying LibreOffice fallback",
                    result.error or "unknown",
                )
                return self._convert_with_libreoffice(input_path, output_path)
            else:
                return self._convert_with_libreoffice(input_path, output_path)

        except Exception as e:
            logger.error(f"Spreadsheet conversion failed: {e}")
            return ConversionResult(
                success=False,
                original_path=input_path,
                original_format=ext,
                error=f"Spreadsheet conversion failed: {e}"
            )

    def _convert_xlsx_native(self, input_path: Path, output_path: Path) -> ConversionResult:
        """Convert XLSX using openpyxl and reportlab."""
        try:
            from openpyxl import load_workbook
            from reportlab.lib.pagesizes import letter, landscape
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, PageBreak, Spacer
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib import colors
        except ImportError as e:
            logger.error(f"openpyxl or reportlab not installed: {e}")
            return ConversionResult(
                success=False,
                original_path=input_path,
                original_format=".xlsx",
                error=f"Missing dependencies for XLSX conversion: {e}. Install openpyxl and reportlab."
            )

        try:
            wb = load_workbook(input_path, data_only=True)

            # Use landscape for spreadsheets
            page_size = landscape(letter)
            available_width = page_size[0] - 72  # page width minus margins

            pdf_doc = SimpleDocTemplate(
                str(output_path),
                pagesize=page_size,
                rightMargin=36,
                leftMargin=36,
                topMargin=36,
                bottomMargin=36
            )

            styles = getSampleStyleSheet()
            story = []

            # Create a style for table cells with word wrap
            cell_style = ParagraphStyle(
                'CellStyle',
                parent=styles['Normal'],
                fontSize=7,
                leading=9,
                wordWrap='LTR',
            )

            # Helper to escape XML special characters
            def escape_text(text: str) -> str:
                if not text:
                    return ""
                return (text
                    .replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                )

            for sheet_name in wb.sheetnames:
                sheet = wb[sheet_name]

                # Add sheet name as header
                safe_sheet_name = escape_text(sheet_name)
                story.append(Paragraph(f"<b>{safe_sheet_name}</b>", styles["Heading2"]))
                story.append(Spacer(1, 6))

                # Extract data and determine column count
                data = []
                max_cols = 0
                for row in sheet.iter_rows(values_only=True):
                    row_data = []
                    for cell in row:
                        cell_text = escape_text(str(cell)) if cell is not None else ""
                        # Use Paragraph for word wrapping in cells
                        row_data.append(Paragraph(cell_text, cell_style))
                    if any(str(cell) if cell else "" for cell in row):  # Skip completely empty rows
                        data.append(row_data)
                        max_cols = max(max_cols, len(row_data))

                if data and max_cols > 0:
                    # Calculate column widths to fit page
                    col_width = available_width / max_cols
                    col_widths = [col_width] * max_cols

                    # Pad rows that have fewer columns
                    for row_data in data:
                        while len(row_data) < max_cols:
                            row_data.append(Paragraph("", cell_style))

                    # Create table with calculated widths
                    t = Table(data, colWidths=col_widths)
                    t.setStyle(TableStyle([
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                        ('FONTSIZE', (0, 0), (-1, -1), 7),
                        ('PADDING', (0, 0), (-1, -1), 3),
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ]))
                    story.append(t)

                story.append(PageBreak())

            if story:
                # Remove last page break
                if story and isinstance(story[-1], PageBreak):
                    story.pop()
                pdf_doc.build(story)
            else:
                # Empty workbook
                from reportlab.pdfgen import canvas
                c = canvas.Canvas(str(output_path), pagesize=letter)
                c.drawString(72, 750, "(Empty spreadsheet)")
                c.save()

            return ConversionResult(
                success=True,
                pdf_path=output_path,
                original_path=input_path,
                original_format=".xlsx",
                page_count=self._count_pdf_pages(output_path),
                was_converted=True
            )

        except Exception as e:
            logger.error(f"XLSX native conversion failed: {e}", exc_info=True)
            return ConversionResult(
                success=False,
                original_path=input_path,
                original_format=".xlsx",
                error=f"XLSX conversion failed: {str(e)}"
            )

    def _convert_csv(self, input_path: Path, output_path: Path) -> ConversionResult:
        """Convert CSV to PDF."""
        try:
            import csv
            from reportlab.lib.pagesizes import letter, landscape
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
            from reportlab.lib import colors
        except ImportError as e:
            return ConversionResult(
                success=False,
                original_path=input_path,
                original_format=".csv",
                error=f"reportlab required for CSV conversion: {e}"
            )

        try:
            # Read CSV
            with open(input_path, 'r', encoding='utf-8', errors='replace') as f:
                reader = csv.reader(f)
                data = list(reader)

            if not data:
                # Empty CSV
                from reportlab.pdfgen import canvas
                c = canvas.Canvas(str(output_path), pagesize=letter)
                c.drawString(72, 750, "(Empty CSV file)")
                c.save()
            else:
                pdf_doc = SimpleDocTemplate(
                    str(output_path),
                    pagesize=landscape(letter),
                    rightMargin=36,
                    leftMargin=36,
                    topMargin=36,
                    bottomMargin=36
                )

                t = Table(data)
                t.setStyle(TableStyle([
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                    ('FONTSIZE', (0, 0), (-1, -1), 8),
                    ('PADDING', (0, 0), (-1, -1), 4),
                ]))

                pdf_doc.build([t])

            return ConversionResult(
                success=True,
                pdf_path=output_path,
                original_path=input_path,
                original_format=".csv",
                page_count=self._count_pdf_pages(output_path),
                was_converted=True
            )

        except Exception as e:
            logger.error(f"CSV conversion failed: {e}")
            return ConversionResult(
                success=False,
                original_path=input_path,
                original_format=".csv",
                error=f"CSV conversion failed: {e}"
            )

    def _convert_text(self, input_path: Path, output_path: Path) -> ConversionResult:
        """Convert plain text or RTF to PDF."""
        ext = input_path.suffix.lower()

        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
        except ImportError as e:
            return ConversionResult(
                success=False,
                original_path=input_path,
                original_format=ext,
                error=f"reportlab required for text conversion: {e}"
            )

        try:
            # Read text content
            with open(input_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()

            # Create PDF
            pdf_doc = SimpleDocTemplate(
                str(output_path),
                pagesize=letter,
                rightMargin=72,
                leftMargin=72,
                topMargin=72,
                bottomMargin=72
            )

            styles = getSampleStyleSheet()
            # Create a style with monospace font for text files
            mono_style = ParagraphStyle(
                'Mono',
                parent=styles['Normal'],
                fontName='Courier',
                fontSize=10,
                leading=12,
            )

            story = []

            # Split by lines and create paragraphs
            for line in content.split('\n'):
                if line.strip():
                    # Escape special characters for reportlab
                    safe_line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    story.append(Paragraph(safe_line, mono_style))
                else:
                    story.append(Spacer(1, 12))

            if story:
                pdf_doc.build(story)
            else:
                from reportlab.pdfgen import canvas
                c = canvas.Canvas(str(output_path), pagesize=letter)
                c.drawString(72, 750, "(Empty text file)")
                c.save()

            return ConversionResult(
                success=True,
                pdf_path=output_path,
                original_path=input_path,
                original_format=ext,
                page_count=self._count_pdf_pages(output_path),
                was_converted=True
            )

        except Exception as e:
            logger.error(f"Text conversion failed: {e}")
            return ConversionResult(
                success=False,
                original_path=input_path,
                original_format=ext,
                error=f"Text conversion failed: {e}"
            )

    def _convert_with_libreoffice(self, input_path: Path, output_path: Path) -> ConversionResult:
        """
        Convert document using LibreOffice (fallback for complex formats).

        Requires LibreOffice to be installed on the system.
        """
        import subprocess

        ext = input_path.suffix.lower()

        try:
            # Check if LibreOffice is available
            result = subprocess.run(
                ["which", "soffice"],
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                # Try common paths
                libreoffice_paths = [
                    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
                    "/usr/bin/soffice",
                    "/usr/local/bin/soffice",
                ]
                soffice_path = None
                for path in libreoffice_paths:
                    if Path(path).exists():
                        soffice_path = path
                        break

                if not soffice_path:
                    return ConversionResult(
                        success=False,
                        original_path=input_path,
                        original_format=ext,
                        error="LibreOffice not found. Install LibreOffice for DOC/XLS conversion."
                    )
            else:
                soffice_path = "soffice"

            # Convert using LibreOffice
            output_dir = output_path.parent
            result = subprocess.run(
                [
                    soffice_path,
                    "--headless",
                    "--convert-to", "pdf",
                    "--outdir", str(output_dir),
                    str(input_path)
                ],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                return ConversionResult(
                    success=False,
                    original_path=input_path,
                    original_format=ext,
                    error=f"LibreOffice conversion failed: {result.stderr}"
                )

            # LibreOffice creates file with same name but .pdf extension
            converted_path = output_dir / f"{input_path.stem}.pdf"

            if not converted_path.exists():
                return ConversionResult(
                    success=False,
                    original_path=input_path,
                    original_format=ext,
                    error="LibreOffice conversion produced no output"
                )

            # Rename to expected output path if different
            if converted_path != output_path:
                shutil.move(str(converted_path), str(output_path))

            return ConversionResult(
                success=True,
                pdf_path=output_path,
                original_path=input_path,
                original_format=ext,
                page_count=self._count_pdf_pages(output_path),
                was_converted=True
            )

        except subprocess.TimeoutExpired:
            return ConversionResult(
                success=False,
                original_path=input_path,
                original_format=ext,
                error="LibreOffice conversion timed out"
            )
        except Exception as e:
            logger.error(f"LibreOffice conversion failed: {e}")
            return ConversionResult(
                success=False,
                original_path=input_path,
                original_format=ext,
                error=f"LibreOffice conversion failed: {e}"
            )

    def _count_pdf_pages(self, pdf_path: Path) -> int:
        """Count pages in a PDF file."""
        try:
            import fitz
            doc = fitz.open(str(pdf_path))
            count = len(doc)
            doc.close()
            return count
        except Exception:
            return 0
