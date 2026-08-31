"""
tests/test_title_detection.py
Unit tests cho Milestone 4 — Title Detection.

Bao gồm:
- Tests cho rules (plausibility, noise detection, capitalization)
- Tests cho scorer (individual features + integrated scoring)
- Tests cho detector (3 strategies + edge cases)
- Tests trên PDF thật (integration tests)
"""

import sys
from pathlib import Path

import pytest

# Đảm bảo import đúng
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from core.text_extraction.models import BlockData, LineData, SpanData, PageData
from core.layout_analysis.layout_model import (
    LayoutDocument,
    LayoutPage,
    Region,
    RegionType,
    ColumnInfo,
)
from core.title_detection.models import TitleCandidate, TitleResult
from core.title_detection.rules import (
    is_plausible_title,
    is_noise,
    is_title_case,
    is_all_upper,
    MAX_TOTAL_SCORE,
)
from core.title_detection.scorer import TitleScorer
from core.title_detection.detector import TitleDetector
from core.title_detection.service import TitleDetectionService
from core.title_detection.exceptions import TitleDetectionError


# ─────────────────────────────────────────────
# Test Helpers — tạo mock data
# ─────────────────────────────────────────────

def make_span(text: str, font_size: float = 10.0, font_name: str = "Arial",
              font_flags: int = 0, bbox: tuple = (0, 0, 100, 12)) -> SpanData:
    """Tạo SpanData đơn giản."""
    return SpanData(
        text=text,
        font_name=font_name,
        font_size=font_size,
        font_flags=font_flags,
        bbox=bbox,
    )


def make_block(text: str, bbox: tuple = (50, 50, 500, 70),
               font_size: float = 10.0, font_name: str = "Arial",
               font_flags: int = 0) -> BlockData:
    """Tạo BlockData với một line và một span."""
    span = make_span(text, font_size, font_name, font_flags,
                     bbox=bbox)
    line = LineData(bbox=bbox, spans=[span])
    return BlockData(bbox=bbox, block_type=0, block_number=0, lines=[line])


def make_region(text: str, region_type: RegionType,
                bbox: tuple = (50, 50, 500, 70),
                font_size: float = 10.0, font_name: str = "Arial",
                font_flags: int = 0, confidence: float = 0.8,
                page_number: int = 0) -> Region:
    """Tạo Region với một block."""
    block = make_block(text, bbox, font_size, font_name, font_flags)
    return Region(
        region_type=region_type,
        blocks=[block],
        page_number=page_number,
        reading_order_index=0,
        confidence=confidence,
    )


def make_layout_page(regions: list[Region], page_number: int = 0,
                     width: float = 612.0, height: float = 792.0) -> LayoutPage:
    """Tạo LayoutPage với danh sách regions."""
    return LayoutPage(
        page_number=page_number,
        width=width,
        height=height,
        regions=regions,
        column_info=ColumnInfo(),
    )


def make_layout_doc(pages: list[LayoutPage],
                    file_path: str = "test.pdf") -> LayoutDocument:
    """Tạo LayoutDocument với danh sách pages."""
    total_regions = sum(len(p.regions) for p in pages)
    return LayoutDocument(
        file_path=file_path,
        page_count=len(pages),
        pages=pages,
        total_regions=total_regions,
    )


def make_simple_doc_with_title(
    title_text: str = "Paper Title",
    title_font_size: float = 20.0,
    title_bbox: tuple = (100, 80, 500, 110),
    author_text: str = "John Doe",
    abstract_text: str = "This is the abstract of the paper...",
    body_text: str = "This is the body text of the paper.",
) -> LayoutDocument:
    """Tạo LayoutDocument đơn giản với TITLE, AUTHOR, ABSTRACT, BODY."""
    regions = [
        make_region(title_text, RegionType.TITLE,
                    bbox=title_bbox, font_size=title_font_size,
                    font_name="Arial-Bold", font_flags=16),
        make_region(author_text, RegionType.AUTHOR,
                    bbox=(100, 120, 500, 140), font_size=12.0),
        make_region(abstract_text, RegionType.ABSTRACT,
                    bbox=(50, 160, 560, 300), font_size=10.0),
        make_region(body_text, RegionType.BODY,
                    bbox=(50, 320, 560, 700), font_size=10.0),
    ]
    page = make_layout_page(regions)
    return make_layout_doc([page])


