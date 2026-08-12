"""
tests/test_data_cleaning.py
Unit tests cho Milestone 7 -- Data Cleaning & Normalization.

Covers:
1. Unicode normalization (Vietnamese composed/decomposed)
2. Vietnamese text preservation
3. Whitespace normalization
4. Hyphenation repair (safe + compound words)
5. Title cleaning
6. Author cleaning (email, ORCID, footnotes, dedup)
7. Abstract cleaning (header/footer removal, paragraph preservation)
8. Noise detection
9. Empty/None/malformed input
10. Full pipeline integration
11. Character substitution (ligatures, smart quotes)
12. Control character removal
"""

import pytest
import unicodedata

from core.data_cleaning.text_cleaner import TextCleaner
from core.data_cleaning.title_cleaner import TitleCleaner
from core.data_cleaning.author_cleaner import MetadataAuthorCleaner
from core.data_cleaning.abstract_cleaner import AbstractCleaner
from core.data_cleaning.noise_detector import NoiseDetector
from core.data_cleaning.service import DataCleaningService
from core.data_cleaning.models import (
    CleaningResult,
    NoiseResult,
    AUTHOR_EMAILS_REMOVED,
    AUTHOR_FOOTNOTES_REMOVED,
    AUTHOR_DUPLICATES_REMOVED,
    AUTHOR_ORCID_REMOVED,
    TITLE_CLEANED,
    ABSTRACT_HEADER_REMOVED,
    ABSTRACT_FOOTER_REMOVED,
    HIGH_NON_ALPHA_RATIO,
    HIGH_WHITESPACE_RATIO,
    HIGH_DUPLICATE_LINES,
    POSSIBLE_GARBLED_TEXT,
    TEXT_TOO_SHORT,
)


# ═══════════════════════════════════════════════
# 1. UNICODE NORMALIZATION
# ═══════════════════════════════════════════════

class TestUnicodeNormalization:
    """Tests cho Unicode normalization (NFC)."""

    def test_nfc_vietnamese_composed_vs_decomposed(self):
        """
        Two Unicode representations of Vietnamese text
        should normalize to the same NFC form.

        'a breve acute' (decomposed NFD) vs 'a with breve and acute' (composed NFC)
        """
        # NFD decomposed form
        decomposed = unicodedata.normalize("NFD", "ắ")
        # NFC composed form
        composed = unicodedata.normalize("NFC", "ắ")

        # They look the same but differ in codepoints
        assert decomposed != composed  # Different byte sequences
        assert len(decomposed) > len(composed)  # NFD is longer

        # After NFC normalization, they should be equal
        result_d = TextCleaner.normalize_unicode(decomposed)
        result_c = TextCleaner.normalize_unicode(composed)
        assert result_d == result_c

    def test_nfc_vietnamese_full_word(self):
        """Vietnamese word with diacritics normalizes correctly."""
        # 'Nguyen' with diacritics in NFD
        word_nfd = unicodedata.normalize("NFD", "Nguyễn")
        word_nfc = unicodedata.normalize("NFC", "Nguyễn")

        assert TextCleaner.normalize_unicode(word_nfd) == word_nfc

    def test_nfc_vietnamese_sentence(self):
        """Full Vietnamese sentence normalizes."""
        nfd = unicodedata.normalize("NFD", "Đại học Bách khoa Hà Nội")
        nfc = unicodedata.normalize("NFC", "Đại học Bách khoa Hà Nội")

        assert TextCleaner.normalize_unicode(nfd) == nfc

    def test_nfc_english_unchanged(self):
        """English text (no diacritics) is unchanged by NFC."""
        text = "Deep Learning for Medical Diagnosis"
        assert TextCleaner.normalize_unicode(text) == text

    def test_nfc_empty(self):
        """Empty string returns empty."""
        assert TextCleaner.normalize_unicode("") == ""


