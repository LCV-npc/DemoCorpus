"""
tests/test_text_extraction.py
Unit tests cho module core/text_extraction.
Milestone 2 — Text Extraction tests.
"""

import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

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
from core.text_extraction.utils import (
    is_born_digital,
    parse_font_flags,
    compute_extraction_stats,
    safe_color_to_hex,
)
from core.text_extraction.extractor import PDFTextExtractor
from core.text_extraction.service import TextExtractionService


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

# Đường dẫn đến thư mục gốc chứa PDF mẫu
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SAMPLE_PDFS_DIR = _PROJECT_ROOT  # PDFs nằm tại d:\Nghiên cứu khoa học\


def _get_sample_pdf(filename: str) -> str | None:
    """Trả về path đến PDF mẫu, None nếu không tồn tại."""
    path = _SAMPLE_PDFS_DIR / filename
    return str(path) if path.exists() else None


@pytest.fixture
def sample_pdf_path():
    """PDF mẫu thật cho integration tests."""
    path = _get_sample_pdf("2311.02945v3.pdf")
    if path is None:
        pytest.skip("Sample PDF not found: 2311.02945v3.pdf")
    return path


@pytest.fixture
def extractor():
    """PDFTextExtractor instance."""
    return PDFTextExtractor()


@pytest.fixture
def service():
    """TextExtractionService instance."""
    return TextExtractionService()


# ─────────────────────────────────────────────
# SpanData Tests
# ─────────────────────────────────────────────

class TestSpanData:
    """Tests cho SpanData dataclass."""

    def test_span_creation(self):
        """Khởi tạo SpanData với tất cả fields."""
        span = SpanData(
            text="Hello",
            font_name="Arial",
            font_size=12.0,
            font_flags=16,
            color="#FF0000",
            bbox=(10.0, 20.0, 100.0, 35.0),
        )
        assert span.text == "Hello"
        assert span.font_name == "Arial"
        assert span.font_size == 12.0
        assert span.font_flags == 16
        assert span.color == "#FF0000"
        assert span.bbox == (10.0, 20.0, 100.0, 35.0)

    def test_span_defaults(self):
        """SpanData có default values hợp lý."""
        span = SpanData()
        assert span.text == ""
        assert span.font_name == ""
        assert span.font_size == 0.0
        assert span.font_flags == 0
        assert span.color == "#000000"
        assert span.bbox == (0.0, 0.0, 0.0, 0.0)

    def test_span_to_dict(self):
        """to_dict() serialize đúng cấu trúc."""
        span = SpanData(
            text="Test",
            font_name="Times",
            font_size=14.0,
            font_flags=2,
            color="#0000FF",
            bbox=(5.0, 10.0, 200.0, 25.0),
        )
        d = span.to_dict()
        assert d["text"] == "Test"
        assert d["font_name"] == "Times"
        assert d["font_size"] == 14.0
        assert d["font_flags"] == 2
        assert d["color"] == "#0000FF"
        assert d["bbox"] == [5.0, 10.0, 200.0, 25.0]  # tuple → list

    def test_span_to_dict_bbox_is_list(self):
        """to_dict() chuyển bbox tuple thành list cho JSON serialization."""
        span = SpanData(bbox=(1.0, 2.0, 3.0, 4.0))
        d = span.to_dict()
        assert isinstance(d["bbox"], list)


# ─────────────────────────────────────────────
# LineData Tests
# ─────────────────────────────────────────────

class TestLineData:
    """Tests cho LineData dataclass."""

    def test_line_text_from_spans(self):
        """Text property ghép text từ tất cả spans."""
        line = LineData(spans=[
            SpanData(text="Hello "),
            SpanData(text="World"),
        ])
        assert line.text == "Hello World"

    def test_line_text_empty_spans(self):
        """Text = '' khi không có spans."""
        line = LineData()
        assert line.text == ""

    def test_line_to_dict(self):
        """to_dict() serialize line với spans."""
        line = LineData(
            bbox=(10.0, 20.0, 300.0, 35.0),
            spans=[SpanData(text="A"), SpanData(text="B")],
        )
        d = line.to_dict()
        assert d["bbox"] == [10.0, 20.0, 300.0, 35.0]
        assert len(d["spans"]) == 2
        assert d["spans"][0]["text"] == "A"
        assert d["spans"][1]["text"] == "B"


# ─────────────────────────────────────────────
# BlockData Tests
# ─────────────────────────────────────────────

