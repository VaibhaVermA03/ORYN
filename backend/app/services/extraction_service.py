"""Content validation and text extraction for PDF, TXT and DOCX.

File type is decided from the file's actual bytes, never from the browser-supplied MIME type.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

import pymupdf  # PyMuPDF
from docx import Document as DocxDocument

from app.core.config import get_settings
from app.core.exceptions import AppError, UnsupportedMedia

ALLOWED_EXTENSIONS = {"pdf", "txt", "docx"}


class ExtractionError(AppError):
    """The file is corrupted, encrypted, empty or otherwise unreadable. Never retryable."""

    status_code = 422
    code = "extraction_failed"


@dataclass(frozen=True)
class Page:
    number: int | None  # 1-based page number; None for formats without pages (TXT, DOCX)
    text: str


def clean_text(text: str) -> str:
    # PostgreSQL text columns cannot contain NUL; normalize line endings and spacing noise.
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()


def sniff_file_type(path: Path, claimed_ext: str) -> str:
    """Validate magic bytes against the claimed extension and return the canonical type."""
    ext = claimed_ext.lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedMedia("Unsupported file type. Upload a PDF, TXT or DOCX file.", code="unsupported_type")
    with path.open("rb") as f:
        head = f.read(8192)
    if not head:
        raise ExtractionError("The file is empty.", code="empty_file")
    if ext == "pdf":
        if b"%PDF-" not in head[:1024]:
            raise UnsupportedMedia("The file is not a valid PDF.", code="content_mismatch")
    elif ext == "docx":
        if not head.startswith(b"PK"):
            raise UnsupportedMedia("The file is not a valid DOCX document.", code="content_mismatch")
        try:
            with zipfile.ZipFile(path) as z:
                names = set(z.namelist())
                total = sum(i.file_size for i in z.infolist())
        except zipfile.BadZipFile as exc:
            raise UnsupportedMedia("The file is not a valid DOCX document.", code="content_mismatch") from exc
        if "[Content_Types].xml" not in names or "word/document.xml" not in names:
            raise UnsupportedMedia("The file is not a valid DOCX document.", code="content_mismatch")
        if total > get_settings().max_docx_uncompressed_bytes:
            raise ExtractionError("The DOCX file expands to an unsafe size.", code="unsafe_archive")
    else:  # txt
        if b"\x00" in head and not head.startswith((b"\xff\xfe", b"\xfe\xff")):
            raise UnsupportedMedia("The file does not look like plain text.", code="content_mismatch")
    return ext


def _decode_text(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _extract_txt(path: Path) -> list[Page]:
    return [Page(None, clean_text(_decode_text(path.read_bytes())))]


def _extract_docx(path: Path) -> list[Page]:
    try:
        doc = DocxDocument(str(path))
    except Exception as exc:  # noqa: BLE001 - python-docx raises assorted errors on corrupt files
        raise ExtractionError("The DOCX file could not be read. It may be corrupted.", code="corrupt_file") from exc
    parts: list[str] = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return [Page(None, clean_text("\n\n".join(parts)))]


def _extract_pdf(path: Path) -> list[Page]:
    s = get_settings()
    try:
        pdf = pymupdf.open(str(path))
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError("The PDF could not be opened. It may be corrupted.", code="corrupt_file") from exc
    try:
        if pdf.needs_pass or pdf.is_encrypted:
            raise ExtractionError("The PDF is password-protected.", code="encrypted_file")
        if pdf.page_count > s.max_pdf_pages:
            raise ExtractionError(f"The PDF has more than {s.max_pdf_pages} pages.", code="too_many_pages")
        pages: list[Page] = []
        for index in range(pdf.page_count):
            try:
                text = clean_text(pdf[index].get_text("text"))
            except Exception as exc:  # noqa: BLE001
                raise ExtractionError(f"Page {index + 1} could not be read.", code="corrupt_file") from exc
            pages.append(Page(index + 1, text))
        return pages
    finally:
        pdf.close()


def extract_pages(path: Path, file_type: str) -> list[Page]:
    """Return non-empty pages. Raises ExtractionError when no text can be extracted."""
    if file_type == "pdf":
        pages = _extract_pdf(path)
    elif file_type == "docx":
        pages = _extract_docx(path)
    elif file_type == "txt":
        pages = _extract_txt(path)
    else:
        raise UnsupportedMedia("Unsupported file type.", code="unsupported_type")
    pages = [p for p in pages if p.text]
    if not pages:
        hint = " Scanned PDFs need OCR, which is not supported." if file_type == "pdf" else ""
        raise ExtractionError(f"No extractable text was found in the file.{hint}", code="no_text")
    return pages


def page_count(pages: list[Page]) -> int | None:
    numbers = [p.number for p in pages if p.number is not None]
    return max(numbers) if numbers else None