# ═══════════════════════════════════════════════
# 2. VIETNAMESE TEXT PRESERVATION
# ═══════════════════════════════════════════════

class TestVietnamesePreservation:
    """Tests dam bao tieng Viet khong bi mat dau."""

    def test_vietnamese_title_preserved(self):
        """Vietnamese title with diacritics survives full cleaning."""
        title = "ĐÁNH GIÁ KẾT QUẢ PHẪU THUẬT MẤT VỮNG C1-C2"
        cleaned, _ = TitleCleaner.clean(title)
        assert cleaned == title

    def test_vietnamese_author_preserved(self):
        """Vietnamese author names survive cleaning."""
        authors = ["Nguyễn Văn An", "Trần Thị Bình", "Lê Hoàng Cường"]
        cleaned, _ = MetadataAuthorCleaner.clean_all(authors)
        assert cleaned == authors

    def test_vietnamese_abstract_preserved(self):
        """Vietnamese abstract text survives cleaning."""
        abstract = (
            "Đặt vấn đề: Suy hô hấp sơ sinh là nguyên nhân "
            "hàng đầu gây tử vong ở trẻ sơ sinh."
        )
        cleaned, _ = AbstractCleaner.clean(abstract)
        assert cleaned == abstract

    def test_vietnamese_special_chars(self):
        """Special Vietnamese chars: đ, ư, ơ, ă, ê with all tone marks."""
        chars = "ắ ằ ẳ ẵ ặ ấ ầ ẩ ẫ ậ ế ề ể ễ ệ ố ồ ổ ỗ ộ ớ ờ ở ỡ ợ ứ ừ ử ữ ự"
        result = TextCleaner.normalize_unicode(chars)
        # All chars should be present
        assert "ắ" in result
        assert "ự" in result
        assert len(result) == len(chars)


# ═══════════════════════════════════════════════
# 3. WHITESPACE NORMALIZATION
# ═══════════════════════════════════════════════

class TestWhitespaceNormalization:
    """Tests cho whitespace normalization."""

    def test_multiple_spaces(self):
        """'Deep    Learning   for\\nMedical Diagnosis' -> 'Deep Learning for Medical Diagnosis'."""
        text = "Deep    Learning   for\nMedical Diagnosis"
        result = TextCleaner.normalize_whitespace(text, preserve_paragraphs=False)
        assert result == "Deep Learning for Medical Diagnosis"

    def test_tabs(self):
        """Tabs replaced by spaces."""
        text = "Title\twith\ttabs"
        result = TextCleaner.normalize_whitespace(text, preserve_paragraphs=False)
        assert result == "Title with tabs"

    def test_leading_trailing_whitespace(self):
        """Leading/trailing whitespace stripped."""
        text = "   Some text   "
        result = TextCleaner.normalize_whitespace(text)
        assert result == "Some text"

    def test_blank_lines_collapsed(self):
        """3+ blank lines collapsed to 2 when preserving paragraphs."""
        text = "Para 1\n\n\n\n\nPara 2"
        result = TextCleaner.normalize_whitespace(text, preserve_paragraphs=True)
        assert "\n\n\n" not in result
        assert "Para 1" in result
        assert "Para 2" in result

    def test_preserve_paragraphs_double_newline(self):
        """Double newlines preserved when preserve_paragraphs=True."""
        text = "First paragraph.\n\nSecond paragraph."
        result = TextCleaner.normalize_whitespace(text, preserve_paragraphs=True)
        assert "\n\n" in result

    def test_empty_string(self):
        """Empty string returns empty."""
        assert TextCleaner.normalize_whitespace("") == ""

    def test_only_whitespace(self):
        """Only whitespace returns empty."""
        assert TextCleaner.normalize_whitespace("   \n\n\t  ") == ""


# ═══════════════════════════════════════════════
# 4. HYPHENATION REPAIR
# ═══════════════════════════════════════════════

