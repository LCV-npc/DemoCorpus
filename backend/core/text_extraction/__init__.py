# core/text_extraction package
"""
Module text extraction — trích xuất cấu trúc văn bản từ PDF.
Sử dụng PyMuPDF (fitz) để parse PDF hierarchy:
Document → Page → Block → Line → Span.
"""

from core.text_extraction.models import (
    SpanData,
    LineData,
    BlockData,
    PageData,
    DocumentData,
)
from core.text_extraction.exceptions import (
    PDFExtractionError,
    PDFCorruptedError,
    PDFEncryptedError,
    PDFEmptyError,
)
from core.text_extraction.extractor import PDFTextExtractor
from core.text_extraction.service import TextExtractionService

__all__ = [
    # Models
    "SpanData",
    "LineData",
    "BlockData",
    "PageData",
    "DocumentData",
    # Exceptions
    "PDFExtractionError",
    "PDFCorruptedError",
    "PDFEncryptedError",
    "PDFEmptyError",
    # Core classes
    "PDFTextExtractor",
    "TextExtractionService",
]
