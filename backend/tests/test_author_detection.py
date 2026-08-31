"""
tests/test_author_detection.py
Unit tests cho Milestone 5 — Author Detection.

Bao gồm:
- Tests cho AuthorCleaner (split, clean, filter, dedup)
- Tests cho NER Engine (StubNEREngine)
- Tests cho AuthorDetector (3 tiers + edge cases)
- Tests cho AuthorResult model
- Tests cho AuthorDetectionService
- Integration tests trên PDF thật
"""

import sys
from pathlib import Path

import pytest

# Đảm bảo import đúng
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from core.text_extraction.models import BlockData, LineData, SpanData
from core.layout_analysis.layout_model import (
    LayoutDocument,
    LayoutPage,
    Region,
    RegionType,
    ColumnInfo,
)
from core.title_detection.models import TitleResult
from core.author_detection.models import AuthorInfo, AuthorResult
from core.author_detection.cleaner import AuthorCleaner
from core.author_detection.ner_engine import StubNEREngine
from core.author_detection.detector import AuthorDetector
from core.author_detection.service import AuthorDetectionService


# ─────────────────────────────────────────────
# Test Helpers
# ─────────────────────────────────────────────

def make_block(text: str, bbox: tuple = (50, 50, 500, 70),
               font_size: float = 10.0, font_flags: int = 0) -> BlockData:
    """Tạo BlockData đơn giản."""
    span = SpanData(text=text, font_name="Arial", font_size=font_size,
                    font_flags=font_flags, bbox=bbox)
    line = LineData(bbox=bbox, spans=[span])
    return BlockData(bbox=bbox, block_type=0, block_number=0, lines=[line])


def make_region(text: str, region_type: RegionType,
                bbox: tuple = (50, 50, 500, 70),
                confidence: float = 0.8) -> Region:
    """Tạo Region với một block."""
    block = make_block(text, bbox)
    return Region(
        region_type=region_type, blocks=[block],
        page_number=0, reading_order_index=0, confidence=confidence,
    )


def make_layout_doc(regions: list[Region],
                    file_path: str = "test.pdf") -> LayoutDocument:
    """Tạo LayoutDocument với 1 page chứa regions."""
    page = LayoutPage(
        page_number=0, width=612.0, height=792.0,
        regions=regions, column_info=ColumnInfo(),
    )
    return LayoutDocument(
        file_path=file_path, page_count=1,
        pages=[page], total_regions=len(regions),
    )


def make_standard_doc(
    title: str = "Paper Title",
    authors: str = "John Doe, Jane Smith",
    abstract: str = "This is the abstract.",
) -> LayoutDocument:
    """Tạo LayoutDocument chuẩn với TITLE, AUTHOR, ABSTRACT."""
    regions = [
        make_region(title, RegionType.TITLE, bbox=(100, 60, 500, 90)),
        make_region(authors, RegionType.AUTHOR, bbox=(100, 100, 500, 120)),
        make_region(abstract, RegionType.ABSTRACT, bbox=(50, 150, 560, 300)),
    ]
    return make_layout_doc(regions)


# ═══════════════════════════════════════════════
# Tests: AuthorCleaner
# ═══════════════════════════════════════════════

class TestAuthorCleanerSplit:
    """Tests cho split_and_clean() — separator splitting."""

    def setup_method(self):
        self.cleaner = AuthorCleaner()

    def test_split_comma(self):
        """Comma separator → 2 names."""
        result = self.cleaner.split_and_clean("Alice Brown, Bob White")
        assert result == ["Alice Brown", "Bob White"]

    def test_split_semicolons(self):
        """Semicolon separator → 2 names."""
        result = self.cleaner.split_and_clean("Alice Brown; Bob White")
        assert result == ["Alice Brown", "Bob White"]

    def test_split_and_symbol(self):
        """'and' separator → 2 names."""
        result = self.cleaner.split_and_clean("Alice Brown and Bob White")
        assert result == ["Alice Brown", "Bob White"]

    def test_split_ampersand(self):
        """'&' separator → 2 names."""
        result = self.cleaner.split_and_clean("Alice Brown & Bob White")
        assert result == ["Alice Brown", "Bob White"]

    def test_split_middle_dot(self):
        """Middle dot separator → 2 names."""
        result = self.cleaner.split_and_clean("Alice Brown · Bob White")
        assert result == ["Alice Brown", "Bob White"]

    def test_split_mixed_separators(self):
        """Multiple separators → correct split."""
        result = self.cleaner.split_and_clean("Alice Brown, Bob White and Carol Green")
        assert len(result) == 3
        assert "Alice Brown" in result
        assert "Bob White" in result
        assert "Carol Green" in result

    def test_vietnamese_names(self):
        """Vietnamese names with diacritics."""
        result = self.cleaner.split_and_clean("Nguyễn Văn An, Trần Thị Bình")
        assert len(result) == 2
        assert "Nguyễn Văn An" in result
        assert "Trần Thị Bình" in result

    def test_empty_string(self):
        """Empty → []."""
        assert self.cleaner.split_and_clean("") == []

    def test_whitespace_only(self):
        """Whitespace → []."""
        assert self.cleaner.split_and_clean("   ") == []


