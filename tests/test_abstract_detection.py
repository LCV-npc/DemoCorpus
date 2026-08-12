"""
tests/test_abstract_detection.py
Unit tests cho Milestone 6 — Abstract Detection.

Covers:
1. Keyword anchoring (English)
2. Keyword anchoring (Vietnamese)
3. End keyword detection (Keywords)
4. End keyword detection (Introduction)
5. Layout zone fallback
6. Empty document
7. Soft hyphen removal
8. Excessive blank lines normalization
9. Too short validation
10. Too long validation
11. High newline ratio warning
12. Edge cases
"""

import pytest
from unittest.mock import MagicMock
from dataclasses import dataclass, field

from core.abstract_detection.detector import AbstractDetector
from core.abstract_detection.models import (
    AbstractResult,
    ABSTRACT_MAY_BE_LIST,
    ABSTRACT_TOO_SHORT,
    ABSTRACT_TOO_LONG,
    ABSTRACT_STARTS_WITH_KEYWORD,
)
from core.abstract_detection.service import AbstractDetectionService
from core.abstract_detection.exceptions import AbstractDetectionError
from core.text_extraction.models import (
    DocumentData,
    PageData,
    BlockData,
    LineData,
    SpanData,
)
from core.layout_analysis.layout_model import (
    LayoutDocument,
    LayoutPage,
    Region,
    RegionType,
    ColumnInfo,
)
from config.constants import ABSTRACT_MIN_LENGTH, ABSTRACT_MAX_LENGTH


# ─────────────────────────────────────────────
# Test Helpers
# ─────────────────────────────────────────────

def _make_block(text: str, y0: float = 0.0, y1: float = 10.0) -> BlockData:
    """Tạo BlockData đơn giản từ text."""
    return BlockData(
        bbox=(50.0, y0, 500.0, y1),
        block_type=0,
        block_number=0,
        lines=[
            LineData(
                bbox=(50.0, y0, 500.0, y1),
                spans=[
                    SpanData(
                        text=text,
                        font_name="TimesNewRoman",
                        font_size=10.0,
                        font_flags=0,
                    )
                ],
            )
        ],
    )


def _make_doc_data(
    blocks_per_page: list[list[str]],
    file_path: str = "test.pdf",
) -> DocumentData:
    """Tạo DocumentData từ list of list of text strings."""
    pages = []
    for page_num, block_texts in enumerate(blocks_per_page):
        blocks = []
        y = 50.0
        for text in block_texts:
            blocks.append(_make_block(text, y0=y, y1=y + 12.0))
            y += 20.0
        pages.append(PageData(
            page_number=page_num,
            width=595.0,
            height=842.0,
            blocks=blocks,
        ))
    return DocumentData(
        file_path=file_path,
        page_count=len(pages),
        pages=pages,
    )


def _make_layout_doc(
    regions_per_page: list[list[tuple[str, str]]],
    file_path: str = "test.pdf",
) -> LayoutDocument:
    """
    Tạo LayoutDocument từ list of list of (region_type, text).
    region_type: "TITLE", "ABSTRACT", "BODY", "KEYWORD", etc.
    """
    pages = []
    total_regions = 0
    for page_num, region_defs in enumerate(regions_per_page):
        regions = []
        y = 50.0
        for idx, (rtype_str, text) in enumerate(region_defs):
            rtype = RegionType(rtype_str)
            block = _make_block(text, y0=y, y1=y + 12.0)
            regions.append(Region(
                region_type=rtype,
                blocks=[block],
                page_number=page_num,
                reading_order_index=idx,
                confidence=0.85,
            ))
            y += 20.0
            total_regions += 1
        pages.append(LayoutPage(
            page_number=page_num,
            width=595.0,
            height=842.0,
            regions=regions,
            column_info=ColumnInfo(column_count=1),
        ))
    return LayoutDocument(
        file_path=file_path,
        page_count=len(pages),
        pages=pages,
        total_regions=total_regions,
    )


# ─────────────────────────────────────────────
# Test Class
# ─────────────────────────────────────────────

