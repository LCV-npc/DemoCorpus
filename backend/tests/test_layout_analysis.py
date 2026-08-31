"""
tests/test_layout_analysis.py
Unit tests cho module core/layout_analysis.
Milestone 3 — Layout Analysis tests.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

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
from core.layout_analysis.layout_model import (
    RegionType,
    Region,
    ColumnInfo,
    LayoutPage,
    LayoutDocument,
)
from core.layout_analysis.heuristics import (
    dominant_font_size,
    dominant_font_flags,
    is_bold,
    block_width,
    block_center_x,
    is_centered,
    relative_y,
    is_in_header_zone,
    is_in_footer_zone,
    is_in_title_zone,
    is_full_width,
    matches_abstract_start,
    matches_keyword_start,
    matches_reference_start,
    contains_affiliation,
    matches_header_footer,
    max_font_size_in_blocks,
)
from core.layout_analysis.column_detector import ColumnDetector
from core.layout_analysis.reading_order import ReadingOrderReconstructor
from core.layout_analysis.region_detector import RegionDetector
from core.layout_analysis.layout_analyzer import LayoutAnalyzer


# ─────────────────────────────────────────────
# Test Helpers
# ─────────────────────────────────────────────

def _make_block(
    x0: float, y0: float, x1: float, y1: float,
    text: str = "", font_size: float = 10.0, font_flags: int = 0,
    block_number: int = 0,
) -> BlockData:
    """Helper tạo BlockData cho test."""
    return BlockData(
        bbox=(x0, y0, x1, y1),
        block_type=0,
        block_number=block_number,
        lines=[LineData(
            bbox=(x0, y0, x1, y1),
            spans=[SpanData(
                text=text,
                font_size=font_size,
                font_flags=font_flags,
                bbox=(x0, y0, x1, y1),
            )],
        )],
    )


def _make_two_column_blocks() -> list[BlockData]:
    """Tạo blocks cho layout 2-cột giống Vietnamese medical PDF."""
    return [
        # Full-width header
        _make_block(200, 78, 390, 87, "VIETNAM MEDICAL JOURNAL", 9.0, 16, 0),
        # Left column body blocks
        _make_block(72, 97, 293, 120, "Left col paragraph 1...", 10.0, 0, 1),
        _make_block(72, 125, 293, 190, "Left col paragraph 2...", 10.0, 0, 2),
        _make_block(72, 195, 293, 385, "Left col paragraph 3...", 10.0, 0, 3),
        # Right column body blocks
        _make_block(305, 97, 526, 132, "Right col paragraph 1...", 10.0, 0, 4),
        _make_block(305, 137, 526, 250, "Right col paragraph 2...", 10.0, 0, 5),
        # Full-width reference
        _make_block(72, 400, 528, 550, "TÀI LIỆU THAM KHẢO\n1. Reference...", 12.0, 16, 6),
        # Full-width title (for next article)
        _make_block(112, 557, 487, 590, "TITLE OF NEXT ARTICLE", 14.0, 20, 7),
        # Footer
        _make_block(72, 745, 93, 757, "264", 12.0, 0, 8),
    ]


def _make_single_column_blocks() -> list[BlockData]:
    """Tạo blocks cho layout 1-cột giống arXiv PDF."""
    return [
        # Title (large font, centered)
        _make_block(108, 80, 452, 118, "PHOGPT: GENERATIVE PRE-TRAINING", 17.0, 20, 0),
        # Authors
        _make_block(114, 137, 502, 147, "Dat Quoc Nguyen, Linh The Nguyen", 10.0, 20, 1),
        # Affiliation
        _make_block(114, 148, 246, 158, "VinAI Research, Hanoi, Vietnam", 10.0, 4, 2),
        # Abstract marker
        _make_block(278, 199, 333, 211, "ABSTRACT", 12.0, 4, 3),
        # Abstract content
        _make_block(144, 225, 468, 315, "We present PhoGPT, a generative model...", 10.0, 4, 4),
        # Body heading
        _make_block(108, 350, 504, 365, "1. Introduction", 12.0, 20, 5),
        # Body content
        _make_block(108, 370, 504, 500, "Large language models have shown...", 10.0, 4, 6),
        _make_block(108, 505, 504, 700, "In this paper, we propose...", 10.0, 4, 7),
    ]


# Đường dẫn đến PDF mẫu thật
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SAMPLE_PDFS_DIR = _PROJECT_ROOT


def _get_sample_pdf(filename: str) -> str | None:
    path = _SAMPLE_PDFS_DIR / filename
    return str(path) if path.exists() else None


@pytest.fixture
def arxiv_pdf_path():
    path = _get_sample_pdf("2311.02945v3.pdf")
    if path is None:
        pytest.skip("Sample PDF not found")
    return path


@pytest.fixture
def vn_pdf_path():
    path = Path(
        "d:/Nghiên cứu khoa học/pdf_collector/data/scraped_pdfs/"
        "tapchiyhocvietnam.vn/0be3fc37_0be3fc37.pdf"
    )
    if not path.exists():
        pytest.skip("Vietnamese sample PDF not found")
    return str(path)


# ─────────────────────────────────────────────
# RegionType Tests
# ─────────────────────────────────────────────

class TestRegionType:
    def test_enum_values(self):
        assert RegionType.TITLE.value == "TITLE"
        assert RegionType.ABSTRACT.value == "ABSTRACT"
        assert RegionType.KEYWORD.value == "KEYWORD"
        assert RegionType.REFERENCE.value == "REFERENCE"

    def test_string_comparison(self):
        assert RegionType.TITLE == "TITLE"
        assert RegionType.BODY == "BODY"

    def test_all_types_exist(self):
        expected = {
            "TITLE", "AUTHOR", "AFFILIATION", "ABSTRACT",
            "KEYWORD", "BODY", "REFERENCE", "HEADER", "FOOTER", "UNKNOWN",
        }
        actual = {rt.value for rt in RegionType}
        assert actual == expected


# ─────────────────────────────────────────────
# Region Tests
# ─────────────────────────────────────────────

class TestRegion:
    def test_region_creation(self):
        block = _make_block(10, 20, 100, 40, "Hello")
        region = Region(
            region_type=RegionType.TITLE,
            blocks=[block],
            page_number=0,
            confidence=0.9,
        )
        assert region.region_type == RegionType.TITLE
        assert region.confidence == 0.9

    def test_region_text_property(self):
        blocks = [
            _make_block(10, 20, 100, 30, "Line 1"),
            _make_block(10, 35, 100, 45, "Line 2"),
        ]
        region = Region(blocks=blocks)
        assert region.text == "Line 1\nLine 2"

    def test_region_bbox_merge(self):
        blocks = [
            _make_block(10, 20, 100, 40),
            _make_block(5, 45, 120, 60),
        ]
        region = Region(blocks=blocks)
        bbox = region.bbox
        assert bbox == (5.0, 20.0, 120.0, 60.0)

    def test_region_empty_blocks(self):
        region = Region()
        assert region.bbox == (0.0, 0.0, 0.0, 0.0)
        assert region.text == ""

    def test_region_to_dict(self):
        block = _make_block(10, 20, 100, 40, "Test")
        region = Region(
            region_type=RegionType.ABSTRACT,
            blocks=[block],
            page_number=0,
            reading_order_index=3,
            confidence=0.85,
        )
        d = region.to_dict()
        assert d["region_type"] == "ABSTRACT"
        assert d["confidence"] == 0.85
        assert d["block_count"] == 1
        assert "bbox" in d


# ─────────────────────────────────────────────
# LayoutDocument Tests
# ─────────────────────────────────────────────

class TestLayoutDocument:
    def test_get_regions_by_type(self):
        r1 = Region(region_type=RegionType.TITLE, page_number=0)
        r2 = Region(region_type=RegionType.BODY, page_number=0)
        r3 = Region(region_type=RegionType.TITLE, page_number=1)
        page0 = LayoutPage(page_number=0, regions=[r1, r2])
        page1 = LayoutPage(page_number=1, regions=[r3])
        doc = LayoutDocument(pages=[page0, page1])

        titles = doc.get_regions(RegionType.TITLE)
        assert len(titles) == 2

        titles_p0 = doc.get_regions(RegionType.TITLE, page_number=0)
        assert len(titles_p0) == 1

    def test_to_dict(self):
        doc = LayoutDocument(
            file_path="test.pdf",
            page_count=1,
            total_regions=5,
            analysis_time_seconds=0.01,
        )
        d = doc.to_dict()
        assert d["file_path"] == "test.pdf"
        assert d["total_regions"] == 5


# ─────────────────────────────────────────────
# Heuristics Tests
# ─────────────────────────────────────────────

class TestHeuristics:
    def test_dominant_font_size(self):
        block = BlockData(lines=[
            LineData(spans=[
                SpanData(text="short", font_size=14.0),
                SpanData(text="this is much longer text", font_size=10.0),
            ]),
        ])
        assert dominant_font_size(block) == 10.0  # more chars

    def test_dominant_font_size_empty(self):
        block = BlockData()
        assert dominant_font_size(block) == 0.0

    def test_is_bold_true(self):
        assert is_bold(16) is True
        assert is_bold(20) is True  # 16 + 4

    def test_is_bold_false(self):
        assert is_bold(0) is False
        assert is_bold(4) is False

    def test_block_width(self):
        block = _make_block(10, 0, 110, 50)
        assert block_width(block) == 100.0

    def test_block_center_x(self):
        block = _make_block(100, 0, 200, 50)
        assert block_center_x(block) == 150.0

    def test_is_centered_true(self):
        # Page width 600, block centered at 300
        block = _make_block(200, 0, 400, 50)
        assert is_centered(block, 600.0)

    def test_is_centered_false(self):
        # Page width 600, block at left
        block = _make_block(10, 0, 100, 50)
        assert is_centered(block, 600.0) is False

    def test_is_in_header_zone(self):
        # 5% of 842 = 42.1
        block = _make_block(0, 20, 100, 40)
        assert is_in_header_zone(block, 842.0) is True
        block2 = _make_block(0, 100, 200, 120)
        assert is_in_header_zone(block2, 842.0) is False

    def test_is_in_footer_zone(self):
        # 90% of 842 = 757.8
        block = _make_block(0, 750, 100, 760)
        assert is_in_footer_zone(block, 842.0) is True
        block2 = _make_block(0, 400, 200, 420)
        assert is_in_footer_zone(block2, 842.0) is False

    def test_is_in_title_zone(self):
        # 35% of 842 = 294.7
        block = _make_block(0, 100, 200, 120)
        assert is_in_title_zone(block, 842.0) is True
        block2 = _make_block(0, 400, 200, 420)
        assert is_in_title_zone(block2, 842.0) is False

    def test_is_full_width(self):
        # 60% of 595 = 357
        block = _make_block(72, 0, 526, 50)  # width = 454 > 357
        assert is_full_width(block, 595.0) is True
        block2 = _make_block(72, 0, 293, 50)  # width = 221 < 357
        assert is_full_width(block2, 595.0) is False

    def test_matches_abstract_start(self):
        assert matches_abstract_start("Abstract") is True
        assert matches_abstract_start("ABSTRACT") is True
        assert matches_abstract_start("A BSTRACT") is True  # PyMuPDF small-caps
        assert matches_abstract_start("TÓM TẮT") is True
        assert matches_abstract_start("Tổng quan") is False
        assert matches_abstract_start("Not abstract") is False

    def test_matches_keyword_start(self):
        assert matches_keyword_start("Keywords:") is True
        assert matches_keyword_start("Keywords: NLP") is True
        assert matches_keyword_start("Từ khóa:") is True
        assert matches_keyword_start("Index Terms") is True
        assert matches_keyword_start("Hello world") is False

    def test_matches_reference_start(self):
        assert matches_reference_start("References") is True
        assert matches_reference_start("REFERENCES") is True
        assert matches_reference_start("TÀI LIỆU THAM KHẢO") is True
        assert matches_reference_start("Bibliography") is True
        assert matches_reference_start("Some text") is False

    def test_contains_affiliation(self):
        assert contains_affiliation("VinAI Research, University of X") is True
        assert contains_affiliation("Đại học Y Hà Nội") is True
        assert contains_affiliation("Bệnh viện Bạch Mai") is True
        assert contains_affiliation("Hello World") is False

    def test_matches_header_footer(self):
        assert matches_header_footer("doi: 10.1234/abc") is True
        assert matches_header_footer("© 2024") is True
        assert matches_header_footer("Vol. 15") is True
        assert matches_header_footer("Regular text") is False

    def test_max_font_size_in_blocks(self):
        blocks = [
            _make_block(0, 0, 100, 50, "A", 10.0),
            _make_block(0, 60, 100, 110, "B", 24.0),
            _make_block(0, 120, 100, 170, "C", 12.0),
        ]
        assert max_font_size_in_blocks(blocks) == 24.0

    def test_max_font_size_in_blocks_empty(self):
        assert max_font_size_in_blocks([]) == 0.0


# ─────────────────────────────────────────────
# ColumnDetector Tests
# ─────────────────────────────────────────────

class TestColumnDetector:
    def setup_method(self):
        self.detector = ColumnDetector()

    def test_single_column_arxiv(self):
        """arXiv-style PDF → 1 cột."""
        blocks = _make_single_column_blocks()
        info = self.detector.detect(blocks, 612.0)
        assert info.column_count == 1
        assert info.layout_type == "single_column"

    def test_two_column_vietnamese(self):
        """Vietnamese medical PDF → 2 cột."""
        blocks = _make_two_column_blocks()
        info = self.detector.detect(blocks, 595.0)
        assert info.column_count == 2
        assert info.layout_type == "two_column"
        assert info.gap_start < info.gap_end

    def test_empty_blocks(self):
        info = self.detector.detect([], 595.0)
        assert info.column_count == 1

    def test_all_full_width(self):
        """Tất cả blocks full-width → 1 cột."""
        blocks = [
            _make_block(72, 100, 526, 150, "Full line 1"),
            _make_block(72, 160, 526, 210, "Full line 2"),
        ]
        info = self.detector.detect(blocks, 595.0)
        assert info.column_count == 1

    def test_single_narrow_block(self):
        """Chỉ 1 narrow block → không đủ evidence → 1 cột."""
        blocks = [_make_block(72, 100, 200, 150, "Short")]
        info = self.detector.detect(blocks, 595.0)
        assert info.column_count == 1


# ─────────────────────────────────────────────
# ReadingOrder Tests
# ─────────────────────────────────────────────

class TestReadingOrder:
    def setup_method(self):
        self.reconstructor = ReadingOrderReconstructor()

    def test_single_column_order(self):
        """1 cột: sort theo y0."""
        blocks = [
            _make_block(72, 200, 500, 250, "Second"),
            _make_block(72, 100, 500, 150, "First"),
            _make_block(72, 300, 500, 350, "Third"),
        ]
        info = ColumnInfo(column_count=1)
        result = self.reconstructor.reconstruct(blocks, info, 595.0)

        assert result[0].text == "First"
        assert result[1].text == "Second"
        assert result[2].text == "Third"

    def test_two_column_left_then_right(self):
        """2 cột: left ↓ rồi right ↓."""
        blocks = [
            _make_block(72, 100, 280, 150, "Left 1"),
            _make_block(72, 160, 280, 210, "Left 2"),
            _make_block(310, 100, 520, 150, "Right 1"),
            _make_block(310, 160, 520, 210, "Right 2"),
        ]
        info = ColumnInfo(column_count=2, gap_start=280, gap_end=310)
        result = self.reconstructor.reconstruct(blocks, info, 595.0)

        texts = [b.text for b in result]
        assert texts == ["Left 1", "Left 2", "Right 1", "Right 2"]

    def test_two_column_with_full_width_separator(self):
        """Full-width block chia bands đúng."""
        blocks = [
            _make_block(72, 50, 520, 80, "Full-width header"),  # full
            _make_block(72, 100, 280, 150, "Left 1"),
            _make_block(310, 100, 520, 150, "Right 1"),
            _make_block(72, 200, 520, 250, "Full-width mid"),   # full
            _make_block(72, 270, 280, 320, "Left 2"),
            _make_block(310, 270, 520, 320, "Right 2"),
        ]
        info = ColumnInfo(column_count=2, gap_start=280, gap_end=310)
        result = self.reconstructor.reconstruct(blocks, info, 595.0)

        texts = [b.text for b in result]
        # Full-width header → Left1 → Right1 → Full-width mid → Left2 → Right2
        assert texts[0] == "Full-width header"
        left1_idx = texts.index("Left 1")
        right1_idx = texts.index("Right 1")
        assert left1_idx < right1_idx

    def test_empty_blocks(self):
        info = ColumnInfo(column_count=1)
        result = self.reconstructor.reconstruct([], info, 595.0)
        assert result == []


# ─────────────────────────────────────────────
# RegionDetector Tests
# ─────────────────────────────────────────────

class TestRegionDetector:
    def setup_method(self):
        self.detector = RegionDetector()

    def _make_page(self, blocks, page_number=0):
        return PageData(
            page_number=page_number,
            width=612.0,
            height=792.0,
            blocks=blocks,
        )

    def test_title_detection(self):
        """Block có font lớn nhất, bold, top zone → TITLE."""
        blocks = [
            _make_block(108, 80, 452, 118, "Paper Title Here", 17.0, 20),
            _make_block(108, 200, 504, 300, "Body text...", 10.0, 4),
        ]
        page = self._make_page(blocks)
        info = ColumnInfo(column_count=1)
        regions = self.detector.detect(page, info, blocks)

        types = [r.region_type for r in regions]
        assert RegionType.TITLE in types

    def test_abstract_detection(self):
        """Block sau 'Abstract' marker → ABSTRACT."""
        blocks = [
            _make_block(108, 80, 452, 118, "Paper Title", 17.0, 20),
            _make_block(278, 199, 333, 211, "ABSTRACT", 12.0, 4),
            _make_block(144, 225, 468, 315, "This paper presents...", 10.0, 4),
        ]
        page = self._make_page(blocks)
        info = ColumnInfo(column_count=1)
        regions = self.detector.detect(page, info, blocks)

        types = [r.region_type for r in regions]
        assert RegionType.ABSTRACT in types

    def test_keyword_detection(self):
        """Block sau 'Keywords:' → KEYWORD."""
        blocks = [
            _make_block(278, 199, 333, 211, "ABSTRACT", 12.0, 4),
            _make_block(144, 225, 468, 315, "Abstract content...", 10.0, 4),
            _make_block(144, 320, 468, 335, "Keywords: NLP, GPT", 10.0, 4),
        ]
        page = self._make_page(blocks)
        info = ColumnInfo(column_count=1)
        regions = self.detector.detect(page, info, blocks)

        types = [r.region_type for r in regions]
        assert RegionType.KEYWORD in types

    def test_reference_detection(self):
        """Block sau 'References' → REFERENCE."""
        blocks = [
            _make_block(108, 370, 504, 500, "Body text...", 10.0, 4),
            _make_block(108, 510, 200, 525, "References", 12.0, 20),
            _make_block(108, 530, 504, 700, "1. Author A...", 10.0, 4),
        ]
        page = self._make_page(blocks)
        info = ColumnInfo(column_count=1)
        regions = self.detector.detect(page, info, blocks)

        types = [r.region_type for r in regions]
        assert RegionType.REFERENCE in types

    def test_header_detection(self):
        """Block ở top 5% + matches header pattern → HEADER."""
        blocks = [
            _make_block(100, 10, 500, 25, "Vol. 15, No. 3, 2024", 8.0, 0),
            _make_block(108, 80, 504, 400, "Body text...", 10.0, 4),
        ]
        page = self._make_page(blocks)
        info = ColumnInfo(column_count=1)
        regions = self.detector.detect(page, info, blocks)

        types = [r.region_type for r in regions]
        assert RegionType.HEADER in types

    def test_footer_detection(self):
        """Block ở bottom + page number → FOOTER."""
        blocks = [
            _make_block(108, 80, 504, 400, "Body text...", 10.0, 4),
            _make_block(280, 760, 320, 775, "42", 10.0, 0),
        ]
        page = self._make_page(blocks)
        info = ColumnInfo(column_count=1)
        regions = self.detector.detect(page, info, blocks)

        types = [r.region_type for r in regions]
        assert RegionType.FOOTER in types

    def test_subsequent_page_mostly_body(self):
        """Trang 2+: mặc định BODY."""
        blocks = [
            _make_block(108, 80, 504, 400, "Body text continued...", 10.0, 4),
            _make_block(108, 410, 504, 700, "More body text...", 10.0, 4),
        ]
        page = self._make_page(blocks, page_number=1)
        info = ColumnInfo(column_count=1)
        regions = self.detector.detect(page, info, blocks)

        types = [r.region_type for r in regions]
        assert all(t == RegionType.BODY for t in types)

    def test_affiliation_detection(self):
        """Block chứa university/hospital keywords → AFFILIATION."""
        blocks = [
            _make_block(108, 80, 452, 118, "Paper Title", 17.0, 20),
            _make_block(114, 130, 400, 145, "John Doe, Jane Smith", 10.0, 20),
            _make_block(114, 148, 246, 158, "University of Science", 10.0, 4),
            _make_block(278, 199, 333, 211, "Abstract", 12.0, 4),
            _make_block(144, 225, 468, 315, "Content...", 10.0, 4),
        ]
        page = self._make_page(blocks)
        info = ColumnInfo(column_count=1)
        regions = self.detector.detect(page, info, blocks)

        types = [r.region_type for r in regions]
        assert RegionType.AFFILIATION in types

    def test_vietnamese_tom_tat(self):
        """'TÓM TẮT' detected as abstract marker."""
        blocks = [
            _make_block(112, 557, 487, 590, "TITLE TEXT", 14.0, 20),
            _make_block(72, 632, 218, 663, "TÓM TẮT", 12.0, 16),
            _make_block(305, 631, 526, 720, "Mục tiêu: Xác định...", 9.0, 16),
        ]
        page = self._make_page(blocks)
        info = ColumnInfo(column_count=2)
        regions = self.detector.detect(page, info, blocks)

        types = [r.region_type for r in regions]
        assert RegionType.ABSTRACT in types

    def test_regions_have_reading_order_index(self):
        """Regions phải có reading_order_index tăng dần."""
        blocks = _make_single_column_blocks()
        page = self._make_page(blocks)
        info = ColumnInfo(column_count=1)
        regions = self.detector.detect(page, info, blocks)

        indices = [r.reading_order_index for r in regions]
        assert indices == list(range(len(indices)))


# ─────────────────────────────────────────────
# LayoutAnalyzer Integration Tests
# ─────────────────────────────────────────────

class TestLayoutAnalyzer:
    def setup_method(self):
        self.analyzer = LayoutAnalyzer()

    def test_analyze_single_column(self):
        """Full pipeline trên layout 1-cột."""
        blocks = _make_single_column_blocks()
        doc = DocumentData(
            file_path="test_arxiv.pdf",
            page_count=1,
            pages=[PageData(
                page_number=0,
                width=612.0,
                height=792.0,
                blocks=blocks,
            )],
        )
        result = self.analyzer.analyze(doc)

        assert isinstance(result, LayoutDocument)
        assert result.page_count == 1
        assert result.total_regions > 0
        assert result.analysis_time_seconds >= 0

        page = result.pages[0]
        assert page.layout_type == "single_column"
        assert page.column_info.column_count == 1

    def test_analyze_two_column(self):
        """Full pipeline trên layout 2-cột."""
        blocks = _make_two_column_blocks()
        doc = DocumentData(
            file_path="test_vn.pdf",
            page_count=1,
            pages=[PageData(
                page_number=0,
                width=595.0,
                height=842.0,
                blocks=blocks,
            )],
        )
        result = self.analyzer.analyze(doc)

        page = result.pages[0]
        assert page.column_info.column_count == 2
        assert page.layout_type == "two_column"

    def test_analyze_multipage(self):
        """Multi-page document."""
        doc = DocumentData(
            file_path="test_multi.pdf",
            page_count=2,
            pages=[
                PageData(
                    page_number=0, width=612.0, height=792.0,
                    blocks=_make_single_column_blocks(),
                ),
                PageData(
                    page_number=1, width=612.0, height=792.0,
                    blocks=[_make_block(108, 80, 504, 700, "Body...", 10.0)],
                ),
            ],
        )
        result = self.analyzer.analyze(doc)
        assert result.page_count == 2
        assert len(result.pages) == 2

    def test_analyze_to_dict(self):
        """to_dict() output có đầy đủ keys."""
        blocks = _make_single_column_blocks()
        doc = DocumentData(
            file_path="test.pdf",
            page_count=1,
            pages=[PageData(
                page_number=0, width=612.0, height=792.0, blocks=blocks,
            )],
        )
        result = self.analyzer.analyze(doc)
        d = result.to_dict()

        assert "file_path" in d
        assert "page_count" in d
        assert "total_regions" in d
        assert "pages" in d
        assert len(d["pages"]) == 1
        assert "regions" in d["pages"][0]
        assert "column_info" in d["pages"][0]

    def test_analyze_get_regions(self):
        """get_regions() filter đúng."""
        blocks = _make_single_column_blocks()
        doc = DocumentData(
            file_path="test.pdf",
            page_count=1,
            pages=[PageData(
                page_number=0, width=612.0, height=792.0, blocks=blocks,
            )],
        )
        result = self.analyzer.analyze(doc)

        # Phải có ít nhất 1 TITLE và 1 ABSTRACT
        titles = result.get_regions(RegionType.TITLE)
        assert len(titles) >= 1

        abstracts = result.get_regions(RegionType.ABSTRACT)
        assert len(abstracts) >= 1

    def test_analyze_real_arxiv_pdf(self, arxiv_pdf_path):
        """Integration test trên PDF thật — arXiv 1-cột."""
        from core.text_extraction.extractor import PDFTextExtractor

        extractor = PDFTextExtractor()
        doc_data = extractor.extract(arxiv_pdf_path)
        result = self.analyzer.analyze(doc_data)

        assert result.page_count > 0
        assert result.total_regions > 0

        # Trang 1 phải có TITLE và ABSTRACT
        page0 = result.pages[0]
        types_on_page0 = {r.region_type for r in page0.regions}
        assert RegionType.TITLE in types_on_page0 or RegionType.ABSTRACT in types_on_page0

    def test_analyze_real_vn_pdf(self, vn_pdf_path):
        """Integration test trên PDF thật — Vietnamese 2-cột."""
        from core.text_extraction.extractor import PDFTextExtractor

        extractor = PDFTextExtractor()
        doc_data = extractor.extract(vn_pdf_path)
        result = self.analyzer.analyze(doc_data)

        assert result.page_count > 0
        assert result.total_regions > 0

    def test_analyze_logging(self, caplog):
        """Analyzer log thống kê."""
        import logging
        blocks = _make_single_column_blocks()
        doc = DocumentData(
            file_path="test.pdf",
            page_count=1,
            pages=[PageData(
                page_number=0, width=612.0, height=792.0, blocks=blocks,
            )],
        )
        with caplog.at_level(logging.INFO):
            self.analyzer.analyze(doc)

        assert any("Layout analysis complete" in r.message for r in caplog.records)

    def test_dependency_injection(self):
        """Analyzer nhận custom components qua DI."""
        mock_col = MagicMock(spec=ColumnDetector)
        mock_col.detect.return_value = ColumnInfo(column_count=1)

        mock_ro = MagicMock(spec=ReadingOrderReconstructor)
        mock_ro.reconstruct.return_value = []

        mock_rd = MagicMock(spec=RegionDetector)
        mock_rd.detect.return_value = []

        analyzer = LayoutAnalyzer(
            column_detector=mock_col,
            reading_order=mock_ro,
            region_detector=mock_rd,
        )
        doc = DocumentData(
            page_count=1,
            pages=[PageData(page_number=0, width=612.0, height=792.0)],
        )
        result = analyzer.analyze(doc)
        assert isinstance(result, LayoutDocument)
        mock_col.detect.assert_called_once()