class TestBlockData:
    """Tests cho BlockData dataclass."""

    def test_block_text_from_lines(self):
        """Text property ghép từ lines, cách nhau bởi newline."""
        block = BlockData(lines=[
            LineData(spans=[SpanData(text="Line 1")]),
            LineData(spans=[SpanData(text="Line 2")]),
        ])
        assert block.text == "Line 1\nLine 2"

    def test_block_text_empty_lines(self):
        """Text = '' khi không có lines."""
        block = BlockData()
        assert block.text == ""

    def test_block_to_dict(self):
        """to_dict() serialize block với lines."""
        block = BlockData(
            block_number=3,
            block_type=0,
            bbox=(10.0, 20.0, 500.0, 100.0),
            lines=[LineData(spans=[SpanData(text="Content")])],
        )
        d = block.to_dict()
        assert d["block_number"] == 3
        assert d["block_type"] == 0
        assert d["bbox"] == [10.0, 20.0, 500.0, 100.0]
        assert len(d["lines"]) == 1


# ─────────────────────────────────────────────
# PageData Tests
# ─────────────────────────────────────────────

class TestPageData:
    """Tests cho PageData dataclass."""

    def test_page_text_skips_image_blocks(self):
        """text property chỉ lấy text blocks (type=0), bỏ qua image (type=1)."""
        page = PageData(blocks=[
            BlockData(block_type=0, lines=[LineData(spans=[SpanData(text="Text")])]),
            BlockData(block_type=1),  # image block, no lines
            BlockData(block_type=0, lines=[LineData(spans=[SpanData(text="More")])]),
        ])
        assert "Text" in page.text
        assert "More" in page.text

    def test_page_image_count(self):
        """image_count theo dõi số image blocks."""
        page = PageData(image_count=3)
        assert page.image_count == 3

    def test_page_dimensions(self):
        """width và height lưu đúng."""
        page = PageData(width=595.0, height=842.0)
        assert page.width == 595.0
        assert page.height == 842.0

    def test_page_to_dict(self):
        """to_dict() serialize page data."""
        page = PageData(
            page_number=0,
            width=595.0,
            height=842.0,
            image_count=2,
            blocks=[BlockData(block_number=0)],
        )
        d = page.to_dict()
        assert d["page_number"] == 0
        assert d["width"] == 595.0
        assert d["height"] == 842.0
        assert d["image_count"] == 2
        assert len(d["blocks"]) == 1


# ─────────────────────────────────────────────
# DocumentData Tests
# ─────────────────────────────────────────────

class TestDocumentData:
    """Tests cho DocumentData dataclass."""

    def test_document_stats(self):
        """total_blocks và total_spans ghi nhận đúng."""
        doc = DocumentData(
            page_count=2,
            total_blocks=15,
            total_spans=47,
        )
        assert doc.page_count == 2
        assert doc.total_blocks == 15
        assert doc.total_spans == 47

    def test_document_born_digital_flag(self):
        """is_born_digital flag."""
        doc = DocumentData(is_born_digital=False)
        assert doc.is_born_digital is False

    def test_document_to_dict(self):
        """to_dict() serialize toàn bộ document."""
        doc = DocumentData(
            file_path="test.pdf",
            page_count=1,
            is_born_digital=True,
            extraction_time_seconds=0.5,
            total_blocks=5,
            total_spans=20,
            pages=[PageData(page_number=0, width=595.0, height=842.0)],
        )
        d = doc.to_dict()
        assert d["file_path"] == "test.pdf"
        assert d["page_count"] == 1
        assert d["is_born_digital"] is True
        assert d["extraction_time_seconds"] == 0.5
        assert d["total_blocks"] == 5
        assert d["total_spans"] == 20
        assert len(d["pages"]) == 1

    def test_document_to_dict_has_all_keys(self):
        """to_dict() chứa tất cả expected keys."""
        doc = DocumentData()
        d = doc.to_dict()
        expected_keys = {
            "file_path", "page_count", "is_born_digital",
            "extraction_time_seconds", "total_blocks", "total_spans", "pages",
        }
        assert set(d.keys()) == expected_keys


# ─────────────────────────────────────────────
# Exception Tests
# ─────────────────────────────────────────────