# ═══════════════════════════════════════════════
# Tests: Rules (rules.py)
# ═══════════════════════════════════════════════

class TestIsPlausibleTitle:
    """Tests cho is_plausible_title()."""

    def test_valid_title(self):
        """Title hợp lệ → True."""
        assert is_plausible_title("A Novel Approach to Named Entity Recognition") is True

    def test_rejects_short(self):
        """Title < 5 ký tự → False."""
        assert is_plausible_title("AB") is False
        assert is_plausible_title("Hi") is False

    def test_rejects_empty(self):
        """Empty string → False."""
        assert is_plausible_title("") is False

    def test_rejects_pure_digits(self):
        """Chỉ chứa digits → False."""
        assert is_plausible_title("12345") is False

    def test_rejects_no_alpha(self):
        """Không có ký tự alphabetic → False."""
        assert is_plausible_title("12345 ### @@@") is False

    def test_rejects_noise_doi(self):
        """DOI pattern → False (bị noise filter)."""
        assert is_plausible_title("doi: 10.1234/abcdef") is False

    def test_rejects_noise_copyright(self):
        """Copyright pattern → False."""
        assert is_plausible_title("© 2024 IEEE") is False

    def test_accepts_long_title(self):
        """Title dài nhưng hợp lệ → True."""
        title = "A " * 100 + "Study"
        if len(title.strip()) <= 350:
            assert is_plausible_title(title) is True

    def test_rejects_too_long(self):
        """Title > 350 chars → False."""
        title = "A" * 351
        assert is_plausible_title(title) is False


class TestIsNoise:
    """Tests cho is_noise()."""

    def test_doi_pattern(self):
        """DOI → True."""
        assert is_noise("doi: 10.1234/some.thing") is True

    def test_copyright(self):
        """© → True."""
        assert is_noise("© 2024 IEEE") is True

    def test_page_number(self):
        """Chỉ số trang → True."""
        assert is_noise("42") is True

    def test_issn(self):
        """ISSN → True."""
        assert is_noise("ISSN 1234-5678") is True

    def test_arxiv_id(self):
        """arXiv ID → True."""
        assert is_noise("arXiv: 2311.02945") is True

    def test_proceedings(self):
        """Proceedings header → True."""
        assert is_noise("Proceedings of the 2024 Conference") is True

    def test_normal_title_not_noise(self):
        """Title bình thường → False."""
        assert is_noise("PhoGPT: Generative Pre-training for Vietnamese") is False

    def test_url_noise(self):
        """URL → True."""
        assert is_noise("https://arxiv.org/abs/2311.02945") is True


class TestCapitalization:
    """Tests cho is_title_case() và is_all_upper()."""

    def test_title_case(self):
        """Title Case → True."""
        assert is_title_case("A Novel Approach to NER") is True

    def test_title_case_with_stopwords(self):
        """Title Case với stop words → True."""
        assert is_title_case("The Impact of Deep Learning on NLP") is True

    def test_not_title_case(self):
        """All lowercase → False."""
        assert is_title_case("a novel approach to ner") is False

    def test_all_upper(self):
        """ALL CAPS → True."""
        assert is_all_upper("DEEP LEARNING FOR NLP") is True

    def test_not_all_upper(self):
        """Mixed case → False."""
        assert is_all_upper("Deep Learning for NLP") is False

    def test_all_upper_with_numbers(self):
        """ALL CAPS với numbers → True."""
        assert is_all_upper("BERT4NER: A STUDY IN 2024") is True


# ═══════════════════════════════════════════════
# Tests: Scorer (scorer.py)
# ═══════════════════════════════════════════════