class TestAbstractDetector:
    """Unit tests cho AbstractDetector."""

    def setup_method(self):
        self.detector = AbstractDetector()

    # ── Test 1: Keyword anchoring (English) ──

    def test_keyword_english_abstract(self):
        """Abstract keyword 'Abstract' → extract nội dung đúng."""
        abstract_text = (
            "This paper presents a novel method for extracting metadata "
            "from scientific PDF documents using heuristic-based approaches. "
            "The method achieves state-of-the-art results."
        )
        doc_data = _make_doc_data([
            ["Title of Paper", "Author Names", f"Abstract\n{abstract_text}"],
        ])
        layout_doc = _make_layout_doc([
            [
                ("TITLE", "Title of Paper"),
                ("AUTHOR", "Author Names"),
                ("ABSTRACT", f"Abstract\n{abstract_text}"),
            ]
        ])

        result = self.detector.detect(doc_data, layout_doc)

        assert result.found
        assert result.method == "keyword"
        assert abstract_text.split(".")[0] in result.text
        assert result.confidence >= 0.80
        assert "Abstract" not in result.text.split()[0] if result.text else True

    # ── Test 2: Keyword anchoring (Vietnamese) ──

    def test_keyword_vietnamese_abstract(self):
        """Vietnamese keyword 'TÓM TẮT' → extract đúng nội dung tiếng Việt."""
        abstract_text = (
            "Bài báo này trình bày một phương pháp mới để trích xuất "
            "metadata từ các tài liệu PDF khoa học sử dụng các phương pháp "
            "dựa trên heuristic. Phương pháp đạt kết quả tốt nhất."
        )
        doc_data = _make_doc_data([
            ["Tiêu đề bài báo", "Tên tác giả", f"TÓM TẮT\n{abstract_text}"],
        ])
        layout_doc = _make_layout_doc([
            [
                ("TITLE", "Tiêu đề bài báo"),
                ("AUTHOR", "Tên tác giả"),
                ("ABSTRACT", f"TÓM TẮT\n{abstract_text}"),
            ]
        ])

        result = self.detector.detect(doc_data, layout_doc)

        assert result.found
        assert result.method == "keyword"
        assert "Bài báo này" in result.text
        assert "TÓM TẮT" not in result.text

    # ── Test 3: End keyword (Keywords) ──

    def test_end_keyword_keywords(self):
        """Abstract cắt trước 'Keywords:'."""
        abstract_text = (
            "This paper presents a comprehensive analysis of natural "
            "language processing techniques for Vietnamese text extraction "
            "from academic papers. Our method outperforms baselines."
        )
        doc_data = _make_doc_data([
            [
                "Title",
                f"Abstract\n{abstract_text}\nKeywords: NLP, PDF, extraction",
            ],
        ])
        layout_doc = _make_layout_doc([
            [
                ("TITLE", "Title"),
                ("ABSTRACT", f"Abstract\n{abstract_text}"),
                ("KEYWORD", "Keywords: NLP, PDF, extraction"),
            ]
        ])

        result = self.detector.detect(doc_data, layout_doc)

        assert result.found
        assert "NLP, PDF, extraction" not in result.text
        assert "Keywords" not in result.text

    # ── Test 4: End keyword (Introduction) ──

    def test_end_keyword_introduction(self):
        """Abstract cắt trước '1. Introduction'."""
        abstract_text = (
            "We propose a new framework for document understanding that "
            "combines layout analysis with text extraction methods. "
            "Experiments show significant improvements over prior work."
        )
        doc_data = _make_doc_data([
            [
                "Title",
                f"Abstract\n{abstract_text}\n1. Introduction\nIn this paper...",
            ],
        ])
        layout_doc = _make_layout_doc([
            [
                ("TITLE", "Title"),
                ("ABSTRACT", f"Abstract\n{abstract_text}"),
                ("BODY", "1. Introduction\nIn this paper..."),
            ]
        ])

        result = self.detector.detect(doc_data, layout_doc)

        assert result.found
        assert "In this paper" not in result.text
        assert "Introduction" not in result.text

    # ── Test 5: Layout zone fallback ──

    def test_layout_zone_fallback(self):
        """Không có keyword 'Abstract' nhưng có ABSTRACT zone → extract từ zone."""
        abstract_text = (
            "This study investigates the effectiveness of deep learning "
            "models for automatic metadata extraction from scientific papers. "
            "Results demonstrate superior performance on benchmark datasets."
        )
        # doc_data không chứa keyword "Abstract"
        doc_data = _make_doc_data([
            ["Title of Paper", "Author Names", abstract_text],
        ])
        # layout_doc CÓ ABSTRACT region
        layout_doc = _make_layout_doc([
            [
                ("TITLE", "Title of Paper"),
                ("AUTHOR", "Author Names"),
                ("ABSTRACT", abstract_text),
            ]
        ])

        result = self.detector.detect(doc_data, layout_doc)

        assert result.found
        assert result.method == "zone"
        assert "This study investigates" in result.text

    # ── Test 6: Empty document ──

    def test_empty_document(self):
        """Document rỗng → None."""
        doc_data = DocumentData(file_path="empty.pdf", page_count=0, pages=[])
        layout_doc = LayoutDocument(
            file_path="empty.pdf", page_count=0, pages=[]
        )

        result = self.detector.detect(doc_data, layout_doc)

        assert not result.found
        assert result.text is None
        assert result.method == "none"

    # ── Test 7: Soft hyphen removal ──

    def test_soft_hyphen_removal(self):
        """'infor-\\nmation' → 'information'."""
        cleaned = AbstractDetector._clean_abstract(
            "This paper presents an infor-\nmation extraction system "
            "for processing scien-\ntific documents efficiently and accurately."
        )
        assert "information" in cleaned
        assert "scientific" in cleaned
        assert "-\n" not in cleaned

    # ── Test 8: Excessive blank lines ──

    def test_excessive_blank_lines(self):
        """'line1\\n\\n\\n\\nline2' → normalize."""
        cleaned = AbstractDetector._clean_abstract(
            "First paragraph of the abstract.\n\n\n\n"
            "Second paragraph continues here."
        )
        # Should not have 4 consecutive newlines
        assert "\n\n\n" not in cleaned
        assert "First paragraph" in cleaned
        assert "Second paragraph" in cleaned

    # ── Test 9: Too short ──

    def test_too_short_abstract(self):
        """30 ký tự → invalid, không trả về abstract."""
        short_text = "A" * 30  # 30 chars < 50 minimum
        doc_data = _make_doc_data([
            [f"Abstract\n{short_text}"],
        ])
        layout_doc = _make_layout_doc([
            [("ABSTRACT", f"Abstract\n{short_text}")],
        ])

        result = self.detector.detect(doc_data, layout_doc)

        # Should not return the too-short abstract
        assert not result.found

    # ── Test 10: Too long ──

    def test_too_long_abstract(self):
        """Trên 4000 ký tự → ABSTRACT_TOO_LONG flag nhưng vẫn valid."""
        long_text = (
            "This paper presents an extensive analysis. " * 200
        )  # ~8600 chars
        assert len(long_text) > ABSTRACT_MAX_LENGTH

        doc_data = _make_doc_data([
            [f"Abstract\n{long_text}"],
        ])
        layout_doc = _make_layout_doc([
            [("ABSTRACT", f"Abstract\n{long_text}")],
        ])

        result = self.detector.detect(doc_data, layout_doc)

        assert result.found
        assert ABSTRACT_TOO_LONG in result.flags

    # ── Test 11: High newline ratio → warning flag ──

    def test_high_newline_ratio_flag(self):
        """Newline ratio cao → ABSTRACT_MAY_BE_LIST flag."""
        # Text with lots of very short lines → high newline ratio
        lines = [f"Pt {i}." for i in range(80)]
        text_with_many_newlines = "\n".join(lines)
        # Verify ratio is above threshold before running test
        assert text_with_many_newlines.count("\n") / len(text_with_many_newlines) > 0.10

        doc_data = _make_doc_data([
            [f"Abstract\n{text_with_many_newlines}"],
        ])
        layout_doc = _make_layout_doc([
            [("ABSTRACT", f"Abstract\n{text_with_many_newlines}")],
        ])

        result = self.detector.detect(doc_data, layout_doc)

        if result.found:
            assert ABSTRACT_MAY_BE_LIST in result.flags

    # ── Additional Edge Case Tests ──

    def test_abstract_with_colon(self):
        """'Abstract: This paper...' → extract đúng."""
        abstract_text = (
            "This paper introduces a novel approach for automatic "
            "summarization of scientific articles using transformer models "
            "with attention mechanisms for better performance."
        )
        doc_data = _make_doc_data([
            [f"Abstract: {abstract_text}"],
        ])
        layout_doc = _make_layout_doc([
            [("ABSTRACT", f"Abstract: {abstract_text}")],
        ])

        result = self.detector.detect(doc_data, layout_doc)

        assert result.found
        assert "This paper" in result.text

    def test_abstract_result_to_dict(self):
        """AbstractResult.to_dict() serialization đúng."""
        result = AbstractResult(
            text="Test abstract content with sufficient length for validation.",
            confidence=0.95,
            method="keyword",
            start_page=0,
            end_page=0,
            flags=["ABSTRACT_MAY_BE_LIST"],
        )
        d = result.to_dict()

        assert d["text"] == result.text
        assert d["confidence"] == 0.95
        assert d["method"] == "keyword"
        assert d["flags"] == ["ABSTRACT_MAY_BE_LIST"]
        assert d["length"] == len(result.text)

    def test_abstract_result_properties(self):
        """AbstractResult properties hoạt động đúng."""
        result_found = AbstractResult(text="Some abstract text here.", method="keyword")
        assert result_found.found is True
        assert result_found.length == len("Some abstract text here.")

        result_none = AbstractResult(text=None, method="none")
        assert result_none.found is False
        assert result_none.length == 0

    def test_validate_starts_with_keyword(self):
        """Abstract bắt đầu bằng 'Keywords' → rejected."""
        is_valid, flags = AbstractDetector._validate(
            "Keywords: NLP, machine learning, deep learning and more text to fill minimum"
        )
        assert not is_valid
        assert ABSTRACT_STARTS_WITH_KEYWORD in flags

    def test_validate_only_symbols(self):
        """Abstract chỉ chứa symbols → rejected."""
        is_valid, _ = AbstractDetector._validate(
            "@@@@###$$$%%%&&&***!!!" * 5
        )
        assert not is_valid

    def test_clean_multiple_spaces(self):
        """Multiple spaces trong một dòng → single space."""
        cleaned = AbstractDetector._clean_abstract(
            "This   paper    presents   a   method"
        )
        assert "  " not in cleaned
        assert "This paper presents a method" == cleaned

    def test_keyword_on_separate_line(self):
        """Keyword 'ABSTRACT' đứng riêng trên dòng → extract dòng sau."""
        abstract_text = (
            "Our work addresses the challenge of extracting structured "
            "information from unstructured scientific documents, specifically "
            "focusing on title, author, and abstract extraction."
        )
        doc_data = _make_doc_data([
            ["Some Title", "ABSTRACT", abstract_text],
        ])
        layout_doc = _make_layout_doc([
            [
                ("TITLE", "Some Title"),
                ("ABSTRACT", "ABSTRACT"),
                ("ABSTRACT", abstract_text),
            ]
        ])

        result = self.detector.detect(doc_data, layout_doc)

        assert result.found
        assert "Our work addresses" in result.text