class TestHyphenationRepair:
    """Tests cho hyphenation repair."""

    def test_basic_hyphenation(self):
        """'transfor-\\nmation' -> 'transformation'."""
        text = "transfor-\nmation"
        result = TextCleaner.repair_hyphenation(text)
        assert result == "transformation"

    def test_information_hyphenation(self):
        """'infor-\\nmation' -> 'information'."""
        text = "infor-\nmation"
        result = TextCleaner.repair_hyphenation(text)
        assert result == "information"

    def test_compound_state_of_the_art(self):
        """'state-of-the-art' preserved (no newline)."""
        text = "state-of-the-art"
        result = TextCleaner.repair_hyphenation(text)
        assert result == "state-of-the-art"

    def test_compound_well_known_preserved(self):
        """'well-\\nknown' -> 'well-known' (compound word preserved)."""
        text = "well-\nknown"
        result = TextCleaner.repair_hyphenation(text)
        assert result == "well-known"

    def test_compound_self_attention_preserved(self):
        """'self-\\nattention' -> 'self-attention' (compound word)."""
        text = "self-\nattention"
        result = TextCleaner.repair_hyphenation(text)
        assert result == "self-attention"

    def test_compound_multi_scale_preserved(self):
        """'multi-\\nscale' -> 'multi-scale' (compound word)."""
        text = "multi-\nscale"
        result = TextCleaner.repair_hyphenation(text)
        assert result == "multi-scale"

    def test_real_world_dehyphenation(self):
        """Real PDF dehyphenation: 'classi-\\nfication' -> 'classification'."""
        text = "classi-\nfication"
        result = TextCleaner.repair_hyphenation(text)
        assert result == "classification"

    def test_no_hyphen_unchanged(self):
        """Text without hyphens unchanged."""
        text = "This is normal text without hyphens."
        result = TextCleaner.repair_hyphenation(text)
        assert result == text

    def test_empty_string(self):
        """Empty string returns empty."""
        assert TextCleaner.repair_hyphenation("") == ""

    def test_hyphen_with_spaces(self):
        """'infor- \\n mation' with spaces around hyphen."""
        text = "infor- \n mation"
        result = TextCleaner.repair_hyphenation(text)
        assert result == "information"


# ═══════════════════════════════════════════════
# 5. CHARACTER SUBSTITUTION
# ═══════════════════════════════════════════════

class TestCharacterSubstitution:
    """Tests cho character substitution."""

    def test_ligature_fi(self):
        """Ligature fi -> fi."""
        assert TextCleaner.apply_char_substitution("\ufb01nd") == "find"

    def test_ligature_fl(self):
        """Ligature fl -> fl."""
        assert TextCleaner.apply_char_substitution("\ufb02ow") == "flow"

    def test_ligature_ffi(self):
        """Ligature ffi -> ffi."""
        assert TextCleaner.apply_char_substitution("e\ufb03cient") == "efficient"

    def test_smart_quotes(self):
        """Smart quotes -> straight quotes."""
        text = "\u201cHello\u201d \u2018World\u2019"
        result = TextCleaner.apply_char_substitution(text)
        assert result == '"Hello" \'World\''

    def test_em_dash(self):
        """Em dash -> --."""
        assert TextCleaner.apply_char_substitution("word\u2014word") == "word--word"

    def test_en_dash(self):
        """En dash -> -."""
        assert TextCleaner.apply_char_substitution("2020\u20132024") == "2020-2024"

    def test_ellipsis(self):
        """Ellipsis -> ..."""
        assert TextCleaner.apply_char_substitution("etc\u2026") == "etc..."

    def test_nbsp(self):
        """Non-breaking space -> regular space."""
        assert TextCleaner.apply_char_substitution("word\u00a0word") == "word word"


# ═══════════════════════════════════════════════
# 6. CONTROL CHARACTER REMOVAL
# ═══════════════════════════════════════════════