class TestTitleScorer:
    """Tests cho TitleScorer."""

    def setup_method(self):
        self.scorer = TitleScorer()

    def test_high_score_ideal_title(self):
        """Title lý tưởng → score > 7.0."""
        candidate = TitleCandidate(
            text="A Novel Approach to Named Entity Recognition",
            bbox=(100, 80, 500, 110),
            page_number=0,
            font_size=20.0,
            font_flags=16,  # bold
            font_name="Arial-Bold",
            is_bold=True,
            is_centered=True,
            relative_y=0.10,
            page_width=612.0,
            page_height=792.0,
            line_count=1,
            max_font_size=20.0,
            author_region_y=120.0,
            abstract_region_y=160.0,
        )

        score = self.scorer.score(candidate)
        assert score > 7.0, f"Expected > 7.0, got {score}"
        assert candidate.score == score
        assert len(candidate.score_breakdown) == 10

    def test_low_score_noise(self):
        """Noise text → score < 3.0."""
        candidate = TitleCandidate(
            text="42",
            bbox=(50, 700, 100, 712),
            page_number=0,
            font_size=8.0,
            font_flags=0,
            font_name="TimesNewRoman",
            is_bold=False,
            is_centered=False,
            relative_y=0.90,
            page_width=612.0,
            page_height=792.0,
            line_count=1,
            max_font_size=20.0,
            author_region_y=120.0,
            abstract_region_y=160.0,
        )

        score = self.scorer.score(candidate)
        assert score < 3.0, f"Expected < 3.0, got {score}"

    def test_font_size_ratio(self):
        """Font size = max → score = WEIGHT_FONT_SIZE (2.0)."""
        candidate = TitleCandidate(
            font_size=20.0,
            max_font_size=20.0,
            text="Title",
            bbox=(0, 0, 100, 20),
        )
        score = self.scorer._score_font_size(candidate)
        assert score == pytest.approx(2.0)

    def test_font_size_half(self):
        """Font size = 50% max → score = 1.0."""
        candidate = TitleCandidate(
            font_size=10.0,
            max_font_size=20.0,
            text="Title",
            bbox=(0, 0, 100, 20),
        )
        score = self.scorer._score_font_size(candidate)
        assert score == pytest.approx(1.0)

    def test_bold_true(self):
        """Bold → 1.0."""
        candidate = TitleCandidate(is_bold=True, text="Title", bbox=(0, 0, 100, 20))
        assert self.scorer._score_bold(candidate) == 1.0

    def test_bold_false(self):
        """Not bold → 0.0."""
        candidate = TitleCandidate(is_bold=False, text="Title", bbox=(0, 0, 100, 20))
        assert self.scorer._score_bold(candidate) == 0.0

    def test_position_top(self):
        """Top of page (y=0) → full position score."""
        candidate = TitleCandidate(
            relative_y=0.0, text="Title", bbox=(0, 0, 100, 20)
        )
        score = self.scorer._score_position(candidate)
        assert score == pytest.approx(1.5)

    def test_position_bottom(self):
        """Bottom (y > 0.35) → 0."""
        candidate = TitleCandidate(
            relative_y=0.50, text="Title", bbox=(0, 0, 100, 20)
        )
        score = self.scorer._score_position(candidate)
        assert score == 0.0

    def test_line_count_ideal(self):
        """1-3 lines → full score."""
        candidate = TitleCandidate(line_count=2, text="Title", bbox=(0, 0, 100, 20))
        assert self.scorer._score_line_count(candidate) == 0.5

    def test_line_count_too_many(self):
        """> 5 lines → 0."""
        candidate = TitleCandidate(line_count=8, text="Title", bbox=(0, 0, 100, 20))
        assert self.scorer._score_line_count(candidate) == 0.0

    def test_title_length_ideal(self):
        """10-200 chars → full score."""
        candidate = TitleCandidate(
            text="A Novel Approach to Named Entity Recognition",
            bbox=(0, 0, 100, 20),
        )
        assert self.scorer._score_title_length(candidate) == 1.0

    def test_title_length_too_short(self):
        """< 5 chars → 0."""
        candidate = TitleCandidate(text="Hi", bbox=(0, 0, 100, 20))
        assert self.scorer._score_title_length(candidate) == 0.0

    def test_capitalization_title_case(self):
        """Title Case → full cap score."""
        candidate = TitleCandidate(
            text="A Novel Approach to NER",
            bbox=(0, 0, 100, 20),
        )
        assert self.scorer._score_capitalization(candidate) == 0.5

    def test_capitalization_all_upper(self):
        """ALL CAPS → full cap score."""
        candidate = TitleCandidate(
            text="DEEP LEARNING FOR NLP",
            bbox=(0, 0, 100, 20),
        )
        assert self.scorer._score_capitalization(candidate) == 0.5