class TestAbstractDetectionService:
    """Tests cho AbstractDetectionService."""

    def test_service_initializes(self):
        """Service khởi tạo thành công."""
        service = AbstractDetectionService()
        assert service._detector is not None

    def test_service_with_custom_detector(self):
        """Service nhận custom detector."""
        custom_detector = AbstractDetector()
        service = AbstractDetectionService(detector=custom_detector)
        assert service._detector is custom_detector

    def test_service_returns_result(self):
        """Service trả về AbstractResult."""
        service = AbstractDetectionService()

        abstract_text = (
            "This paper presents methods for processing scientific "
            "documents and extracting key metadata including titles "
            "and author names with high accuracy."
        )
        doc_data = _make_doc_data([
            [f"Abstract\n{abstract_text}"],
        ])
        layout_doc = _make_layout_doc([
            [("ABSTRACT", f"Abstract\n{abstract_text}")],
        ])

        result = service.detect_abstract(doc_data, layout_doc)

        assert isinstance(result, AbstractResult)
        assert result.found


class TestAbstractDetectionException:
    """Tests cho AbstractDetectionError."""

    def test_exception_message(self):
        """Exception chứa message và file_path đúng."""
        error = AbstractDetectionError("Test error", file_path="test.pdf")
        assert str(error) == "Test error"
        assert error.file_path == "test.pdf"

    def test_exception_default_file_path(self):
        """Exception có default file_path rỗng."""
        error = AbstractDetectionError("Test error")
        assert error.file_path == ""
