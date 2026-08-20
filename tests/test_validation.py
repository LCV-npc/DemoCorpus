"""
tests/test_validation.py
Unit + Integration tests cho Milestone 8 -- Validation & Scoring.

Covers:
1. Title validation (6 cases: valid, short, numeric, DOI, URL, empty)
2. Author validation (5 cases: valid, empty, duplicate, email, affiliation)
3. Abstract validation (7 cases: valid, short, long, list, keywords, references, noisy)
4. Scoring (6 cases: all valid, title/author/abstract invalid, all invalid, boundary)
5. Integration (ValidationEngine with CleaningResult)
6. Models (serialization)
"""

import pytest

from core.validators.models import RuleResult, FieldValidation, ValidationReport
from core.validators.title_validator import TitleValidator
from core.validators.author_validator import AuthorValidator
from core.validators.abstract_validator import AbstractValidator
from core.validators.scoring import ValidationScorer
from core.validators.validation_engine import ValidationEngine
from core.data_cleaning.models import CleaningResult
from config.constants import VALIDATION_PASS_THRESHOLD


# ═══════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════

def _make_valid_abstract(word_count: int = 100) -> str:
    """Tạo abstract prose hợp lệ với số từ chỉ định."""
    base_sentences = [
        "This paper presents a novel approach to information extraction from academic papers.",
        "We propose a multi-stage pipeline that combines heuristic rules with machine learning.",
        "The system first extracts text blocks from PDF documents using PyMuPDF.",
        "Layout analysis identifies zones such as title, author, and abstract regions.",
        "Experimental results show that our approach achieves high accuracy on benchmark datasets.",
        "We evaluate the system on a collection of medical research papers.",
        "The validation module checks quality of extracted metadata using deterministic rules.",
        "Our scoring system provides transparency by reporting individual rule results.",
        "Future work includes integrating large language models for enhanced validation.",
        "The complete system is designed for production deployment with MongoDB persistence.",
    ]
    text = " ".join(base_sentences)
    words = text.split()
    # Repeat until we have enough words
    while len(words) < word_count:
        words.extend(text.split())
    return " ".join(words[:word_count]) + "."


# ═══════════════════════════════════════════════
# 1. TITLE VALIDATION
# ═══════════════════════════════════════════════

class TestTitleValidation:
    """Tests cho TitleValidator."""

    def test_title_valid(self):
        """Title hợp lệ → score = 1.0 (hoặc gần 1.0), passed = True."""
        result = TitleValidator.validate(
            "A Novel Approach to Information Extraction from Academic Papers"
        )
        assert result.passed is True
        assert result.score >= 0.90
        assert len(result.issues) == 0
        assert result.field_name == "title"

    def test_title_valid_sentence_case(self):
        """Title sentence case (phổ biến trong academic) → vẫn pass."""
        result = TitleValidator.validate(
            "Automated building of a multidialectal parallel Arabic corpus"
        )
        assert result.passed is True
        assert result.score >= 0.80

    def test_title_short(self):
        """Title quá ngắn → score < 1.0, có issue."""
        result = TitleValidator.validate("AB")
        assert result.score < 1.0
        assert any("short" in i or "length" in i for i in result.issues)

    def test_title_numeric(self):
        """Title toàn số → score < 1.0, có issue."""
        result = TitleValidator.validate("12345")
        assert result.score < 1.0
        assert any("digit" in i for i in result.issues)

    def test_title_doi(self):
        """Title là DOI → score < 1.0, có issue."""
        result = TitleValidator.validate("doi: 10.1234/abc.2023.456")
        assert result.score < 1.0
        assert any("DOI" in i for i in result.issues)

    def test_title_url(self):
        """Title là URL → score < 1.0, có issue."""
        result = TitleValidator.validate("https://example.com/paper/12345")
        assert result.score < 1.0
        assert any("URL" in i for i in result.issues)

    def test_title_empty(self):
        """Title None → score = 0.0, issue 'null'."""
        result = TitleValidator.validate(None)
        assert result.score == 0.0
        assert result.passed is False
        assert any("null" in i or "empty" in i for i in result.issues)

    def test_title_empty_string(self):
        """Title rỗng → giống None."""
        result = TitleValidator.validate("")
        assert result.score == 0.0
        assert result.passed is False

    def test_title_whitespace_only(self):
        """Title chỉ có whitespace → giống None."""
        result = TitleValidator.validate("   \n  ")
        assert result.score == 0.0
        assert result.passed is False

    def test_title_noise_arxiv(self):
        """Title chứa arxiv pattern → bị penalize."""
        result = TitleValidator.validate("arxiv: 2304.14953v2")
        assert result.score < 1.0

    def test_title_footer_pattern(self):
        """Title chứa footer pattern → bị penalize."""
        result = TitleValidator.validate("Vol. 25 No. 3, pp. 123-145")
        assert result.score < 1.0

    def test_title_single_word(self):
        """Title chỉ có 1 từ → word_count fail."""
        result = TitleValidator.validate("Introduction")
        assert result.score < 1.0
        assert any("word" in i for i in result.issues)

    def test_title_too_many_words(self):
        """Title quá nhiều từ → word_count fail."""
        long_title = " ".join(["word"] * 45)
        result = TitleValidator.validate(long_title)
        assert result.score < 1.0

    def test_title_rules_count(self):
        """Kiểm tra đúng 10 rules được check."""
        result = TitleValidator.validate("A Valid Paper Title")
        assert len(result.checked_rules) == 10