# ═══════════════════════════════════════════════
# Tests: Detector (detector.py)
# ═══════════════════════════════════════════════

class TestTitleDetector:
    """Tests cho TitleDetector — 3 strategies."""

    def setup_method(self):
        self.detector = TitleDetector()

    def test_detect_title_from_zone(self):
        """Strategy 1: Document có TITLE region → đúng text."""
        doc = make_simple_doc_with_title(title_text="Paper Title")
        result = self.detector.detect(doc)

        assert result.title == "Paper Title"
        assert result.strategy == "zone_based"
        assert result.confidence >= 0.85
        assert result.page == 0

    def test_detect_title_multiblock(self):
        """Strategy 1: 2 TITLE blocks liên tiếp → merge thành 1 chuỗi."""
        title_block_1 = make_block(
            "A Novel Approach to",
            bbox=(100, 80, 500, 100),
            font_size=20.0, font_flags=16,
        )
        title_block_2 = make_block(
            "Named Entity Recognition",
            bbox=(100, 100, 500, 120),
            font_size=20.0, font_flags=16,
        )
        title_region = Region(
            region_type=RegionType.TITLE,
            blocks=[title_block_1, title_block_2],
            page_number=0,
            reading_order_index=0,
            confidence=0.80,
        )
        author_region = make_region("John Doe", RegionType.AUTHOR,
                                    bbox=(100, 130, 500, 150))
        abstract_region = make_region(
            "This paper presents a novel approach...",
            RegionType.ABSTRACT,
            bbox=(50, 170, 560, 300),
        )

        page = make_layout_page([title_region, author_region, abstract_region])
        doc = make_layout_doc([page])

        result = self.detector.detect(doc)
        assert "Novel Approach" in result.title
        assert "Named Entity Recognition" in result.title
        assert result.strategy == "zone_based"

    def test_detect_fallback_max_font(self):
        """Strategy 2: Không có TITLE zone, block font lớn nhất → title."""
        # Tạo page chỉ có BODY regions, nhưng block đầu có font lớn
        big_font_block = make_block(
            "Paper Title Here",
            bbox=(100, 80, 500, 110),
            font_size=20.0, font_flags=16,
        )
        body_block = make_block(
            "This is body text with normal font.",
            bbox=(50, 200, 560, 220),
            font_size=10.0,
        )
        # Assign ALL regions as BODY so no TITLE zone exists
        region1 = Region(
            region_type=RegionType.BODY,
            blocks=[big_font_block],
            page_number=0,
            reading_order_index=0,
            confidence=0.65,
        )
        region2 = Region(
            region_type=RegionType.BODY,
            blocks=[body_block],
            page_number=0,
            reading_order_index=1,
            confidence=0.65,
        )

        page = make_layout_page([region1, region2])
        doc = make_layout_doc([page])

        result = self.detector.detect(doc)
        assert result.title is not None
        assert "Paper Title Here" in result.title
        assert result.strategy == "font_based"
        assert result.confidence >= 0.60

    def test_detect_fallback_first_line(self):
        """Strategy 3: Không có font lớn, lấy dòng đầu."""
        # Tất cả blocks có cùng font size nhỏ, không có noise
        block1 = make_block(
            "Machine Learning for NLP",
            bbox=(50, 50, 560, 65),
            font_size=10.0,
        )
        block2 = make_block(
            "This is some body text here.",
            bbox=(50, 80, 560, 95),
            font_size=10.0,
        )
        region1 = Region(
            region_type=RegionType.BODY,
            blocks=[block1],
            page_number=0,
            reading_order_index=0,
            confidence=0.65,
        )
        region2 = Region(
            region_type=RegionType.BODY,
            blocks=[block2],
            page_number=0,
            reading_order_index=1,
            confidence=0.65,
        )

        page = make_layout_page([region1, region2])
        doc = make_layout_doc([page])

        result = self.detector.detect(doc)
        assert result.title is not None
        # Nên lấy dòng đầu hoặc block font lớn nhất
        assert result.title is not None

    def test_detect_none_empty_doc(self):
        """Document rỗng → title = None."""
        doc = LayoutDocument(file_path="empty.pdf", page_count=0, pages=[])
        result = self.detector.detect(doc)
        assert result.title is None

    def test_detect_empty_page(self):
        """Trang rỗng → title = None."""
        page = make_layout_page(regions=[], page_number=0)
        doc = make_layout_doc([page])
        result = self.detector.detect(doc)
        assert result.title is None

    def test_detect_skips_noise_blocks(self):
        """Blocks noise (DOI, ©) bị bỏ qua."""
        noise_block = make_block(
            "doi: 10.1234/abcdef",
            bbox=(50, 50, 560, 65),
            font_size=20.0,
        )
        title_block = make_block(
            "Real Paper Title",
            bbox=(50, 80, 560, 100),
            font_size=18.0,
            font_flags=16,
        )
        region1 = Region(
            region_type=RegionType.BODY,
            blocks=[noise_block],
            page_number=0,
            reading_order_index=0,
            confidence=0.65,
        )
        region2 = Region(
            region_type=RegionType.BODY,
            blocks=[title_block],
            page_number=0,
            reading_order_index=1,
            confidence=0.65,
        )
        page = make_layout_page([region1, region2])
        doc = make_layout_doc([page])

        result = self.detector.detect(doc)
        assert result.title is not None
        assert "Real Paper Title" in result.title


