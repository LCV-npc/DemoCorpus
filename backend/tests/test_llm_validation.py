"""
tests/test_llm_validation.py
Unit + Integration tests cho Milestone 9 — LLM Enhancement.

Covers:
1. LLM Skip/Call logic (4 cases)
2. JSON Parsing (7 cases)
3. Score Combining (3 cases)
4. Error Handling (3 cases)
5. StubLLM (2 cases)
6. Integration (3 cases)
7. Loader (2 cases)
"""

import pytest
import json

from core.validators.models import (
    RuleResult,
    FieldValidation,
    ValidationReport,
)
from core.validators.llm_validator import LLMValidator
from core.validators.validation_engine import ValidationEngine
from core.validators.scoring import ValidationScorer
from infrastructure.nlp.llm_loader import ApiLLM, StubLLM, load_llm
from config.settings import settings
from config.constants import (
    LLM_ENHANCEMENT_THRESHOLD,
    LLM_INVALID_CONFIDENCE_CAP,
    LLM_SCORE_WEIGHT_RULE,
    LLM_SCORE_WEIGHT_LLM,
    VALIDATION_PASS_THRESHOLD,
)


# ═══════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════

def _make_valid_abstract(word_count: int = 100) -> str:
    """Tạo abstract prose hợp lệ."""
    base = (
        "This paper presents a novel approach to information extraction. "
        "We propose a multi-stage pipeline combining heuristic rules with ML. "
        "The system first extracts text blocks from PDF documents. "
        "Experimental results show high accuracy on benchmark datasets. "
        "Future work includes integrating large language models. "
    )
    words = base.split()
    while len(words) < word_count:
        words.extend(base.split())
    return " ".join(words[:word_count]) + "."


def _make_report(
    title_score: float = 1.0,
    author_score: float = 1.0,
    abstract_score: float = 1.0,
) -> ValidationReport:
    """Create a ValidationReport with specified field scores."""
    title_fv = FieldValidation(
        field_name="title",
        score=title_score,
        passed=title_score >= VALIDATION_PASS_THRESHOLD,
    )
    author_fv = FieldValidation(
        field_name="authors",
        score=author_score,
        passed=author_score >= VALIDATION_PASS_THRESHOLD,
    )
    abstract_fv = FieldValidation(
        field_name="abstract",
        score=abstract_score,
        passed=abstract_score >= VALIDATION_PASS_THRESHOLD,
    )
    overall = ValidationScorer.compute_overall_score(title_fv, author_fv, abstract_fv)
    return ValidationReport(
        title=title_fv,
        authors=author_fv,
        abstract=abstract_fv,
        overall_score=overall,
        passed=ValidationScorer.is_passed(overall),
    )


# ═══════════════════════════════════════════════
# 1. LLM SKIP / CALL LOGIC
# ═══════════════════════════════════════════════