class TestControlCharRemoval:
    """Tests cho control character removal."""

    def test_null_byte(self):
        """Null byte removed."""
        assert TextCleaner.remove_control_chars("hello\x00world") == "helloworld"

    def test_bell_char(self):
        """Bell character removed."""
        assert TextCleaner.remove_control_chars("hello\x07world") == "helloworld"

    def test_newline_preserved(self):
        """Newlines are NOT removed (handled separately)."""
        text = "line1\nline2"
        assert TextCleaner.remove_control_chars(text) == text

    def test_tab_preserved(self):
        """Tabs are NOT removed (handled by whitespace normalization)."""
        text = "col1\tcol2"
        assert TextCleaner.remove_control_chars(text) == text

    def test_c1_control_chars(self):
        """C1 control characters (0x80-0x9F) removed."""
        assert TextCleaner.remove_control_chars("hello\x80world") == "helloworld"


# ═══════════════════════════════════════════════
# 7. TITLE CLEANING
# ═══════════════════════════════════════════════

class TestTitleCleaning:
    """Tests cho TitleCleaner."""

    def test_basic_title(self):
        """Normal title unchanged."""
        title = "Deep Learning for Medical Diagnosis"
        cleaned, _ = TitleCleaner.clean(title)
        assert cleaned == title

    def test_title_with_newlines(self):
        """Newlines in title removed."""
        title = "Deep Learning\nfor Medical\nDiagnosis"
        cleaned, _ = TitleCleaner.clean(title)
        assert cleaned == "Deep Learning for Medical Diagnosis"

    def test_title_with_multiple_spaces(self):
        """Multiple spaces collapsed."""
        title = "Deep   Learning    for   Medical"
        cleaned, _ = TitleCleaner.clean(title)
        assert cleaned == "Deep Learning for Medical"

    def test_title_with_ligatures(self):
        """Ligatures in title expanded."""
        title = "E\ufb03cient Methods for Classi\ufb01cation"
        cleaned, _ = TitleCleaner.clean(title)
        assert "Efficient" in cleaned
        assert "Classification" in cleaned

    def test_title_none(self):
        """None title returns None."""
        cleaned, _ = TitleCleaner.clean(None)
        assert cleaned is None

    def test_title_empty(self):
        """Empty title returns None."""
        cleaned, _ = TitleCleaner.clean("")
        assert cleaned is None

    def test_title_only_whitespace(self):
        """Whitespace-only title returns None."""
        cleaned, _ = TitleCleaner.clean("   \n\n  ")
        assert cleaned is None

    def test_title_unicode_normalized(self):
        """Vietnamese title Unicode-normalized."""
        import unicodedata
        nfd_title = unicodedata.normalize("NFD", "Đánh giá phương pháp")
        cleaned, _ = TitleCleaner.clean(nfd_title)
        nfc_expected = unicodedata.normalize("NFC", "Đánh giá phương pháp")
        assert cleaned == nfc_expected


# ═══════════════════════════════════════════════
# 8. AUTHOR CLEANING
# ═══════════════════════════════════════════════

