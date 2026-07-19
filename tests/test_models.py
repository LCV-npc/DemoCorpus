"""
tests/test_models.py
Unit tests cho domain models: TextBlock, Page, Document, Metadata.
Milestone 0 — Foundation tests.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from core.models.document import TextBlock, Page, Document
from core.models.metadata import (
    FieldConfidence,
    ValidationResult,
    FilterResult,
    ProcessingStep,
    ExtractedMetadata,
)
from config.constants import ZoneType


# ─────────────────────────────────────────────
# TextBlock Tests
# ─────────────────────────────────────────────

class TestTextBlock:
    """Tests cho TextBlock dataclass."""

    def test_textblock_is_bold_true(self):
        """font_flags bit 4 (value=16) → is_bold = True."""
        block = TextBlock(font_flags=16)
        assert block.is_bold is True

    def test_textblock_is_bold_false(self):
        """font_flags = 0 → is_bold = False."""
        block = TextBlock(font_flags=0)
        assert block.is_bold is False

    def test_textblock_is_bold_combined_flags(self):
        """font_flags = 20 (16 + 4) → is_bold = True (bit 4 set)."""
        block = TextBlock(font_flags=20)  # 0b10100
        assert block.is_bold is True

    def test_textblock_properties(self):
        """width, height, center_y tính đúng từ bounding box."""
        block = TextBlock(x0=10.0, y0=20.0, x1=110.0, y1=40.0)
        assert block.width == 100.0
        assert block.height == 20.0
        assert block.center_y == 30.0

    def test_textblock_stripped_text(self):
        """stripped_text bỏ khoảng trắng đầu/cuối."""
        block = TextBlock(text="  Hello World  ")
        assert block.stripped_text == "Hello World"

    def test_textblock_stripped_text_empty(self):
        """stripped_text trên empty string."""
        block = TextBlock(text="")
        assert block.stripped_text == ""

    def test_textblock_default_zone(self):
        """Default zone_type = UNKNOWN."""
        block = TextBlock()
        assert block.zone_type == ZoneType.UNKNOWN


# ─────────────────────────────────────────────
# Page Tests
# ─────────────────────────────────────────────

class TestPage:
    """Tests cho Page dataclass."""

    def _make_page(self):
        """Tạo Page với blocks test."""
        blocks = [
            TextBlock(y0=10, y1=30, font_size=24.0, zone_type=ZoneType.TITLE, text="Title"),
            TextBlock(y0=40, y1=55, font_size=12.0, zone_type=ZoneType.AUTHOR, text="Author"),
            TextBlock(y0=60, y1=100, font_size=10.0, zone_type=ZoneType.ABSTRACT, text="Abstract..."),
            TextBlock(y0=110, y1=700, font_size=10.0, zone_type=ZoneType.BODY, text="Body..."),
            TextBlock(y0=750, y1=780, font_size=8.0, zone_type=ZoneType.FOOTER, text="Page 1"),
        ]
        return Page(page_index=0, width=595.0, height=842.0, blocks=blocks)

    def test_page_blocks_in_zone(self):
        """blocks_in_zone lọc đúng zone_type."""
        page = self._make_page()
        title_blocks = page.blocks_in_zone(ZoneType.TITLE)
        assert len(title_blocks) == 1
        assert title_blocks[0].text == "Title"

    def test_page_blocks_in_zone_empty(self):
        """blocks_in_zone trả về [] khi không có block nào thuộc zone."""
        page = self._make_page()
        header_blocks = page.blocks_in_zone(ZoneType.HEADER)
        assert header_blocks == []

    def test_page_max_font_size(self):
        """max_font_size trả về font size lớn nhất."""
        page = self._make_page()
        assert page.max_font_size() == 24.0

    def test_page_max_font_size_empty(self):
        """max_font_size = 0.0 khi không có blocks."""
        page = Page()
        assert page.max_font_size() == 0.0

    def test_page_top_fraction_blocks(self):
        """top_fraction_blocks(0.35) lấy blocks nằm trong 35% trên."""
        page = self._make_page()
        # 842 * 0.35 = 294.7 → blocks có y0 < 294.7
        top_blocks = page.top_fraction_blocks(0.35)
        assert len(top_blocks) >= 3  # Title, Author, Abstract


# ─────────────────────────────────────────────
# Document Tests
# ─────────────────────────────────────────────

class TestDocument:
    """Tests cho Document dataclass."""

    def test_document_first_page(self):
        """first_page trả về trang đầu tiên."""
        pages = [Page(page_index=0), Page(page_index=1)]
        doc = Document(file_path="test.pdf", pages=pages, page_count=2)
        assert doc.first_page is not None
        assert doc.first_page.page_index == 0

    def test_document_first_page_empty(self):
        """first_page = None khi document rỗng."""
        doc = Document()
        assert doc.first_page is None

    def test_document_all_blocks(self):
        """all_blocks gom tất cả blocks từ mọi trang."""
        page1 = Page(blocks=[TextBlock(text="A"), TextBlock(text="B")])
        page2 = Page(blocks=[TextBlock(text="C")])
        doc = Document(pages=[page1, page2])
        assert len(doc.all_blocks()) == 3

    def test_document_blocks_on_page(self):
        """blocks_on_page trả về blocks ở trang chỉ định."""
        page = Page(blocks=[TextBlock(text="Hello")])
        doc = Document(pages=[page])
        assert len(doc.blocks_on_page(0)) == 1
        assert doc.blocks_on_page(0)[0].text == "Hello"

    def test_document_blocks_on_page_out_of_range(self):
        """blocks_on_page trả về [] khi page_num ngoài phạm vi."""
        doc = Document(pages=[Page()])
        assert doc.blocks_on_page(99) == []


# ─────────────────────────────────────────────
# Metadata Tests
# ─────────────────────────────────────────────

class TestFieldConfidence:
    """Tests cho FieldConfidence."""

    def test_field_confidence_passed_true(self):
        """score >= 0.5 → passed = True."""
        fc = FieldConfidence(field_name="title", score=0.8)
        assert fc.passed is True

    def test_field_confidence_passed_threshold(self):
        """score = 0.5 (exactly at threshold) → passed = True."""
        fc = FieldConfidence(field_name="title", score=0.5)
        assert fc.passed is True

    def test_field_confidence_passed_false(self):
        """score < 0.5 → passed = False."""
        fc = FieldConfidence(field_name="title", score=0.3)
        assert fc.passed is False


class TestValidationResult:
    """Tests cho ValidationResult."""

    def test_validation_overall_score(self):
        """overall_score = mean of 3 field scores."""
        vr = ValidationResult(
            title=FieldConfidence(score=0.9),
            authors=FieldConfidence(score=0.6),
            abstract=FieldConfidence(score=0.3),
        )
        expected = (0.9 + 0.6 + 0.3) / 3
        assert abs(vr.overall_score - expected) < 1e-6

    def test_validation_is_valid_true(self):
        """is_valid khi overall_score >= 0.5."""
        vr = ValidationResult(
            title=FieldConfidence(score=0.8),
            authors=FieldConfidence(score=0.7),
            abstract=FieldConfidence(score=0.6),
        )
        assert vr.is_valid is True

    def test_validation_is_valid_false(self):
        """is_valid = False khi overall_score < 0.5."""
        vr = ValidationResult(
            title=FieldConfidence(score=0.1),
            authors=FieldConfidence(score=0.2),
            abstract=FieldConfidence(score=0.1),
        )
        assert vr.is_valid is False


class TestExtractedMetadata:
    """Tests cho ExtractedMetadata."""

    def test_metadata_to_dict(self):
        """to_dict() serialize đúng cấu trúc."""
        meta = ExtractedMetadata(
            paper_id="test-123",
            source="upload",
            file_path="/path/to/file.pdf",
            file_hash_sha256="abc123",
            title="Test Title",
            authors=["Author A", "Author B"],
            abstract="Test abstract.",
        )
        d = meta.to_dict()
        assert d["paper_id"] == "test-123"
        assert d["source"] == "upload"
        assert d["file_path"] == "/path/to/file.pdf"
        assert d["file_hash_sha256"] == "abc123"
        assert d["extracted"]["title"] == "Test Title"
        assert d["extracted"]["authors"] == ["Author A", "Author B"]
        assert d["extracted"]["abstract"] == "Test abstract."
        assert "confidence" in d
        assert "processing" in d
        assert "review" in d

    def test_metadata_overall_confidence_default(self):
        """overall_confidence = 0.0 khi chưa validate."""
        meta = ExtractedMetadata()
        assert meta.overall_confidence == 0.0

    def test_metadata_overall_confidence_with_validation(self):
        """overall_confidence dùng validation result."""
        vr = ValidationResult(
            title=FieldConfidence(score=0.9),
            authors=FieldConfidence(score=0.8),
            abstract=FieldConfidence(score=0.7),
        )
        meta = ExtractedMetadata(confidence=vr)
        assert abs(meta.overall_confidence - 0.8) < 1e-6

    def test_metadata_has_all_fields_true(self):
        """has_all_fields khi title, authors, abstract đều có."""
        meta = ExtractedMetadata(
            title="Title",
            authors=["Author"],
            abstract="Abstract",
        )
        assert meta.has_all_fields is True

    def test_metadata_has_all_fields_false(self):
        """has_all_fields = False khi thiếu bất kỳ field nào."""
        meta = ExtractedMetadata(title="Title")
        assert meta.has_all_fields is False

    def test_metadata_auto_paper_id(self):
        """paper_id tự sinh UUID."""
        meta = ExtractedMetadata()
        assert meta.paper_id is not None
        assert len(meta.paper_id) > 0