class TestExceptions:
    """Tests cho custom exception hierarchy."""

    def test_base_exception(self):
        """PDFExtractionError là base class."""
        err = PDFExtractionError("test error", file_path="test.pdf")
        assert str(err) == "test error"
        assert err.file_path == "test.pdf"

    def test_corrupted_is_extraction_error(self):
        """PDFCorruptedError kế thừa PDFExtractionError."""
        err = PDFCorruptedError(file_path="bad.pdf", detail="parse failed")
        assert isinstance(err, PDFExtractionError)
        assert "bad.pdf" in str(err)
        assert "parse failed" in str(err)

    def test_encrypted_is_extraction_error(self):
        """PDFEncryptedError kế thừa PDFExtractionError."""
        err = PDFEncryptedError(file_path="secret.pdf")
        assert isinstance(err, PDFExtractionError)
        assert "secret.pdf" in str(err)
        assert "password" in str(err).lower() or "encrypted" in str(err).lower()

    def test_empty_is_extraction_error(self):
        """PDFEmptyError kế thừa PDFExtractionError."""
        err = PDFEmptyError(file_path="empty.pdf")
        assert isinstance(err, PDFExtractionError)
        assert "empty.pdf" in str(err)
        assert "0 pages" in str(err)

    def test_exception_hierarchy_catch(self):
        """Có thể catch tất cả subclasses bằng PDFExtractionError."""
        exceptions = [
            PDFCorruptedError("test.pdf"),
            PDFEncryptedError("test.pdf"),
            PDFEmptyError("test.pdf"),
        ]
        for exc in exceptions:
            with pytest.raises(PDFExtractionError):
                raise exc


# ─────────────────────────────────────────────
# Utils Tests
# ─────────────────────────────────────────────

class TestUtils:
    """Tests cho utility functions."""

    def test_is_born_digital_true(self):
        """PDF có nhiều text → born digital."""
        pages = [PageData(blocks=[
            BlockData(block_type=0, lines=[
                LineData(spans=[SpanData(text="A" * 200)])
            ])
        ])]
        assert is_born_digital(pages) is True

    def test_is_born_digital_false(self):
        """PDF ít text → scanned."""
        pages = [PageData(blocks=[
            BlockData(block_type=0, lines=[
                LineData(spans=[SpanData(text="ab")])
            ])
        ])]
        assert is_born_digital(pages) is False

    def test_is_born_digital_threshold(self):
        """Exactly at threshold → True."""
        pages = [PageData(blocks=[
            BlockData(block_type=0, lines=[
                LineData(spans=[SpanData(text="x" * 100)])
            ])
        ])]
        assert is_born_digital(pages, threshold=100) is True

    def test_is_born_digital_below_threshold(self):
        """One below threshold → False."""
        pages = [PageData(blocks=[
            BlockData(block_type=0, lines=[
                LineData(spans=[SpanData(text="x" * 99)])
            ])
        ])]
        assert is_born_digital(pages, threshold=100) is False

    def test_is_born_digital_empty_pages(self):
        """Không có pages → False."""
        assert is_born_digital([]) is False

    def test_parse_font_flags_bold(self):
        """Flag 16 → bold=True."""
        result = parse_font_flags(16)
        assert result["bold"] is True
        assert result["italic"] is False

    def test_parse_font_flags_italic(self):
        """Flag 2 → italic=True."""
        result = parse_font_flags(2)
        assert result["italic"] is True
        assert result["bold"] is False

    def test_parse_font_flags_combined(self):
        """Flag 20 (16+4) → bold=True, serif=True."""
        result = parse_font_flags(20)
        assert result["bold"] is True
        assert result["serif"] is True
        assert result["italic"] is False

    def test_parse_font_flags_all(self):
        """Flag 31 (all bits) → all True."""
        result = parse_font_flags(31)
        assert all(result.values())

    def test_parse_font_flags_zero(self):
        """Flag 0 → all False."""
        result = parse_font_flags(0)
        assert not any(result.values())

    def test_safe_color_to_hex_black(self):
        """Color 0 → #000000."""
        assert safe_color_to_hex(0) == "#000000"

    def test_safe_color_to_hex_red(self):
        """Color 16711680 (0xFF0000) → #FF0000."""
        assert safe_color_to_hex(16711680) == "#FF0000"

    def test_safe_color_to_hex_blue(self):
        """Color 255 (0x0000FF) → #0000FF."""
        assert safe_color_to_hex(255) == "#0000FF"

    def test_safe_color_to_hex_white(self):
        """Color 16777215 (0xFFFFFF) → #FFFFFF."""
        assert safe_color_to_hex(16777215) == "#FFFFFF"

    def test_safe_color_to_hex_negative(self):
        """Negative color clamped to 0 → #000000."""
        assert safe_color_to_hex(-1) == "#000000"

    def test_compute_extraction_stats(self):
        """compute_extraction_stats tính đúng."""
        doc = DocumentData(pages=[
            PageData(
                image_count=1,
                blocks=[
                    BlockData(lines=[
                        LineData(spans=[
                            SpanData(text="Hello"),
                            SpanData(text=" World"),
                        ]),
                    ]),
                    BlockData(lines=[
                        LineData(spans=[SpanData(text="Foo")]),
                    ]),
                ],
            ),
        ])
        stats = compute_extraction_stats(doc)
        assert stats["total_blocks"] == 2
        assert stats["total_lines"] == 2
        assert stats["total_spans"] == 3
        assert stats["total_chars"] == 14  # "Hello" + " World" + "Foo"
        assert stats["total_images"] == 1
        assert stats["avg_blocks_per_page"] == 2.0

    def test_compute_extraction_stats_empty(self):
        """Stats cho document rỗng."""
        doc = DocumentData()
        stats = compute_extraction_stats(doc)
        assert stats["total_blocks"] == 0
        assert stats["total_lines"] == 0
        assert stats["total_spans"] == 0
        assert stats["total_chars"] == 0
        assert stats["total_images"] == 0
        assert stats["avg_blocks_per_page"] == 0.0