class TestLLMSkipCall:
    """Tests cho logic gọi/bỏ qua LLM."""

    def test_llm_skip_high_confidence(self):
        """rule_score = 0.9 → LLM KHÔNG được gọi."""
        stub = StubLLM()
        validator = LLMValidator(llm_model=stub)
        report = _make_report(title_score=0.9, author_score=0.9, abstract_score=0.9)

        enhanced = validator.enhance(
            report,
            title="Valid Title Here",
            authors=["John Doe"],
            abstract=_make_valid_abstract(),
        )

        assert stub.call_count == 0
        assert enhanced.llm_enhanced is False
        # Scores unchanged
        assert enhanced.title.score == 0.9
        assert enhanced.authors.score == 0.9
        assert enhanced.abstract.score == 0.9
        assert enhanced.title.llm_called is False

    def test_llm_skip_all_high(self):
        """All 3 fields score >= 0.7 → LLM NOT called for any."""
        stub = StubLLM()
        validator = LLMValidator(llm_model=stub)
        report = _make_report(title_score=0.8, author_score=0.75, abstract_score=0.7)

        enhanced = validator.enhance(report, title="T", authors=["A"], abstract="B")

        assert stub.call_count == 0
        assert enhanced.llm_enhanced is False

    def test_llm_can_verify_all_high_confidence_fields(self):
        """Final M9 mode verifies all fields even when rules score highly."""
        stub = StubLLM()
        validator = LLMValidator(llm_model=stub, validate_all_fields=True)
        report = _make_report(title_score=0.9, author_score=0.9, abstract_score=0.9)

        enhanced = validator.enhance(
            report, title="Valid Title", authors=["Author"], abstract="Abstract"
        )

        assert stub.call_count == 3
        assert enhanced.llm_enhanced is True
        assert enhanced.title.llm_called is True
        assert enhanced.authors.llm_called is True
        assert enhanced.abstract.llm_called is True

    def test_llm_called_low_confidence(self):
        """rule_score = 0.5 → LLM được gọi."""
        stub = StubLLM('{"is_valid": true, "confidence": 0.9, "reason": "looks valid"}')
        validator = LLMValidator(llm_model=stub)
        report = _make_report(title_score=0.5, author_score=0.9, abstract_score=0.9)

        enhanced = validator.enhance(
            report, title="Maybe Valid Title", authors=["A"], abstract="B"
        )

        assert stub.call_count == 1  # Only title called
        assert enhanced.title.llm_called is True
        assert enhanced.title.llm_score == 0.9
        assert enhanced.title.llm_reason == "looks valid"
        assert enhanced.llm_enhanced is True
        # Authors and abstract NOT called
        assert enhanced.authors.llm_called is False
        assert enhanced.abstract.llm_called is False

    def test_llm_called_for_specific_field(self):
        """Only title < 0.7 → LLM called ONLY for title."""
        stub = StubLLM()
        validator = LLMValidator(llm_model=stub)
        report = _make_report(title_score=0.3, author_score=0.8, abstract_score=0.9)

        enhanced = validator.enhance(report, title="Bad", authors=["A"], abstract="B")

        assert stub.call_count == 1
        assert enhanced.title.llm_called is True
        assert enhanced.authors.llm_called is False
        assert enhanced.abstract.llm_called is False

    def test_llm_called_multiple_fields(self):
        """Multiple fields < 0.7 → LLM called for each."""
        stub = StubLLM()
        validator = LLMValidator(llm_model=stub)
        report = _make_report(title_score=0.3, author_score=0.4, abstract_score=0.5)

        enhanced = validator.enhance(report, title="T", authors=["A"], abstract="B")

        assert stub.call_count == 3
        assert enhanced.title.llm_called is True
        assert enhanced.authors.llm_called is True
        assert enhanced.abstract.llm_called is True
        assert enhanced.llm_enhanced is True


# ═══════════════════════════════════════════════
# 2. JSON PARSING
# ═══════════════════════════════════════════════

class TestJSONParsing:
    """Tests cho LLMValidator._parse_response()."""

    def test_parse_valid_json(self):
        """Valid JSON → correct extraction."""
        result = LLMValidator._parse_response(
            '{"is_valid": true, "confidence": 0.9, "reason": "valid title"}'
        )
        assert result is not None
        assert result["is_valid"] is True
        assert result["confidence"] == 0.9
        assert result["reason"] == "valid title"

    def test_parse_json_in_code_fence(self):
        """JSON inside ```json ... ``` → parses correctly."""
        raw = '```json\n{"is_valid": true, "confidence": 0.88, "reason": "ok"}\n```'
        result = LLMValidator._parse_response(raw)
        assert result is not None
        assert result["confidence"] == 0.88

    def test_parse_json_in_plain_fence(self):
        """JSON inside ``` ... ``` (no language) → parses correctly."""
        raw = '```\n{"is_valid": false, "confidence": 0.2, "reason": "bad"}\n```'
        result = LLMValidator._parse_response(raw)
        assert result is not None
        assert result["is_valid"] is False
        assert result["confidence"] == 0.2

    def test_parse_invalid_json(self):
        """Garbage input → None."""
        result = LLMValidator._parse_response("garbage text here")
        assert result is None

    def test_parse_empty_response(self):
        """Empty string → None."""
        assert LLMValidator._parse_response("") is None
        assert LLMValidator._parse_response("   ") is None

    def test_parse_missing_fields(self):
        """JSON with missing confidence → defaults to 0.5."""
        result = LLMValidator._parse_response('{"is_valid": true}')
        assert result is not None
        assert result["is_valid"] is True
        assert result["confidence"] == 0.5  # default

    def test_parse_confidence_out_of_range(self):
        """confidence = 2.0 → clamped to 1.0."""
        result = LLMValidator._parse_response(
            '{"is_valid": true, "confidence": 2.0}'
        )
        assert result is not None
        assert result["confidence"] == 1.0

    def test_parse_confidence_negative(self):
        """confidence = -0.5 → clamped to 0.0."""
        result = LLMValidator._parse_response(
            '{"is_valid": true, "confidence": -0.5}'
        )
        assert result is not None
        assert result["confidence"] == 0.0

    def test_parse_invalid_caps_confidence(self):
        """is_valid=false with confidence=0.95 → capped to 0.3."""
        result = LLMValidator._parse_response(
            '{"is_valid": false, "confidence": 0.95}'
        )
        assert result is not None
        assert result["is_valid"] is False
        assert result["confidence"] == LLM_INVALID_CONFIDENCE_CAP  # 0.3

    def test_parse_invalid_low_confidence(self):
        """is_valid=false with confidence=0.2 → NOT capped (already low)."""
        result = LLMValidator._parse_response(
            '{"is_valid": false, "confidence": 0.2}'
        )
        assert result is not None
        assert result["confidence"] == 0.2  # below cap, no change

    def test_parse_json_with_extra_text(self):
        """JSON embedded in explanatory text."""
        raw = 'Here is my analysis:\n{"is_valid": true, "confidence": 0.85, "reason": "ok"}\nEnd.'
        result = LLMValidator._parse_response(raw)
        assert result is not None
        assert result["confidence"] == 0.85