class TestAuthorCleaning:
    """Tests cho MetadataAuthorCleaner."""

    def test_basic_authors(self):
        """Normal author names unchanged."""
        authors = ["John Smith", "Jane Doe"]
        cleaned, _ = MetadataAuthorCleaner.clean_all(authors)
        assert cleaned == authors

    def test_authors_with_emails(self):
        """Emails removed from author names."""
        authors = ["John Smith john@example.com", "Jane Doe jane@uni.edu"]
        cleaned, changes = MetadataAuthorCleaner.clean_all(authors)
        assert "john@example.com" not in cleaned[0]
        assert AUTHOR_EMAILS_REMOVED in changes

    def test_authors_with_footnotes(self):
        """Footnote markers removed."""
        authors = ["Nguyen Van A\u00b9", "Tran Thi B\u00b2"]
        cleaned, changes = MetadataAuthorCleaner.clean_all(authors)
        for name in cleaned:
            assert "\u00b9" not in name
            assert "\u00b2" not in name

    def test_authors_with_superscript_markers(self):
        """Superscript footnote markers removed."""
        authors = ["John Smith\u00b9\u00b2", "Jane Doe\u00b3"]
        cleaned, changes = MetadataAuthorCleaner.clean_all(authors)
        assert AUTHOR_FOOTNOTES_REMOVED in changes

    def test_authors_with_orcid(self):
        """ORCID IDs removed."""
        authors = ["John Smith 0000-0001-2345-6789"]
        cleaned, changes = MetadataAuthorCleaner.clean_all(authors)
        assert "0000-0001" not in cleaned[0]
        assert AUTHOR_ORCID_REMOVED in changes

    def test_authors_deduplication(self):
        """Duplicate authors removed (case-insensitive)."""
        authors = ["John Smith", "john smith", "JOHN SMITH"]
        cleaned, changes = MetadataAuthorCleaner.clean_all(authors)
        assert len(cleaned) == 1
        assert AUTHOR_DUPLICATES_REMOVED in changes

    def test_authors_empty_list(self):
        """Empty list returns empty."""
        cleaned, changes = MetadataAuthorCleaner.clean_all([])
        assert cleaned == []
        assert changes == []

    def test_authors_with_trailing_digits(self):
        """Trailing digits removed: 'John Doe1,2' -> 'John Doe'."""
        authors = ["John Doe1,2", "Jane Smith3"]
        cleaned, _ = MetadataAuthorCleaner.clean_all(authors)
        assert cleaned[0] == "John Doe"
        assert cleaned[1] == "Jane Smith"

    def test_vietnamese_authors_with_markers(self):
        """Vietnamese authors with footnote markers."""
        authors = ["Nguyen Van A\u00b9", "Tran Thi B\u00b2", "Le Hoang C*"]
        cleaned, _ = MetadataAuthorCleaner.clean_all(authors)
        assert "Nguyen Van A" in cleaned[0]
        assert "Tran Thi B" in cleaned[1]


# ═══════════════════════════════════════════════
# 9. ABSTRACT CLEANING
# ═══════════════════════════════════════════════

class TestAbstractCleaning:
    """Tests cho AbstractCleaner."""

    def test_basic_abstract(self):
        """Normal abstract unchanged (modulo whitespace)."""
        abstract = (
            "This paper presents a novel method for extracting "
            "metadata from scientific PDF documents."
        )
        cleaned, _ = AbstractCleaner.clean(abstract)
        assert cleaned == abstract

    def test_abstract_with_stuck_doi(self):
        """doi at start removed."""
        abstract = (
            "doi: 10.1234/example.2024\n"
            "This paper presents a novel approach."
        )
        cleaned, changes = AbstractCleaner.clean(abstract)
        assert "doi" not in cleaned.lower()
        assert ABSTRACT_HEADER_REMOVED in changes

    def test_abstract_with_stuck_page_number(self):
        """Page number at end removed."""
        abstract = (
            "This paper presents a novel approach to document analysis.\n123"
        )
        cleaned, changes = AbstractCleaner.clean(abstract)
        assert not cleaned.endswith("123")
        assert ABSTRACT_FOOTER_REMOVED in changes

    def test_abstract_with_copyright(self):
        """Copyright line at end removed."""
        abstract = (
            "This paper presents results.\n"
            "\u00a9 2024 IEEE"
        )
        cleaned, changes = AbstractCleaner.clean(abstract)
        assert "\u00a9" not in cleaned
        assert ABSTRACT_FOOTER_REMOVED in changes

    def test_abstract_paragraph_preserved(self):
        """Paragraph breaks preserved."""
        abstract = (
            "First paragraph of the abstract.\n\n"
            "Second paragraph continues here."
        )
        cleaned, _ = AbstractCleaner.clean(abstract)
        assert "\n\n" in cleaned
        assert "First paragraph" in cleaned
        assert "Second paragraph" in cleaned

    def test_abstract_hyphenation_repaired(self):
        """Hyphenated words repaired."""
        abstract = (
            "This paper presents a classi-\nfication method "
            "for document understanding."
        )
        cleaned, _ = AbstractCleaner.clean(abstract)
        assert "classification" in cleaned

    def test_abstract_none(self):
        """None returns None."""
        cleaned, _ = AbstractCleaner.clean(None)
        assert cleaned is None

    def test_abstract_empty(self):
        """Empty returns None."""
        cleaned, _ = AbstractCleaner.clean("")
        assert cleaned is None