# ─────────────────────────────────────────────
# PDFTextExtractor Tests
# ─────────────────────────────────────────────

class TestPDFTextExtractor:
    """Tests cho PDFTextExtractor."""

    def test_extract_file_not_found(self, extractor):
        """PDFExtractionError khi file không tồn tại."""
        with pytest.raises(PDFExtractionError, match="File not found"):
            extractor.extract("/nonexistent/path.pdf")

    def test_extract_corrupted_file(self, extractor, tmp_path):
        """PDFCorruptedError khi file không phải PDF hợp lệ."""
        bad_file = tmp_path / "corrupted.pdf"
        bad_file.write_bytes(b"This is not a PDF at all")

        with pytest.raises(PDFCorruptedError):
            extractor.extract(str(bad_file))

    def test_extract_valid_pdf(self, extractor, sample_pdf_path):
        """Extract PDF thật → DocumentData có pages > 0."""
        result = extractor.extract(sample_pdf_path)

        assert isinstance(result, DocumentData)
        assert result.page_count > 0
        assert len(result.pages) == result.page_count
        assert result.file_path == sample_pdf_path
        assert result.extraction_time_seconds > 0

    def test_extract_has_blocks(self, extractor, sample_pdf_path):
        """PDF thật phải có blocks."""
        result = extractor.extract(sample_pdf_path)

        assert result.total_blocks > 0
        # Page đầu phải có blocks
        first_page = result.pages[0]
        assert len(first_page.blocks) > 0

    def test_extract_has_spans(self, extractor, sample_pdf_path):
        """PDF thật phải có spans với font metadata."""
        result = extractor.extract(sample_pdf_path)
        assert result.total_spans > 0

        # Tìm span đầu tiên và kiểm tra metadata
        for page in result.pages:
            for block in page.blocks:
                for line in block.lines:
                    for span in line.spans:
                        if span.text.strip():
                            assert span.font_name != ""
                            assert span.font_size > 0
                            return
        pytest.fail("No spans with text found")

    def test_extract_page_dimensions(self, extractor, sample_pdf_path):
        """Mỗi page phải có width và height > 0."""
        result = extractor.extract(sample_pdf_path)

        for page in result.pages:
            assert page.width > 0
            assert page.height > 0

    def test_extract_born_digital(self, extractor, sample_pdf_path):
        """PDF có text layer → is_born_digital = True."""
        result = extractor.extract(sample_pdf_path)
        assert result.is_born_digital is True

    def test_extract_scanned_pdf_simulation(self, extractor, tmp_path):
        """
        Simulate scanned PDF bằng cách tạo PDF chỉ có image.
        Dùng PyMuPDF để tạo PDF trống (không có text).
        """
        import fitz

        pdf_path = str(tmp_path / "scanned.pdf")
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        # Tạo page trống → không có text blocks
        doc.save(pdf_path)
        doc.close()

        result = extractor.extract(pdf_path)
        assert result.is_born_digital is False

    def test_extract_to_dict_roundtrip(self, extractor, sample_pdf_path):
        """to_dict() tạo output JSON-compatible."""
        result = extractor.extract(sample_pdf_path)
        d = result.to_dict()

        # Validate structure
        assert "file_path" in d
        assert "page_count" in d
        assert "pages" in d
        assert isinstance(d["pages"], list)
        assert len(d["pages"]) > 0

        # Validate nested structure
        first_page = d["pages"][0]
        assert "page_number" in first_page
        assert "width" in first_page
        assert "height" in first_page
        assert "blocks" in first_page

    def test_extract_empty_pdf(self, extractor, tmp_path):
        """PDFEmptyError khi PDF có 0 pages."""
        import fitz

        # PyMuPDF không cho save PDF 0 pages, nên dùng mock
        mock_doc = MagicMock()
        mock_doc.is_encrypted = False
        mock_doc.page_count = 0
        mock_doc.__enter__ = MagicMock(return_value=mock_doc)
        mock_doc.__exit__ = MagicMock(return_value=False)

        # Tạo file PDF giả để bypass file existence check
        pdf_path = str(tmp_path / "empty.pdf")
        real_doc = fitz.open()
        real_doc.new_page()
        real_doc.save(pdf_path)
        real_doc.close()

        with patch("core.text_extraction.extractor.fitz.open", return_value=mock_doc):
            with pytest.raises(PDFEmptyError):
                extractor.extract(pdf_path)

    def test_extract_multipage(self, extractor, sample_pdf_path):
        """PDF nhiều trang → đúng số lượng pages."""
        result = extractor.extract(sample_pdf_path)
        # 2311.02945v3.pdf thường có nhiều trang
        assert result.page_count == len(result.pages)

    def test_extract_bbox_values(self, extractor, sample_pdf_path):
        """Bounding box phải có giá trị hợp lý (positive, x0 < x1, y0 < y1)."""
        result = extractor.extract(sample_pdf_path)

        for page in result.pages:
            for block in page.blocks:
                x0, y0, x1, y1 = block.bbox
                assert x0 <= x1, f"Block bbox x0={x0} > x1={x1}"
                assert y0 <= y1, f"Block bbox y0={y0} > y1={y1}"