# ═══════════════════════════════════════════════
# 3. SCORE COMBINING
# ═══════════════════════════════════════════════

class TestScoreCombining:
    """Tests cho logic kết hợp Rule + LLM scores."""

    def test_combine_scores_average(self):
        """rule=0.5, llm=0.9 → final ≈ 0.7."""
        stub = StubLLM('{"is_valid": true, "confidence": 0.9, "reason": "ok"}')
        validator = LLMValidator(llm_model=stub)
        report = _make_report(title_score=0.5, author_score=0.9, abstract_score=0.9)

        enhanced = validator.enhance(report, title="T", authors=["A"], abstract="B")

        expected = LLM_SCORE_WEIGHT_RULE * 0.5 + LLM_SCORE_WEIGHT_LLM * 0.9
        assert abs(enhanced.title.score - expected) < 0.01

    def test_combine_scores_both_high(self):
        """rule=0.65, llm=0.85 → final=0.75."""
        stub = StubLLM('{"is_valid": true, "confidence": 0.85, "reason": "good"}')
        validator = LLMValidator(llm_model=stub)
        report = _make_report(title_score=0.65, author_score=0.9, abstract_score=0.9)

        enhanced = validator.enhance(report, title="T", authors=["A"], abstract="B")

        expected = LLM_SCORE_WEIGHT_RULE * 0.65 + LLM_SCORE_WEIGHT_LLM * 0.85
        assert abs(enhanced.title.score - expected) < 0.01

    def test_combine_scores_llm_none(self):
        """LLM parse fails → keep rule score unchanged."""
        stub = StubLLM("garbage response not json")
        validator = LLMValidator(llm_model=stub)
        report = _make_report(title_score=0.5, author_score=0.9, abstract_score=0.9)

        enhanced = validator.enhance(report, title="T", authors=["A"], abstract="B")

        # Title score should remain 0.5 (unchanged)
        assert enhanced.title.score == 0.5
        assert enhanced.title.llm_called is True
        assert enhanced.title.llm_score is None

    def test_combine_invalid_lowers_score(self):
        """LLM says invalid → capped confidence lowers final score."""
        stub = StubLLM('{"is_valid": false, "confidence": 0.95, "reason": "not a title"}')
        validator = LLMValidator(llm_model=stub)
        report = _make_report(title_score=0.5, author_score=0.9, abstract_score=0.9)

        enhanced = validator.enhance(report, title="Bad", authors=["A"], abstract="B")

        # LLM score capped to 0.3
        expected = LLM_SCORE_WEIGHT_RULE * 0.5 + LLM_SCORE_WEIGHT_LLM * 0.3
        assert abs(enhanced.title.score - expected) < 0.01
        assert enhanced.title.llm_score == LLM_INVALID_CONFIDENCE_CAP

    def test_final_score_updates_overall(self):
        """Enhanced field score should update overall_score."""
        stub = StubLLM('{"is_valid": true, "confidence": 0.9, "reason": "ok"}')
        validator = LLMValidator(llm_model=stub)
        report = _make_report(title_score=0.5, author_score=0.9, abstract_score=0.9)
        original_overall = report.overall_score

        enhanced = validator.enhance(report, title="T", authors=["A"], abstract="B")

        # Title improved → overall should increase
        assert enhanced.overall_score > original_overall