# ═══════════════════════════════════════════════
# 10. NOISE DETECTION
# ═══════════════════════════════════════════════

class TestNoiseDetection:
    """Tests cho NoiseDetector."""

    def test_clean_text(self):
        """Normal text has low noise score."""
        result = NoiseDetector.analyze(
            "This paper presents a novel method for document analysis."
        )
        assert not result.is_noisy
        assert result.noise_score < 0.3

    def test_high_non_alpha_text(self):
        """Text with many non-alpha chars flagged."""
        result = NoiseDetector.analyze("###$$$%%%&&&***!!!@@@" * 5)
        assert result.is_noisy
        assert HIGH_NON_ALPHA_RATIO in result.flags

    def test_high_whitespace_text(self):
        """Text with excessive whitespace flagged."""
        result = NoiseDetector.analyze("a " * 100)
        assert HIGH_WHITESPACE_RATIO in result.flags

    def test_duplicate_lines(self):
        """Text with many duplicate lines flagged."""
        text = "Same line.\n" * 20
        result = NoiseDetector.analyze(text)
        assert HIGH_DUPLICATE_LINES in result.flags

    def test_garbled_text(self):
        """Text with very low alpha ratio flagged as garbled."""
        result = NoiseDetector.analyze("12345 67890 @#$% ^&*() 12345 67890")
        assert POSSIBLE_GARBLED_TEXT in result.flags

    def test_none_input(self):
        """None input returns clean result."""
        result = NoiseDetector.analyze(None)
        assert not result.is_noisy
        assert result.noise_score == 0.0

    def test_empty_input(self):
        """Empty input returns clean result with TEXT_TOO_SHORT flag."""
        result = NoiseDetector.analyze("")
        assert TEXT_TOO_SHORT in result.flags

    def test_short_text(self):
        """Very short text flagged."""
        result = NoiseDetector.analyze("Hi")
        assert TEXT_TOO_SHORT in result.flags

    def test_author_noise_detection(self):
        """Author noise detection works."""
        result = NoiseDetector.analyze_authors(["John Smith", "Jane Doe"])
        assert not result.is_noisy

    def test_author_noise_empty(self):
        """Empty author list."""
        result = NoiseDetector.analyze_authors([])
        assert TEXT_TOO_SHORT in result.flags

    def test_noise_result_to_dict(self):
        """NoiseResult serialization."""
        result = NoiseDetector.analyze("Normal scientific text for testing purposes.")
        d = result.to_dict()
        assert "is_noisy" in d
        assert "noise_score" in d
        assert "flags" in d
        assert "metrics" in d

    def test_noise_metrics_present(self):
        """All noise metrics present."""
        result = NoiseDetector.analyze("Some text with normal content here.")
        assert "non_alpha_ratio" in result.metrics
        assert "whitespace_ratio" in result.metrics
        assert "newline_ratio" in result.metrics
        assert "duplicate_line_ratio" in result.metrics
        assert "symbol_ratio" in result.metrics


# ═══════════════════════════════════════════════
# 11. FULL PIPELINE (SERVICE)
# ═══════════════════════════════════════════════