# ─────────────────────────────────────────────
# TextExtractionService Tests
# ─────────────────────────────────────────────

class TestTextExtractionService:
    """Tests cho TextExtractionService."""

    def test_service_extract_document(self, service, sample_pdf_path):
        """Service extract trả về DocumentData hợp lệ."""
        result = service.extract_document(sample_pdf_path)

        assert isinstance(result, DocumentData)
        assert result.page_count > 0
        assert result.total_blocks > 0

    def test_service_extract_error_handling(self, service):
        """Service raise PDFExtractionError cho file không tồn tại."""
        with pytest.raises(PDFExtractionError):
            service.extract_document("/nonexistent/file.pdf")

    def test_service_batch_extract(self, service, sample_pdf_path):
        """Batch extract xử lý đúng list files."""
        results = service.extract_batch([sample_pdf_path])

        assert len(results) == 1
        assert results[0] is not None
        assert isinstance(results[0], DocumentData)

    def test_service_batch_with_errors(self, service, sample_pdf_path):
        """Batch: file lỗi → None, file hợp lệ → DocumentData."""
        results = service.extract_batch([
            "/nonexistent/bad.pdf",
            sample_pdf_path,
        ])

        assert len(results) == 2
        assert results[0] is None  # File lỗi
        assert results[1] is not None  # File hợp lệ

    def test_service_batch_empty_list(self, service):
        """Batch với list rỗng → list rỗng."""
        results = service.extract_batch([])
        assert results == []

    def test_service_dependency_injection(self):
        """Service nhận custom extractor qua DI."""
        mock_extractor = MagicMock(spec=PDFTextExtractor)
        mock_result = DocumentData(page_count=1, total_blocks=5)
        mock_extractor.extract.return_value = mock_result

        service = TextExtractionService(extractor=mock_extractor)
        result = service.extract_document("dummy.pdf")

        mock_extractor.extract.assert_called_once_with("dummy.pdf")
        assert result.page_count == 1
        assert result.total_blocks == 5

    def test_service_logging(self, service, sample_pdf_path, caplog):
        """Service ghi log đúng khi extract."""
        import logging
        with caplog.at_level(logging.INFO):
            service.extract_document(sample_pdf_path)

        assert any("Starting extraction" in r.message for r in caplog.records)
        assert any("Extraction complete" in r.message for r in caplog.records)

    def test_service_error_logging(self, service, caplog):
        """Service ghi log lỗi khi extract thất bại."""
        import logging
        with caplog.at_level(logging.ERROR):
            try:
                service.extract_document("/nonexistent/path.pdf")
            except PDFExtractionError:
                pass

        assert any("Extraction failed" in r.message for r in caplog.records)