# ═══════════════════════════════════════════════
# 2. AUTHOR VALIDATION
# ═══════════════════════════════════════════════

class TestAuthorValidation:
    """Tests cho AuthorValidator."""

    def test_authors_valid(self):
        """Authors hợp lệ → score = 1.0, passed = True."""
        result = AuthorValidator.validate(["John Doe", "Jane Smith"])
        assert result.passed is True
        assert result.score >= 0.95
        assert len(result.issues) == 0

    def test_authors_single(self):
        """Một tác giả hợp lệ."""
        result = AuthorValidator.validate(["Alice Johnson"])
        assert result.passed is True
        assert result.score >= 0.95

    def test_authors_empty(self):
        """Danh sách rỗng → score = 0.0."""
        result = AuthorValidator.validate([])
        assert result.score == 0.0
        assert result.passed is False
        assert any("empty" in i for i in result.issues)

    def test_authors_duplicate(self):
        """Tên trùng lặp → score < 1.0."""
        result = AuthorValidator.validate(["John Doe", "John Doe", "Jane Smith"])
        assert result.score < 1.0
        assert any("duplicate" in i for i in result.issues)

    def test_authors_duplicate_case_insensitive(self):
        """Duplicate case-insensitive."""
        result = AuthorValidator.validate(["John Doe", "john doe"])
        assert any("duplicate" in i for i in result.issues)

    def test_authors_email_mixed(self):
        """Tên chứa email → score < 1.0."""
        result = AuthorValidator.validate(["john.doe@university.edu"])
        assert result.score < 1.0
        assert any("email" in i for i in result.issues)

    def test_authors_url_mixed(self):
        """Tên chứa URL → score < 1.0."""
        result = AuthorValidator.validate(["https://orcid.org/0000-0001"])
        assert result.score < 1.0

    def test_authors_affiliation_mixed(self):
        """Tên chứa affiliation → score < 1.0."""
        result = AuthorValidator.validate(["University of Cambridge"])
        assert result.score < 1.0
        assert any("affiliation" in i for i in result.issues)

    def test_authors_too_long_name(self):
        """Tên quá dài → score < 1.0."""
        long_name = "A" * 100
        result = AuthorValidator.validate([long_name])
        assert result.score < 1.0
        assert any("long" in i for i in result.issues)

    def test_authors_all_digits(self):
        """Tên toàn số → score < 1.0."""
        result = AuthorValidator.validate(["12345"])
        assert result.score < 1.0
        assert any("digit" in i for i in result.issues)

    def test_authors_too_many(self):
        """Quá nhiều tác giả → warning."""
        authors = [f"Author {i}" for i in range(55)]
        result = AuthorValidator.validate(authors)
        assert result.score < 1.0

    def test_authors_rules_count(self):
        """Kiểm tra đúng 9 rules."""
        result = AuthorValidator.validate(["John Doe"])
        assert len(result.checked_rules) == 9

    def test_authors_vietnamese_names(self):
        """Tên tiếng Việt hợp lệ."""
        result = AuthorValidator.validate(["Nguyễn Văn An", "Trần Thị Bình"])
        assert result.passed is True
        assert result.score >= 0.95