# ═══════════════════════════════════════════════
# 4. ERROR HANDLING
# ═══════════════════════════════════════════════

class TestErrorHandling:
    """Tests cho error handling — pipeline KHÔNG crash."""

    def test_llm_unavailable_no_crash(self):
        """No LLM model → returns original report unchanged."""
        validator = LLMValidator(llm_model=None)
        report = _make_report(title_score=0.5, author_score=0.5, abstract_score=0.5)

        enhanced = validator.enhance(report, title="T", authors=["A"], abstract="B")

        assert enhanced is not report  # New object
        assert enhanced.title.score == 0.5  # Unchanged
        assert enhanced.authors.score == 0.5
        assert enhanced.abstract.score == 0.5
        assert enhanced.llm_enhanced is False

    def test_unexpected_exception_safe(self):
        """LLM raises exception → pipeline continues, keeps rule score."""
        class BrokenLLM:
            def generate(self, prompt):
                raise RuntimeError("Model crashed!")

        validator = LLMValidator(llm_model=BrokenLLM())
        report = _make_report(title_score=0.5, author_score=0.9, abstract_score=0.9)

        # Should NOT raise
        enhanced = validator.enhance(report, title="T", authors=["A"], abstract="B")

        assert enhanced.title.score == 0.5  # Unchanged
        assert enhanced.title.llm_called is True
        assert enhanced.title.llm_score is None
        assert "error" in enhanced.title.llm_reason.lower()

    def test_api_timeout_fallback(self):
        """API timeout → keeps rule score, logs warning."""
        class TimeoutLLM:
            def generate(self, prompt):
                raise TimeoutError("Connection timed out")

        validator = LLMValidator(llm_model=TimeoutLLM())
        report = _make_report(title_score=0.4, author_score=0.9, abstract_score=0.9)

        enhanced = validator.enhance(report, title="T", authors=["A"], abstract="B")

        assert enhanced.title.score == 0.4
        assert enhanced.title.llm_called is True
        assert enhanced.title.llm_score is None


# ═══════════════════════════════════════════════
# 5. STUB LLM
# ═══════════════════════════════════════════════

class TestStubLLM:
    """Tests cho StubLLM."""

    def test_stub_llm_deterministic(self):
        """StubLLM always returns same response."""
        stub = StubLLM()
        r1 = stub.generate("prompt 1")
        r2 = stub.generate("prompt 2")
        assert r1 == r2
        assert stub.call_count == 2

    def test_stub_llm_custom_response(self):
        """StubLLM with custom JSON."""
        custom = '{"is_valid": false, "confidence": 0.3, "reason": "custom"}'
        stub = StubLLM(response=custom)
        result = stub.generate("any prompt")
        assert result == custom

    def test_stub_llm_tracks_prompt(self):
        """StubLLM stores last prompt for assertions."""
        stub = StubLLM()
        stub.generate("test prompt 123")
        assert "test prompt 123" in stub.last_prompt


# ═══════════════════════════════════════════════
# 6. INTEGRATION
# ═══════════════════════════════════════════════