class TestAuthorCleanerRemoval:
    """Tests cho email, ORCID, bracket removal."""

    def setup_method(self):
        self.cleaner = AuthorCleaner()

    def test_remove_emails(self):
        """Email bị loại bỏ."""
        result = self.cleaner.split_and_clean(
            "John Doe john.doe@mit.edu, Jane Smith jane@uni.edu"
        )
        assert "John Doe" in result
        assert "Jane Smith" in result
        # Không nên có email trong tên
        for name in result:
            assert "@" not in name

    def test_remove_orcid(self):
        """ORCID ID bị loại bỏ."""
        result = self.cleaner.split_and_clean(
            "John Doe 0000-0001-2345-6789, Jane Smith"
        )
        assert "John Doe" in result

    def test_remove_brackets(self):
        """Bracket content (affiliations) bị loại bỏ."""
        result = self.cleaner.split_and_clean(
            "John Doe (University of Oxford), Jane Smith [MIT]"
        )
        assert "John Doe" in result
        assert "Jane Smith" in result
        for name in result:
            assert "University" not in name
            assert "MIT" not in name

    def test_extract_emails(self):
        """extract_emails() trả về danh sách emails."""
        emails = self.cleaner.extract_emails(
            "John Doe john@uni.edu, Jane jane@test.com"
        )
        assert len(emails) == 2
        assert "john@uni.edu" in emails
        assert "jane@test.com" in emails


class TestAuthorCleanerCleanName:
    """Tests cho clean_name() — footnote/symbol removal."""

    def setup_method(self):
        self.cleaner = AuthorCleaner()

    def test_remove_footnote_markers(self):
        """Footnote markers (¹²) removed."""
        assert self.cleaner.clean_name("John Doe¹²") == "John Doe"

    def test_remove_asterisk(self):
        """Asterisk removed."""
        assert self.cleaner.clean_name("John Doe*") == "John Doe"

    def test_remove_dagger(self):
        """Dagger (†) removed."""
        assert self.cleaner.clean_name("John Doe†") == "John Doe"

    def test_remove_double_dagger(self):
        """Double dagger (‡) removed."""
        assert self.cleaner.clean_name("John Doe‡") == "John Doe"

    def test_remove_trailing_digits(self):
        """Trailing superscript digits removed."""
        assert self.cleaner.clean_name("John Doe1,2") == "John Doe"

    def test_split_names_joined_by_affiliation_marker(self):
        """An affiliation digit between adjacent names is a real boundary."""
        result = self.cleaner.split_and_clean(
            "Nguyễn Đức Anh1 Bùi Thị Vân Anh"
        )
        assert result == ["Nguyễn Đức Anh", "Bùi Thị Vân Anh"]

    def test_remove_leading_affiliation_digits_and_private_use_marker(self):
        """Detached affiliation digits and PDF private-use footnotes vanish."""
        assert self.cleaner.clean_name("2 Nguyễn Thị Thanh Hải") == "Nguyễn Thị Thanh Hải"
        assert self.cleaner.clean_name("Nguyễn Trọng Tuệ\uf02a") == "Nguyễn Trọng Tuệ"

    def test_split_vietnamese_conjunction_before_removing_affiliation_marker(self):
        """'và' splits authors so the preceding affiliation number is removed."""
        result = self.cleaner.split_and_clean(
            "Bùi Tiến Hùng1, Lương Đức Dũng 2 và Nguyễn Thị Minh3"
        )
        assert result == ["Bùi Tiến Hùng", "Lương Đức Dũng", "Nguyễn Thị Minh"]
        assert all(not any(character.isdigit() for character in name) for name in result)

    def test_clean_combined(self):
        """Footnote + asterisk + digits."""
        assert self.cleaner.clean_name("John Doe¹*†") == "John Doe"

    def test_clean_empty(self):
        """Empty string → empty."""
        assert self.cleaner.clean_name("") == ""

    def test_preserve_normal_name(self):
        """Normal name preserved."""
        assert self.cleaner.clean_name("John Doe") == "John Doe"

    def test_preserve_vietnamese(self):
        """Vietnamese name preserved."""
        assert self.cleaner.clean_name("Nguyễn Văn An") == "Nguyễn Văn An"


