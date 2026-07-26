"""
core/text_extraction/extractor.py
PDFTextExtractor — core extraction engine sử dụng PyMuPDF (fitz).
Trích xuất cấu trúc phân cấp: Document → Page → Block → Line → Span.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import fitz  # PyMuPDF

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
from core.text_extraction.utils import is_born_digital, safe_color_to_hex

logger = logging.getLogger(__name__)


class PDFTextExtractor:
    """
    Trích xuất cấu trúc text từ PDF sử dụng PyMuPDF.

    Output là DocumentData chứa full hierarchy với font metadata,
    bounding box, và page dimensions.

    Có thể sử dụng standalone (không cần ExtractorPipeline).
    """

    def extract(self, file_path: str) -> DocumentData:
        """
        Trích xuất toàn bộ cấu trúc text từ một file PDF.

        Args:
            file_path: Đường dẫn đến file PDF.

        Returns:
            DocumentData chứa tất cả pages, blocks, lines, spans.

        Raises:
            PDFCorruptedError: File bị lỗi cấu trúc.
            PDFEncryptedError: File yêu cầu password.
            PDFEmptyError: File không có trang nào.
            PDFExtractionError: Lỗi không xác định khác.
        """
        start_time = time.time()

        # Validate file exists
        path = Path(file_path)
        if not path.exists():
            raise PDFExtractionError(
                f"File not found: {file_path}", file_path=file_path
            )

        # Open PDF with PyMuPDF
        try:
            doc = fitz.open(str(file_path))
        except Exception as e:
            raise PDFCorruptedError(
                file_path=file_path, detail=str(e)
            ) from e

        try:
            # Check encrypted
            if doc.is_encrypted:
                raise PDFEncryptedError(file_path=file_path)

            # Check empty
            if doc.page_count == 0:
                raise PDFEmptyError(file_path=file_path)

            # Extract all pages
            pages: list[PageData] = []
            total_blocks = 0
            total_spans = 0

            for page_number in range(doc.page_count):
                page = doc[page_number]
                page_data = self._extract_page(page, page_number)
                pages.append(page_data)

                # Count totals
                for block in page_data.blocks:
                    total_blocks += 1
                    for line in block.lines:
                        total_spans += len(line.spans)

            # Detect born-digital
            born_digital = is_born_digital(pages)

            elapsed = time.time() - start_time

            return DocumentData(
                file_path=str(file_path),
                page_count=doc.page_count,
                pages=pages,
                is_born_digital=born_digital,
                extraction_time_seconds=round(elapsed, 3),
                total_blocks=total_blocks,
                total_spans=total_spans,
            )
        finally:
            doc.close()

    def _extract_page(self, page: fitz.Page, page_number: int) -> PageData:
        """
        Trích xuất một trang PDF thành PageData.

        Args:
            page: fitz.Page object.
            page_number: Số thứ tự trang (0-indexed).

        Returns:
            PageData chứa blocks, dimensions, image count.
        """
        # Get page dimensions
        rect = page.rect
        width = rect.width
        height = rect.height

        # Get text structure via dict mode
        page_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

        # Extract blocks
        blocks = self._extract_blocks(page_dict)

        # Count image blocks
        image_count = sum(
            1 for raw_block in page_dict.get("blocks", [])
            if raw_block.get("type", 0) == 1
        )

        return PageData(
            page_number=page_number,
            width=round(width, 2),
            height=round(height, 2),
            blocks=blocks,
            image_count=image_count,
        )

    def _extract_blocks(self, page_dict: dict) -> list[BlockData]:
        """
        Extract text blocks từ page dict (bỏ qua image blocks).

        Args:
            page_dict: Dict trả về từ page.get_text("dict").

        Returns:
            List các BlockData (chỉ text blocks, type=0).
        """
        blocks: list[BlockData] = []

        for raw_block in page_dict.get("blocks", []):
            block_type = raw_block.get("type", 0)

            # Chỉ xử lý text blocks (type=0)
            if block_type != 0:
                continue

            bbox = raw_block.get("bbox", (0, 0, 0, 0))
            block_number = raw_block.get("number", 0)
            lines = self._extract_lines(raw_block)

            blocks.append(BlockData(
                bbox=tuple(round(v, 2) for v in bbox),
                block_type=block_type,
                block_number=block_number,
                lines=lines,
            ))

        return blocks

    def _extract_lines(self, block_dict: dict) -> list[LineData]:
        """
        Extract lines từ một block dict.

        Args:
            block_dict: Dict của một block từ PyMuPDF.

        Returns:
            List các LineData.
        """
        lines: list[LineData] = []

        for raw_line in block_dict.get("lines", []):
            bbox = raw_line.get("bbox", (0, 0, 0, 0))
            spans = self._extract_spans(raw_line)

            lines.append(LineData(
                bbox=tuple(round(v, 2) for v in bbox),
                spans=spans,
            ))

        return lines

    def _extract_spans(self, line_dict: dict) -> list[SpanData]:
        """
        Extract spans từ một line dict.

        Args:
            line_dict: Dict của một line từ PyMuPDF.

        Returns:
            List các SpanData với font metadata.
        """
        spans: list[SpanData] = []

        for raw_span in line_dict.get("spans", []):
            bbox = raw_span.get("bbox", (0, 0, 0, 0))
            color_int = raw_span.get("color", 0)

            spans.append(SpanData(
                text=raw_span.get("text", ""),
                font_name=raw_span.get("font", ""),
                font_size=round(raw_span.get("size", 0.0), 2),
                font_flags=raw_span.get("flags", 0),
                color=safe_color_to_hex(color_int),
                bbox=tuple(round(v, 2) for v in bbox),
            ))

        return spans