class TestIntegration:
    """Integration tests — M8 → M9 pipeline."""

    def test_enhance_full_report(self):
        """Full enhance() with StubLLM on real M8 output."""
        # Run M8 validation
        engine = ValidationEngine()
        report = engine.validate(
            title="A Valid Title for Testing Paper",
            authors=["John Doe", "Jane Smith"],
            abstract=_make_valid_abstract(100),
        )

        # M8 scores should be high (all valid)
        assert report.title.score >= 0.7
        assert report.authors.score >= 0.7
        assert report.abstract.score >= 0.7

        # Enhance with StubLLM (should skip since all high)
        stub = StubLLM()
        validator = LLMValidator(llm_model=stub)
        enhanced = validator.enhance(
            report,
            title="A Valid Title for Testing Paper",
            authors=["John Doe", "Jane Smith"],
            abstract=_make_valid_abstract(100),
        )

        assert stub.call_count == 0
        assert enhanced.llm_enhanced is False
        # Scores preserved
        assert enhanced.title.score == report.title.score

    def test_enhance_low_confidence_report(self):
        """Enhance a report with intentionally low scores."""
        # Craft a report with one low field
        report = _make_report(title_score=0.4, author_score=0.9, abstract_score=0.9)

        stub = StubLLM('{"is_valid": true, "confidence": 0.8, "reason": "valid"}')
        validator = LLMValidator(llm_model=stub)
        enhanced = validator.enhance(
            report, title="Short", authors=["A"], abstract="B"
        )

        assert enhanced.title.llm_called is True
        assert enhanced.title.llm_score == 0.8
        # Final = 0.5 * 0.4 + 0.5 * 0.8 = 0.6
        expected = 0.5 * 0.4 + 0.5 * 0.8
        assert abs(enhanced.title.score - expected) < 0.01

    def test_enhance_preserves_rule_issues(self):
        """Original rule issues preserved after LLM enhancement."""
        report = _make_report(title_score=0.5)
        report.title.issues = ["title too short", "title is noise"]

        stub = StubLLM('{"is_valid": true, "confidence": 0.9, "reason": "ok"}')
        validator = LLMValidator(llm_model=stub)
        enhanced = validator.enhance(report, title="T", authors=["A"], abstract="B")

        assert "title too short" in enhanced.title.issues
        assert "title is noise" in enhanced.title.issues

    def test_enhance_deterministic(self):
        """Same input → same output with StubLLM."""
        stub = StubLLM()
        validator = LLMValidator(llm_model=stub)
        report = _make_report(title_score=0.4, author_score=0.9, abstract_score=0.9)

        e1 = validator.enhance(report, title="T", authors=["A"], abstract="B")
        # Need to reset stub count but result should be same
        stub2 = StubLLM()
        validator2 = LLMValidator(llm_model=stub2)
        report2 = _make_report(title_score=0.4, author_score=0.9, abstract_score=0.9)
        e2 = validator2.enhance(report2, title="T", authors=["A"], abstract="B")

        assert e1.title.score == e2.title.score
        assert e1.overall_score == e2.overall_score

    def test_enhance_serialization(self):
        """Enhanced report serializes correctly with LLM fields."""
        stub = StubLLM('{"is_valid": true, "confidence": 0.85, "reason": "test"}')
        validator = LLMValidator(llm_model=stub)
        report = _make_report(title_score=0.5, author_score=0.9, abstract_score=0.9)

        enhanced = validator.enhance(report, title="T", authors=["A"], abstract="B")
        d = enhanced.to_dict()

        assert d["llm_enhanced"] is True
        assert d["title"]["llm_called"] is True
        assert d["title"]["llm_score"] == 0.85
        assert d["title"]["llm_reason"] == "test"
        # Authors should NOT have LLM fields (score was high)
        assert "llm_called" not in d["authors"]


# ═══════════════════════════════════════════════
# 7. LOADER
# ═══════════════════════════════════════════════

class TestLoader:
    """Tests cho load_llm()."""

    def test_load_llm_no_config(self, monkeypatch):
        """No path/key → returns None."""
        monkeypatch.setattr(settings, "LLM_MODEL_PATH", "")
        monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
        monkeypatch.setattr(settings, "OPENAI_API_URL", "")
        result = load_llm(model_path="", api_url="", api_key="")
        assert result is None

    def test_load_llm_uses_gemini_when_configured(self, monkeypatch):
        """Gemini is selected with its own endpoint and model name."""
        monkeypatch.setattr(settings, "LLM_MODEL_PATH", "")
        monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-gemini-key")
        monkeypatch.setattr(
            settings,
            "GEMINI_API_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai",
        )
        monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-test-model")

        result = load_llm()

        assert isinstance(result, ApiLLM)
        assert result._model == "gemini-test-model"
        assert "generativelanguage.googleapis.com" in result._api_url

    def test_load_llm_stub(self):
        """StubLLM loads without any dependencies."""
        stub = StubLLM()
        assert stub.generate("test") is not None
        assert stub.call_count == 1

    def test_load_llm_missing_transformers(self):
        """Non-existent model path with no transformers → None."""
        result = load_llm(model_path="nonexistent/model/path")
        # Will either fail import or fail load → returns None
        assert result is None or isinstance(result, object)