class TestDataCleaningService:
    """Tests cho DataCleaningService full pipeline."""

    def setup_method(self):
        self.service = DataCleaningService()

    def test_full_pipeline(self):
        """Full pipeline cleans title, authors, abstract."""
        result = self.service.clean(
            title="Deep   Learning\nfor   Medical\nDiagnosis",
            authors=["John Smith\u00b9", "Jane Doe john@test.com"],
            abstract=(
                "This paper presents a novel classi-\nfication method "
                "for medical image analysis."
            ),
        )

        assert isinstance(result, CleaningResult)
        assert result.title == "Deep Learning for Medical Diagnosis"
        assert "classification" in result.abstract
        assert "@test.com" not in " ".join(result.authors)

    def test_pipeline_none_inputs(self):
        """Pipeline handles None inputs."""
        result = self.service.clean(title=None, authors=None, abstract=None)
        assert result.title is None
        assert result.authors == []
        assert result.abstract is None

    def test_pipeline_empty_inputs(self):
        """Pipeline handles empty inputs."""
        result = self.service.clean(title="", authors=[], abstract="")
        assert result.title is None
        assert result.authors == []
        assert result.abstract is None

    def test_pipeline_vietnamese(self):
        """Pipeline preserves Vietnamese text."""
        result = self.service.clean(
            title="ĐÁNH GIÁ KẾT QUẢ PHẪU THUẬT",
            authors=["Nguyễn Văn An", "Trần Thị Bình"],
            abstract="Đặt vấn đề: Suy hô hấp sơ sinh.",
        )

        assert "ĐÁNH GIÁ" in result.title
        assert "Nguyễn Văn An" in result.authors
        assert "Đặt vấn đề" in result.abstract

    def test_pipeline_changes_tracked(self):
        """Changes are tracked."""
        result = self.service.clean(
            title="Title\nwith\nnewlines",
            authors=["Author\u00b9"],
            abstract="Text here.",
        )
        assert len(result.changes_made) > 0

    def test_pipeline_noise_scores(self):
        """Noise scores computed."""
        result = self.service.clean(
            title="Normal Title",
            authors=["John Smith"],
            abstract="Normal abstract text for testing.",
        )
        assert result.overall_noise_score >= 0.0
        assert result.overall_noise_score <= 1.0

    def test_pipeline_to_dict(self):
        """CleaningResult serialization."""
        result = self.service.clean(
            title="Test Title",
            authors=["Author One"],
            abstract="Test abstract.",
        )
        d = result.to_dict()
        assert "title" in d
        assert "authors" in d
        assert "abstract" in d
        assert "noise" in d
        assert "overall_score" in d["noise"]

    def test_pipeline_has_noise_property(self):
        """has_noise property works."""
        result = self.service.clean(
            title="Normal Title",
            authors=["John Smith"],
            abstract="This is a normal abstract.",
        )
        assert isinstance(result.has_noise, bool)


# ═══════════════════════════════════════════════
# 12. FULL CLEAN PIPELINE (TextCleaner.full_clean)
# ═══════════════════════════════════════════════

class TestFullClean:
    """Tests cho TextCleaner.full_clean."""

    def test_full_clean_all_steps(self):
        """Full pipeline applies all cleaning steps."""
        text = "E\ufb03cient\x00 transfor-\nmation   of  data"
        result, changes = TextCleaner.full_clean(text, preserve_paragraphs=False)
        assert "Efficient" in result
        assert "transformation" in result
        assert "\x00" not in result
        assert "  " not in result

    def test_full_clean_empty(self):
        """Empty input returns empty."""
        result, changes = TextCleaner.full_clean("")
        assert result == ""
        assert changes == []

    def test_full_clean_no_changes(self):
        """Clean text produces no changes."""
        text = "Already clean text."
        result, changes = TextCleaner.full_clean(text)
        assert result == text
        assert changes == []

    def test_full_clean_preserves_paragraphs(self):
        """Paragraph breaks preserved when requested."""
        text = "First paragraph.\n\nSecond paragraph."
        result, _ = TextCleaner.full_clean(text, preserve_paragraphs=True)
        assert "\n\n" in result