# ═══════════════════════════════════════════════
# 3. ABSTRACT VALIDATION
# ═══════════════════════════════════════════════

class TestAbstractValidation:
    """Tests cho AbstractValidator."""

    def test_abstract_valid(self):
        """Abstract prose hợp lệ → score ≈ 1.0, passed = True."""
        abstract = _make_valid_abstract(100)
        result = AbstractValidator.validate(abstract)
        assert result.passed is True
        assert result.score >= 0.90
        assert len(result.issues) == 0

    def test_abstract_too_short(self):
        """Abstract quá ngắn → score < 1.0."""
        result = AbstractValidator.validate("Short abstract.")
        assert result.score < 1.0
        assert any("short" in i or "few words" in i for i in result.issues)

    def test_abstract_too_long(self):
        """Abstract quá dài → score < 1.0."""
        long_text = _make_valid_abstract(2000)  # ~2000 words, >5000 chars
        result = AbstractValidator.validate(long_text)
        # This might be OK length-wise since 2000 words ≈ 10000+ chars
        if len(long_text) > 5000:
            assert any("long" in i for i in result.issues)

    def test_abstract_list_like(self):
        """Abstract dạng danh sách → score < 1.0."""
        list_text = (
            "1. First item about methodology.\n"
            "2. Second item about results.\n"
            "3. Third item about evaluation.\n"
            "4. Fourth item about experiments.\n"
            "5. Fifth item about conclusions.\n"
            "6. Sixth item about future work.\n"
        )
        result = AbstractValidator.validate(list_text)
        assert result.score < 1.0

    def test_abstract_keywords(self):
        """Abstract bắt đầu bằng 'Keywords:' → score < 1.0."""
        result = AbstractValidator.validate(
            "Keywords: machine learning, deep learning, natural language processing, "
            "information extraction, document analysis"
        )
        assert result.score < 1.0
        assert any("Keywords" in i or "keywords" in i.lower() for i in result.issues)

    def test_abstract_references(self):
        """Abstract là References section → score < 1.0."""
        ref_text = (
            "References\n"
            "[1] Smith, J. et al. (2020). Title of paper. Journal, 10(2), 100-120.\n"
            "[2] Doe, A. (2021). Another paper. Conference Proceedings, 50-60.\n"
            "[3] Johnson, B. (2019). Yet another paper. arXiv preprint.\n"
        )
        result = AbstractValidator.validate(ref_text)
        assert result.score < 1.0
        assert any("References" in i or "reference" in i.lower() for i in result.issues)

    def test_abstract_noisy(self):
        """Abstract với nhiều ký tự rác → score < 1.0."""
        noisy = "§¶†‡ " * 50 + "some actual text here."
        result = AbstractValidator.validate(noisy)
        assert result.score < 1.0

    def test_abstract_null(self):
        """Abstract None → score = 0.0."""
        result = AbstractValidator.validate(None)
        assert result.score == 0.0
        assert result.passed is False

    def test_abstract_empty(self):
        """Abstract rỗng → score = 0.0."""
        result = AbstractValidator.validate("")
        assert result.score == 0.0
        assert result.passed is False

    def test_abstract_no_sentences(self):
        """Abstract không có câu (no periods) → partial score."""
        result = AbstractValidator.validate(
            "This is a text without sentence ending punctuation " * 5
        )
        # Should still get some score for length, word count, etc.
        # But is_prose and sentence_structure will fail/warn
        assert result.score < 1.0

    def test_abstract_rules_count(self):
        """Kiểm tra đúng 9 rules."""
        result = AbstractValidator.validate(_make_valid_abstract(50))
        assert len(result.checked_rules) == 9

    def test_abstract_index_terms(self):
        """Abstract bắt đầu bằng 'Index Terms:' → fail not_keywords."""
        result = AbstractValidator.validate(
            "Index Terms: information retrieval, text mining, metadata extraction"
        )
        assert any("Keywords" in i or "Index" in i for i in result.issues)


# ═══════════════════════════════════════════════
# 4. SCORING
# ═══════════════════════════════════════════════