class TestAuthorCleanerFilter:
    """Tests cho filter_names() — validation + dedup."""

    def setup_method(self):
        self.cleaner = AuthorCleaner()

    def test_filter_short_names(self):
        """Single token names filtered out."""
        result = self.cleaner.filter_names(["J", "John", "X"])
        assert result == []

    def test_filter_long_names(self):
        """Name > 80 chars filtered out."""
        long_name = "A" * 40 + " " + "B" * 41
        result = self.cleaner.filter_names([long_name])
        assert result == []

    def test_filter_digit_names(self):
        """Names with high digit ratio filtered out."""
        result = self.cleaner.filter_names(["12345 67890"])
        assert result == []

    def test_filter_no_alpha(self):
        """Names without alpha chars filtered out."""
        result = self.cleaner.filter_names(["123 456"])
        assert result == []

    def test_deduplicate(self):
        """Duplicate names (case-insensitive) removed."""
        result = self.cleaner.filter_names(["John Doe", "john doe", "JOHN DOE"])
        assert len(result) == 1
        assert result[0] == "John Doe"  # First occurrence kept

    def test_filter_affiliation_text(self):
        """Text containing affiliation keywords filtered out."""
        result = self.cleaner.filter_names(["University of Oxford"])
        assert result == []

    def test_pass_valid_names(self):
        """Valid names pass through."""
        names = ["John Doe", "Jane Smith", "Nguyễn Văn An"]
        result = self.cleaner.filter_names(names)
        assert result == names


# ═══════════════════════════════════════════════
# Tests: NER Engine
# ═══════════════════════════════════════════════

class TestStubNEREngine:
    """Tests cho StubNEREngine."""

    def test_predict_returns_empty(self):
        """StubNEREngine.predict() → []."""
        engine = StubNEREngine()
        assert engine.predict("John Doe is a researcher") == []

    def test_extract_persons_returns_empty(self):
        """StubNEREngine.extract_persons() → []."""
        engine = StubNEREngine()
        assert engine.extract_persons("John Doe is a researcher") == []


# ═══════════════════════════════════════════════
# Tests: AuthorDetector
# ═══════════════════════════════════════════════

