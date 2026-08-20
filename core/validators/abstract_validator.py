"""
core/validators/abstract_validator.py
AbstractValidator — 9 rules kiểm tra chất lượng abstract đã trích xuất.

Rules:
 1. not_null              — abstract không None/empty
 2. length_ok             — độ dài [80, 5000] ký tự
 3. is_prose              — có cấu trúc prose (câu văn, có dấu chấm)
 4. word_count_ok         — ≥ 20 từ
 5. not_list              — không phải danh sách (bullet/numbered list)
 6. not_references        — không phải References/Bibliography section
 7. not_keywords          — không bắt đầu bằng "Keywords:" / "Index Terms:"
 8. low_garbage           — tỷ lệ ký tự rác thấp
 9. sentence_structure_ok — cấu trúc câu hợp lý (avg words/sentence ≥ 3)
"""

from __future__ import annotations

import re
import logging

from core.validators.models import RuleResult, FieldValidation
from config.constants import (
    ABSTRACT_RULE_WEIGHTS,
    VALID_ABSTRACT_MIN_LENGTH,
    VALID_ABSTRACT_MAX_LENGTH,
    VALID_ABSTRACT_MIN_WORDS,
    VALID_ABSTRACT_MIN_SENTENCE_WORDS,
    VALID_ABSTRACT_GARBAGE_CHAR_THRESHOLD,
    VALID_ABSTRACT_NEWLINE_RATIO_WARN,
    VALIDATION_PASS_THRESHOLD,
    BULLET_LIST_PATTERN,
    REFERENCES_START_PATTERN,
    KEYWORDS_START_PATTERN,
)

logger = logging.getLogger(__name__)

# Sentence-ending punctuation pattern
_SENTENCE_END = re.compile(r"[.!?]\s")