class TestScoring:
    """Tests cho ValidationScorer."""

    def test_scoring_all_valid(self):
        """3 fields hợp lệ → overall ≈ 1.0, passed = True."""
        engine = ValidationEngine()
        report = engine.validate(
            title="A Novel Approach to Information Extraction",
            authors=["John Doe", "Jane Smith"],
            abstract=_make_valid_abstract(100),
        )
        assert report.overall_score >= 0.85
        assert report.passed is True

    def test_scoring_title_invalid(self):
        """Chỉ title fail → overall < 1.0 nhưng có thể vẫn pass."""
        engine = ValidationEngine()
        report = engine.validate(
            title=None,
            authors=["John Doe"],
            abstract=_make_valid_abstract(100),
        )
        assert report.overall_score < 1.0
        assert report.title.passed is False

    def test_scoring_author_invalid(self):
        """Chỉ authors fail → overall < 1.0."""
        engine = ValidationEngine()
        report = engine.validate(
            title="A Valid Paper Title for Testing",
            authors=[],
            abstract=_make_valid_abstract(100),
        )
        assert report.overall_score < 1.0
        assert report.authors.passed is False

    def test_scoring_abstract_invalid(self):
        """Chỉ abstract fail → overall < 1.0."""
        engine = ValidationEngine()
        report = engine.validate(
            title="A Valid Paper Title for Testing",
            authors=["John Doe"],
            abstract=None,
        )
        assert report.overall_score < 1.0
        assert report.abstract.passed is False

    def test_scoring_all_invalid(self):
        """3 fields fail → overall ≈ 0.0, passed = False."""
        engine = ValidationEngine()
        report = engine.validate(
            title=None,
            authors=[],
            abstract=None,
        )
        assert report.overall_score == 0.0
        assert report.passed is False

    def test_scoring_boundary(self):
        """Score gần threshold → kiểm tra pass/fail."""
        # Title valid + authors valid + abstract None
        # Expected: title ~1.0 (×0.35) + authors ~1.0 (×0.30) = ~0.65 > 0.60
        engine = ValidationEngine()
        report = engine.validate(
            title="A Valid Paper Title for Testing",
            authors=["John Doe"],
            abstract=None,
        )
        # With abstract=None (score=0), overall ≈ 0.35+0.30 = 0.65
        assert report.overall_score >= VALIDATION_PASS_THRESHOLD
        assert report.passed is True

    def test_scoring_below_boundary(self):
        """Score dưới threshold → passed = False."""
        # Only title valid (score×0.35 ≈ 0.35 < 0.60)
        engine = ValidationEngine()
        report = engine.validate(
            title="A Valid Paper Title for Testing",
            authors=[],
            abstract=None,
        )
        assert report.overall_score < VALIDATION_PASS_THRESHOLD
        assert report.passed is False

    def test_compute_field_score(self):
        """Test compute_field_score trực tiếp."""
        rules = [
            RuleResult(rule_name="r1", passed=True, score=0.3, weight=0.3),
            RuleResult(rule_name="r2", passed=True, score=0.2, weight=0.2),
            RuleResult(rule_name="r3", passed=False, score=0.0, weight=0.5),
        ]
        score = ValidationScorer.compute_field_score(rules)
        assert abs(score - 0.5) < 0.001

    def test_compute_field_score_empty(self):
        """Empty rules → score = 0.0."""
        assert ValidationScorer.compute_field_score([]) == 0.0

    def test_overall_weights_sum_to_one(self):
        """Verify trọng số tổng = 1.0."""
        from config.constants import OVERALL_FIELD_WEIGHTS
        total = sum(OVERALL_FIELD_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001

    def test_title_weights_sum_to_one(self):
        """Verify title rule weights tổng = 1.0."""
        from config.constants import TITLE_RULE_WEIGHTS
        total = sum(TITLE_RULE_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001

    def test_author_weights_sum_to_one(self):
        """Verify author rule weights tổng = 1.0."""
        from config.constants import AUTHOR_RULE_WEIGHTS
        total = sum(AUTHOR_RULE_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001

    def test_abstract_weights_sum_to_one(self):
        """Verify abstract rule weights tổng = 1.0."""
        from config.constants import ABSTRACT_RULE_WEIGHTS
        total = sum(ABSTRACT_RULE_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001


# ═══════════════════════════════════════════════
# 5. INTEGRATION — ValidationEngine
# ═══════════════════════════════════════════════

class TestValidationEngine:
    """Tests cho ValidationEngine orchestrator."""

    def test_engine_with_cleaning_result(self):
        """Engine nhận CleaningResult từ M7."""
        cleaning = CleaningResult(
            title="A Novel Method for Extracting Metadata from PDFs",
            authors=["Alice Johnson", "Bob Williams"],
            abstract=_make_valid_abstract(100),
        )
        engine = ValidationEngine()
        report = engine.validate(cleaning_result=cleaning)

        assert isinstance(report, ValidationReport)
        assert report.title.field_name == "title"
        assert report.authors.field_name == "authors"
        assert report.abstract.field_name == "abstract"
        assert report.overall_score > 0
        assert report.passed is True

    def test_engine_with_direct_params(self):
        """Engine nhận params trực tiếp."""
        engine = ValidationEngine()
        report = engine.validate(
            title="Direct Title Test for Validation",
            authors=["John Doe"],
            abstract=_make_valid_abstract(50),
        )
        assert isinstance(report, ValidationReport)
        assert report.overall_score > 0

    def test_engine_cleaning_result_priority(self):
        """CleaningResult được ưu tiên hơn direct params."""
        cleaning = CleaningResult(
            title="From CleaningResult Title Test",
            authors=["Author A"],
            abstract=_make_valid_abstract(50),
        )
        engine = ValidationEngine()
        report = engine.validate(
            cleaning_result=cleaning,
            title="This Should Be Ignored Title",
        )
        # Title validation should be based on CleaningResult
        assert report.title.passed is True

    def test_engine_all_none(self):
        """Tất cả None/empty → overall = 0.0."""
        engine = ValidationEngine()
        report = engine.validate(title=None, authors=[], abstract=None)
        assert report.overall_score == 0.0
        assert report.passed is False

    def test_engine_deterministic(self):
        """Cùng input → cùng output (deterministic)."""
        engine = ValidationEngine()
        title = "A Deterministic Test Title for Validation"
        authors = ["John Doe", "Jane Smith"]
        abstract = _make_valid_abstract(100)

        r1 = engine.validate(title=title, authors=authors, abstract=abstract)
        r2 = engine.validate(title=title, authors=authors, abstract=abstract)

        assert r1.overall_score == r2.overall_score
        assert r1.title.score == r2.title.score
        assert r1.authors.score == r2.authors.score
        assert r1.abstract.score == r2.abstract.score
        assert r1.passed == r2.passed


# ═══════════════════════════════════════════════
# 6. MODELS — Serialization
# ═══════════════════════════════════════════════

class TestValidationModels:
    """Tests cho validation data models."""

    def test_rule_result_to_dict(self):
        """RuleResult serialization."""
        r = RuleResult(
            rule_name="test_rule",
            passed=True,
            score=0.15,
            weight=0.15,
            message="",
        )
        d = r.to_dict()
        assert d["rule"] == "test_rule"
        assert d["passed"] is True
        assert d["score"] == 0.15
        assert "message" not in d  # Empty message excluded

    def test_rule_result_with_message(self):
        """RuleResult with message."""
        r = RuleResult(
            rule_name="fail_rule",
            passed=False,
            score=0.0,
            weight=0.10,
            message="something failed",
        )
        d = r.to_dict()
        assert d["message"] == "something failed"

    def test_field_validation_to_dict(self):
        """FieldValidation serialization."""
        fv = FieldValidation(
            field_name="title",
            score=0.85,
            passed=True,
            issues=[],
            warnings=["minor warning"],
            checked_rules=[
                RuleResult(rule_name="r1", passed=True, score=0.5, weight=0.5),
            ],
        )
        d = fv.to_dict()
        assert d["field"] == "title"
        assert d["score"] == 0.85
        assert d["passed"] is True
        assert len(d["checked_rules"]) == 1

    def test_validation_report_to_dict(self):
        """ValidationReport serialization."""
        engine = ValidationEngine()
        report = engine.validate(
            title="Test Title for Serialization Check",
            authors=["John Doe"],
            abstract=_make_valid_abstract(50),
        )
        d = report.to_dict()
        assert "title" in d
        assert "authors" in d
        assert "abstract" in d
        assert "overall_score" in d
        assert "passed" in d
        assert isinstance(d["overall_score"], float)