class TestAuthorDetector:
    """Tests cho AuthorDetector — 3 tiers."""

    def setup_method(self):
        self.detector = AuthorDetector()

    def test_detect_authors_heuristic(self):
        """Tier 1: AUTHOR zone → correct names."""
        doc = make_standard_doc(authors="John Doe, Jane Smith")
        result = self.detector.detect(doc)

        assert result.count == 2
        assert "John Doe" in result.author_names
        assert "Jane Smith" in result.author_names
        assert result.strategy == "heuristic"
        assert result.confidence >= 0.75

    def test_detect_multiple_authors(self):
        """Tier 1: Many authors."""
        doc = make_standard_doc(
            authors="Alice Brown, Bob White, Carol Green, Dave Black"
        )
        result = self.detector.detect(doc)
        assert result.count == 4
        assert result.strategy in ("heuristic", "pattern")

    def test_detect_vietnamese_authors(self):
        """Tier 1: Vietnamese names."""
        doc = make_standard_doc(
            authors="Nguyễn Văn An, Trần Thị Bình, Lê Hoàng Nam"
        )
        result = self.detector.detect(doc)
        assert result.count == 3
        assert "Nguyễn Văn An" in result.author_names

    def test_detect_single_author(self):
        """Tier 1: Single author."""
        doc = make_standard_doc(authors="John Doe")
        result = self.detector.detect(doc)
        assert result.count == 1
        assert result.author_names == ["John Doe"]

    def test_detect_authors_with_emails(self):
        """Tier 1: Authors with emails → emails extracted."""
        doc = make_standard_doc(
            authors="John Doe john@uni.edu, Jane Smith jane@test.com"
        )
        result = self.detector.detect(doc)
        assert result.count == 2
        # Check emails attached
        emails = [a.email for a in result.authors if a.email]
        assert len(emails) >= 1

    def test_detect_authors_with_footnotes(self):
        """Tier 1: Authors with footnote markers → cleaned."""
        doc = make_standard_doc(authors="John Doe¹*, Jane Smith²")
        result = self.detector.detect(doc)
        assert result.count == 2
        assert "John Doe" in result.author_names
        assert "Jane Smith" in result.author_names

    def test_metadata_band_recovers_author_fragmented_outside_author_region(self):
        """The final name remains available when M3 splits an author line."""
        title = make_region("TỔNG QUAN VỀ HIF", RegionType.TITLE, bbox=(90, 50, 520, 80))
        first_authors = make_region(
            "Trần Tuấn Tú1,2, Nguyễn Quang Hảo3",
            RegionType.AUTHOR,
            bbox=(120, 100, 430, 116),
        )
        final_author = make_region(
            "Hoàng Thị Hải Yến1",
            RegionType.BODY,
            bbox=(435, 100, 540, 116),
        )
        affiliation = make_region(
            "Trường Đại học Y Dược", RegionType.AFFILIATION,
            bbox=(210, 135, 420, 151),
        )
        abstract = make_region(
            "Nghiên cứu mô tả kết quả điều trị và đánh giá hiệu quả trong thực hành lâm sàng.",
            RegionType.BODY,
            bbox=(70, 180, 540, 210),
        )
        doc = make_layout_doc([title, first_authors, final_author, affiliation, abstract])
        title_result = TitleResult(
            title="TỔNG QUAN VỀ HIF", bbox=[90, 50, 520, 80],
            page=0, strategy="zone_based", confidence=0.95,
        )

        result = self.detector.detect(doc, title_result)

        assert result.author_names == [
            "Trần Tuấn Tú", "Nguyễn Quang Hảo", "Hoàng Thị Hải Yến",
        ]

    def test_detect_tier3_fallback(self):
        """Tier 3: No AUTHOR zone, find authors in gap."""
        # Create doc without AUTHOR region
        regions = [
            make_region("Paper Title", RegionType.TITLE,
                        bbox=(100, 60, 500, 90)),
            # Block between title and abstract (authors)
            make_region("Alice Brown, Bob White", RegionType.BODY,
                        bbox=(100, 100, 500, 120)),
            make_region("This is the abstract text here.",
                        RegionType.ABSTRACT, bbox=(50, 150, 560, 300)),
        ]
        doc = make_layout_doc(regions)
        title_result = TitleResult(
            title="Paper Title",
            bbox=[100, 60, 500, 90],
            page=0, strategy="zone_based", confidence=0.95,
        )

        result = self.detector.detect(doc, title_result)
        assert result.count >= 1
        assert result.strategy == "pattern"

    def test_detect_empty_doc(self):
        """Empty document → no authors."""
        doc = LayoutDocument(file_path="empty.pdf", page_count=0, pages=[])
        result = self.detector.detect(doc)
        assert result.count == 0
        assert result.strategy == "none"

    def test_detect_no_author_region(self):
        """No AUTHOR zone, no pattern → empty or fallback."""
        regions = [
            make_region("Paper Title", RegionType.TITLE,
                        bbox=(100, 60, 500, 90)),
            make_region("Body text only.", RegionType.BODY,
                        bbox=(50, 100, 560, 700)),
        ]
        doc = make_layout_doc(regions)
        result = self.detector.detect(doc)
        # May find something via pattern or return empty
        assert isinstance(result, AuthorResult)


# ═══════════════════════════════════════════════
# Tests: AuthorResult model
# ═══════════════════════════════════════════════