class AbstractValidator:
    """
    Validate abstract đã trích xuất bằng 9 deterministic rules.

    Input: abstract string (cleaned, from M7).
    Output: FieldValidation với score, issues, warnings.

    NOTE: Validator CHỈ đánh giá. Không sửa abstract.
    """

    @staticmethod
    def validate(abstract: str | None) -> FieldValidation:
        """
        Chạy 9 rules trên abstract.

        Args:
            abstract: Abstract đã clean từ CleaningResult. None nếu không có.

        Returns:
            FieldValidation với score [0.0, 1.0].
        """
        weights = ABSTRACT_RULE_WEIGHTS
        rules: list[RuleResult] = []
        issues: list[str] = []
        warnings: list[str] = []

        # ── Rule 1: not_null ──
        r = AbstractValidator._check_not_null(abstract, weights["not_null"])
        rules.append(r)
        if not r.passed:
            issues.append(r.message)
            # Short-circuit
            for rule_name in list(weights.keys())[1:]:
                rules.append(RuleResult(
                    rule_name=rule_name,
                    passed=False,
                    score=0.0,
                    weight=weights[rule_name],
                    message="skipped (abstract is null)",
                ))
            return FieldValidation(
                field_name="abstract",
                score=0.0,
                passed=False,
                issues=issues,
                warnings=warnings,
                checked_rules=rules,
            )

        assert abstract is not None
        stripped = abstract.strip()

        # ── Rule 2: length_ok ──
        r = AbstractValidator._check_length(stripped, weights["length_ok"])
        rules.append(r)
        if not r.passed:
            issues.append(r.message)

        # ── Rule 3: is_prose ──
        r = AbstractValidator._check_is_prose(stripped, weights["is_prose"])
        rules.append(r)
        if not r.passed:
            issues.append(r.message)

        # ── Rule 4: word_count_ok ──
        r = AbstractValidator._check_word_count(stripped, weights["word_count_ok"])
        rules.append(r)
        if not r.passed:
            issues.append(r.message)

        # ── Rule 5: not_list ──
        r = AbstractValidator._check_not_list(stripped, weights["not_list"])
        rules.append(r)
        if not r.passed:
            issues.append(r.message)

        # ── Rule 6: not_references ──
        r = AbstractValidator._check_not_references(
            stripped, weights["not_references"]
        )
        rules.append(r)
        if not r.passed:
            issues.append(r.message)

        # ── Rule 7: not_keywords ──
        r = AbstractValidator._check_not_keywords(stripped, weights["not_keywords"])
        rules.append(r)
        if not r.passed:
            issues.append(r.message)

        # ── Rule 8: low_garbage ──
        r = AbstractValidator._check_low_garbage(stripped, weights["low_garbage"])
        rules.append(r)
        if not r.passed:
            issues.append(r.message)

        # ── Rule 9: sentence_structure_ok ──
        r = AbstractValidator._check_sentence_structure(
            stripped, weights["sentence_structure_ok"]
        )
        rules.append(r)
        if not r.passed:
            warnings.append(r.message)  # Warning, not critical

        # Check newline ratio for additional warning
        if stripped:
            newline_ratio = stripped.count("\n") / len(stripped)
            if newline_ratio > VALID_ABSTRACT_NEWLINE_RATIO_WARN:
                warnings.append(
                    f"abstract newline ratio is high ({newline_ratio:.4f})"
                )

        # Compute total score
        score = sum(r.score for r in rules)
        score = min(score, 1.0)

        logger.debug(
            f"Abstract validation: score={score:.4f} "
            f"issues={len(issues)} warnings={len(warnings)}"
        )

        return FieldValidation(
            field_name="abstract",
            score=score,
            passed=score >= VALIDATION_PASS_THRESHOLD,
            issues=issues,
            warnings=warnings,
            checked_rules=rules,
        )

    # ── Individual Rule Checks ──

    @staticmethod
    def _check_not_null(abstract: str | None, weight: float) -> RuleResult:
        """Abstract không None/empty."""
        if abstract is None or not abstract.strip():
            return RuleResult(
                rule_name="not_null",
                passed=False,
                score=0.0,
                weight=weight,
                message="abstract is null or empty",
            )
        return RuleResult(
            rule_name="not_null", passed=True, score=weight, weight=weight
        )

    @staticmethod
    def _check_length(text: str, weight: float) -> RuleResult:
        """Độ dài trong [VALID_ABSTRACT_MIN_LENGTH, VALID_ABSTRACT_MAX_LENGTH]."""
        length = len(text)
        if length < VALID_ABSTRACT_MIN_LENGTH:
            return RuleResult(
                rule_name="length_ok",
                passed=False,
                score=0.0,
                weight=weight,
                message=(
                    f"abstract too short ({length} chars, "
                    f"min {VALID_ABSTRACT_MIN_LENGTH})"
                ),
            )
        if length > VALID_ABSTRACT_MAX_LENGTH:
            return RuleResult(
                rule_name="length_ok",
                passed=False,
                score=0.0,
                weight=weight,
                message=(
                    f"abstract too long ({length} chars, "
                    f"max {VALID_ABSTRACT_MAX_LENGTH})"
                ),
            )
        return RuleResult(
            rule_name="length_ok", passed=True, score=weight, weight=weight
        )

    @staticmethod
    def _check_is_prose(text: str, weight: float) -> RuleResult:
        """
        Abstract có cấu trúc prose — có câu văn kết thúc bằng dấu chấm.

        Heuristic: ≥ 2 sentence-ending punctuations (., !, ?)
        """
        sentences = _SENTENCE_END.findall(text)
        # Also count ending with period at the very end
        if text.rstrip().endswith((".","!","?")):
            sentence_count = len(sentences) + 1
        else:
            sentence_count = len(sentences)

        if sentence_count >= 2:
            return RuleResult(
                rule_name="is_prose", passed=True, score=weight, weight=weight
            )
        if sentence_count == 1:
            return RuleResult(
                rule_name="is_prose",
                passed=True,
                score=weight * 0.5,
                weight=weight,
                message="abstract has only 1 sentence (partial score)",
            )
        return RuleResult(
            rule_name="is_prose",
            passed=False,
            score=0.0,
            weight=weight,
            message="abstract has no prose structure (no sentence-ending punctuation)",
        )

    @staticmethod
    def _check_word_count(text: str, weight: float) -> RuleResult:
        """Số từ ≥ VALID_ABSTRACT_MIN_WORDS."""
        word_count = len(text.split())
        if word_count < VALID_ABSTRACT_MIN_WORDS:
            return RuleResult(
                rule_name="word_count_ok",
                passed=False,
                score=0.0,
                weight=weight,
                message=(
                    f"abstract has too few words ({word_count}, "
                    f"min {VALID_ABSTRACT_MIN_WORDS})"
                ),
            )
        return RuleResult(
            rule_name="word_count_ok", passed=True, score=weight, weight=weight
        )

    @staticmethod
    def _check_not_list(text: str, weight: float) -> RuleResult:
        """
        Abstract không phải danh sách (bullet/numbered list).

        Heuristic: nếu > 50% dòng bắt đầu bằng bullet/number → fail.
        """
        lines = [line for line in text.split("\n") if line.strip()]
        if not lines:
            return RuleResult(
                rule_name="not_list", passed=True, score=weight, weight=weight
            )

        list_matches = BULLET_LIST_PATTERN.findall(text)
        list_ratio = len(list_matches) / len(lines) if lines else 0.0

        if list_ratio > 0.50:
            return RuleResult(
                rule_name="not_list",
                passed=False,
                score=0.0,
                weight=weight,
                message=(
                    f"abstract appears to be a list "
                    f"({len(list_matches)}/{len(lines)} lines are list items)"
                ),
            )
        return RuleResult(
            rule_name="not_list", passed=True, score=weight, weight=weight
        )

    @staticmethod
    def _check_not_references(text: str, weight: float) -> RuleResult:
        """Abstract không phải References/Bibliography section."""
        if REFERENCES_START_PATTERN.search(text):
            return RuleResult(
                rule_name="not_references",
                passed=False,
                score=0.0,
                weight=weight,
                message="abstract matches References/Bibliography pattern",
            )
        return RuleResult(
            rule_name="not_references", passed=True, score=weight, weight=weight
        )

    @staticmethod
    def _check_not_keywords(text: str, weight: float) -> RuleResult:
        """Abstract không bắt đầu bằng 'Keywords:' / 'Index Terms:'."""
        if KEYWORDS_START_PATTERN.match(text):
            return RuleResult(
                rule_name="not_keywords",
                passed=False,
                score=0.0,
                weight=weight,
                message="abstract starts with Keywords/Index Terms pattern",
            )
        return RuleResult(
            rule_name="not_keywords", passed=True, score=weight, weight=weight
        )

    @staticmethod
    def _check_low_garbage(text: str, weight: float) -> RuleResult:
        """
        Tỷ lệ ký tự rác (non-alphanumeric, non-space, non-punctuation) thấp.

        Garbage chars: control chars, suspicious symbols, etc.
        Normal punctuation (.,;:!?'-\"()[]{}/) is excluded from garbage.
        """
        if not text:
            return RuleResult(
                rule_name="low_garbage", passed=True, score=weight, weight=weight
            )

        normal_chars = set(
            "abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "0123456789"
            " \t\n\r"
            ".,;:!?'\"-()[]{}/<>@#$%&*+=~`^|\\"
        )
        # Allow Vietnamese and other Unicode alphabetic chars
        garbage_count = sum(
            1 for c in text
            if c not in normal_chars and not c.isalpha() and not c.isspace()
        )
        garbage_ratio = garbage_count / len(text)

        if garbage_ratio > VALID_ABSTRACT_GARBAGE_CHAR_THRESHOLD:
            return RuleResult(
                rule_name="low_garbage",
                passed=False,
                score=0.0,
                weight=weight,
                message=(
                    f"abstract has high garbage char ratio "
                    f"({garbage_ratio:.4f}, threshold "
                    f"{VALID_ABSTRACT_GARBAGE_CHAR_THRESHOLD})"
                ),
            )
        return RuleResult(
            rule_name="low_garbage", passed=True, score=weight, weight=weight
        )

    @staticmethod
    def _check_sentence_structure(text: str, weight: float) -> RuleResult:
        """
        Cấu trúc câu hợp lý: avg words per sentence ≥ threshold.

        Split by sentence-ending punctuation, compute average word count.
        """
        # Split into sentences (simple heuristic)
        sentences = re.split(r"[.!?]+", text)
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            return RuleResult(
                rule_name="sentence_structure_ok",
                passed=False,
                score=0.0,
                weight=weight,
                message="no sentences detected in abstract",
            )

        word_counts = [len(s.split()) for s in sentences]
        avg_words = sum(word_counts) / len(word_counts)

        if avg_words >= VALID_ABSTRACT_MIN_SENTENCE_WORDS:
            return RuleResult(
                rule_name="sentence_structure_ok",
                passed=True,
                score=weight,
                weight=weight,
            )

        return RuleResult(
            rule_name="sentence_structure_ok",
            passed=False,
            score=0.0,
            weight=weight,
            message=(
                f"average sentence length too short "
                f"({avg_words:.1f} words, min {VALID_ABSTRACT_MIN_SENTENCE_WORDS})"
            ),
        )