# ═══════════════════════════════════════════════
# Tests: TitleResult model
# ═══════════════════════════════════════════════

class TestTitleResult:
    """Tests cho TitleResult dataclass."""

    def test_to_dict(self):
        """to_dict() trả về dict đúng format."""
        result = TitleResult(
            title="Test Title",
            confidence=0.95,
            bbox=[100, 80, 500, 110],
            page=0,
            strategy="zone_based",
            raw_score=8.5,
        )
        d = result.to_dict()
        assert d["title"] == "Test Title"
        assert d["confidence"] == 0.95
        assert d["page"] == 0
        assert d["strategy"] == "zone_based"
        assert d["raw_score"] == 8.5
        assert len(d["bbox"]) == 4

    def test_to_dict_none_title(self):
        """to_dict() với title=None."""
        result = TitleResult(title=None)
        d = result.to_dict()
        assert d["title"] is None


# ═══════════════════════════════════════════════
# Tests: Service
# ═══════════════════════════════════════════════

class TestTitleDetectionService:
    """Tests cho TitleDetectionService."""

    def test_service_detect(self):
        """Service wrapper hoạt động đúng."""
        service = TitleDetectionService()
        doc = make_simple_doc_with_title(title_text="Service Test Title")
        result = service.detect_title(doc)
        assert result.title == "Service Test Title"
        assert result.confidence > 0

    def test_service_empty_doc(self):
        """Service xử lý document rỗng."""
        service = TitleDetectionService()
        doc = LayoutDocument(file_path="empty.pdf", page_count=0, pages=[])
        result = service.detect_title(doc)
        assert result.title is None