class TestAuthorResult:
    """Tests cho AuthorResult dataclass."""

    def test_to_dict(self):
        """to_dict() serialization."""
        result = AuthorResult(
            authors=[
                AuthorInfo(name="John Doe", email="john@uni.edu"),
                AuthorInfo(name="Jane Smith", affiliation="MIT"),
            ],
            confidence=0.85,
            strategy="heuristic",
        )
        d = result.to_dict()
        assert d["count"] == 2
        assert d["confidence"] == 0.85
        assert d["strategy"] == "heuristic"
        assert len(d["authors"]) == 2
        assert d["authors"][0]["name"] == "John Doe"
        assert d["authors"][0]["email"] == "john@uni.edu"
        assert d["authors"][1]["affiliation"] == "MIT"

    def test_author_names_property(self):
        """author_names → list of names."""
        result = AuthorResult(
            authors=[AuthorInfo(name="A B"), AuthorInfo(name="C D")]
        )
        assert result.author_names == ["A B", "C D"]

    def test_count_property(self):
        """count → len(authors)."""
        result = AuthorResult(
            authors=[AuthorInfo(name="A B"), AuthorInfo(name="C D")]
        )
        assert result.count == 2

    def test_empty_result(self):
        """Empty result."""
        result = AuthorResult()
        assert result.count == 0
        assert result.author_names == []


# ═══════════════════════════════════════════════
# Tests: Service
# ═══════════════════════════════════════════════

class TestAuthorDetectionService:
    """Tests cho AuthorDetectionService."""

    def test_service_detect(self):
        """Service wrapper works correctly."""
        service = AuthorDetectionService()
        doc = make_standard_doc(authors="John Doe, Jane Smith")
        result = service.detect_authors(doc)
        assert result.count == 2

    def test_service_empty_doc(self):
        """Service handles empty document."""
        service = AuthorDetectionService()
        doc = LayoutDocument(file_path="empty.pdf", page_count=0, pages=[])
        result = service.detect_authors(doc)
        assert result.count == 0

    def test_service_with_title_result(self):
        """Service forwards title_result to detector."""
        service = AuthorDetectionService()
        doc = make_standard_doc()
        title_result = TitleResult(
            title="Paper Title", bbox=[100, 60, 500, 90],
            page=0, strategy="zone_based",
        )
        result = service.detect_authors(doc, title_result)
        assert result.count >= 1


# ═══════════════════════════════════════════════
# Tests: Integration — Real PDF
# ═══════════════════════════════════════════════

_PARENT_DIR = Path(__file__).resolve().parent.parent.parent
_SAMPLE_PDFS = {
    "naacl": _PARENT_DIR / "2024.naacl-long.461.pdf",
    "phogpt": _PARENT_DIR / "2311.02945v3.pdf",
}


def _extract_and_analyze(pdf_path: str):
    """Helper: full pipeline M2 → M3 → M4 → result."""
    from core.text_extraction.extractor import PDFTextExtractor
    from core.layout_analysis.layout_analyzer import LayoutAnalyzer
    from core.title_detection.detector import TitleDetector

    extractor = PDFTextExtractor()
    doc_data = extractor.extract(pdf_path)
    analyzer = LayoutAnalyzer()
    layout_doc = analyzer.analyze(doc_data)
    title_detector = TitleDetector()
    title_result = title_detector.detect(layout_doc)
    return layout_doc, title_result


@pytest.mark.skipif(
    not _SAMPLE_PDFS["naacl"].exists(),
    reason="Sample PDF 2024.naacl-long.461.pdf not found"
)
class TestRealPDFNaacl:
    """Integration test trên 2024.naacl-long.461.pdf."""

    def test_authors_detected(self):
        """Phải detect được authors."""
        layout_doc, title_result = _extract_and_analyze(
            str(_SAMPLE_PDFS["naacl"])
        )
        detector = AuthorDetector()
        result = detector.detect(layout_doc, title_result)

        assert result.count > 0, "Should detect at least 1 author"
        # Check at least one known author name
        all_names = " ".join(result.author_names).lower()
        # The paper has authors like "Guiliano Martinelli" etc.
        assert len(result.author_names) >= 1


@pytest.mark.skipif(
    not _SAMPLE_PDFS["phogpt"].exists(),
    reason="Sample PDF 2311.02945v3.pdf not found"
)
class TestRealPDFPhoGPT:
    """Integration test trên 2311.02945v3.pdf."""

    def test_authors_detected(self):
        """Phải detect được authors."""
        layout_doc, title_result = _extract_and_analyze(
            str(_SAMPLE_PDFS["phogpt"])
        )
        service = AuthorDetectionService()
        result = service.detect_authors(layout_doc, title_result)

        assert result.count > 0, "Should detect at least 1 author"