# ═══════════════════════════════════════════════
# Tests: Integration — Real PDF (nếu có)
# ═══════════════════════════════════════════════

_PARENT_DIR = Path(__file__).resolve().parent.parent.parent
_SAMPLE_PDFS = {
    "naacl": _PARENT_DIR / "2024.naacl-long.461.pdf",
    "phogpt": _PARENT_DIR / "2311.02945v3.pdf",
    "ccpdf": _PARENT_DIR / "2304.14953v2.pdf",
}


def _extract_and_analyze(pdf_path: str) -> LayoutDocument:
    """Helper: Extract text → Layout analysis → return LayoutDocument."""
    from core.text_extraction.extractor import PDFTextExtractor
    from core.layout_analysis.layout_analyzer import LayoutAnalyzer

    extractor = PDFTextExtractor()
    doc_data = extractor.extract(pdf_path)
    analyzer = LayoutAnalyzer()
    return analyzer.analyze(doc_data)


@pytest.mark.skipif(
    not _SAMPLE_PDFS["phogpt"].exists(),
    reason="Sample PDF 2311.02945v3.pdf not found"
)
class TestRealPDFPhoGPT:
    """Integration test trên 2311.02945v3.pdf (arXiv format)."""

    def test_title_contains_phogpt(self):
        """Title phải chứa 'PhoGPT'."""
        layout_doc = _extract_and_analyze(str(_SAMPLE_PDFS["phogpt"]))
        detector = TitleDetector()
        result = detector.detect(layout_doc)

        assert result.title is not None, "Title should not be None"
        assert "PhoGPT" in result.title, (
            f"Expected 'PhoGPT' in title, got: {result.title!r}"
        )
        # PhoGPT PDF: title block ở y=27.8 (header zone), Layout Analysis
        # classify là BODY → first_line strategy (confidence range 0.30–0.55)
        assert result.confidence > 0.3
        assert result.page == 0

    def test_title_confidence_reasonable(self):
        """Confidence phải > 0 (title được tìm thấy)."""
        layout_doc = _extract_and_analyze(str(_SAMPLE_PDFS["phogpt"]))
        service = TitleDetectionService()
        result = service.detect_title(layout_doc)

        # first_line strategy có confidence range [0.30, 0.55]
        assert result.confidence > 0.3
        assert result.title is not None


@pytest.mark.skipif(
    not _SAMPLE_PDFS["naacl"].exists(),
    reason="Sample PDF 2024.naacl-long.461.pdf not found"
)
class TestRealPDFNaacl:
    """Integration test trên 2024.naacl-long.461.pdf (conference format)."""

    def test_title_contains_cner(self):
        """Title phải chứa 'CNER' (hoặc liên quan)."""
        layout_doc = _extract_and_analyze(str(_SAMPLE_PDFS["naacl"]))
        detector = TitleDetector()
        result = detector.detect(layout_doc)

        assert result.title is not None, "Title should not be None"
        # Title có thể là "CNER: ..." hoặc tương tự
        title_upper = result.title.upper()
        assert "CNER" in title_upper or "NAMED ENTITY" in title_upper, (
            f"Expected 'CNER' or 'NAMED ENTITY' in title, got: {result.title!r}"
        )


@pytest.mark.skipif(
    not _SAMPLE_PDFS["ccpdf"].exists(),
    reason="Sample PDF 2304.14953v2.pdf not found"
)
class TestRealPDFCcpdf:
    """Integration test trên 2304.14953v2.pdf."""

    def test_title_contains_ccpdf(self):
        """Title phải chứa 'CCpdf'."""
        layout_doc = _extract_and_analyze(str(_SAMPLE_PDFS["ccpdf"]))
        detector = TitleDetector()
        result = detector.detect(layout_doc)

        assert result.title is not None, "Title should not be None"
        title_upper = result.title.upper()
        assert "CCPDF" in title_upper, (
            f"Expected 'CCPDF' in title, got: {result.title!r}"
        )
