"""
core/validators/title_validator.py
TitleValidator — 10 rules kiểm tra chất lượng title đã trích xuất.

Mỗi rule trả về RuleResult với score = weight (nếu pass) hoặc 0.0 (nếu fail).
Tổng weights = 1.0 (config trong TITLE_RULE_WEIGHTS).

Rules:
 1. not_null       — title không None/empty
 2. length_ok      — độ dài [5, 350] ký tự
 3. has_alpha      — có chứa ký tự alphabetic
 4. not_all_digits — không phải toàn số
 5. word_count_ok  — số từ [2, 40]
 6. not_doi        — không phải DOI
 7. not_url        — không phải URL
 8. not_footer     — không phải header/footer pattern
 9. no_noise       — không chứa noise patterns (arxiv, journal, etc.)
10. title_like     — có tính giống title (capitalization, structure)
"""

from __future__ import annotations

import logging

from core.validators.models import RuleResult, FieldValidation
from config.constants import (
    TITLE_RULE_WEIGHTS,
    VALID_TITLE_MIN_LENGTH,
    VALID_TITLE_MAX_LENGTH,
    VALID_TITLE_MIN_WORDS,
    VALID_TITLE_MAX_WORDS,
    VALIDATION_PASS_THRESHOLD,
    DOI_PATTERN,
    URL_PATTERN,
    HEADER_FOOTER_PATTERNS,
)
from core.title_detection.rules import NOISE_PATTERNS, is_title_case, is_all_upper

logger = logging.getLogger(__name__)


class TitleValidator:
    """
    Validate title đã trích xuất bằng 10 deterministic rules.

    Input: title string (cleaned, from M7).
    Output: FieldValidation với score, issues, warnings.
    """

    @staticmethod
    def validate(title: str | None) -> FieldValidation:
        """
        Chạy 10 rules trên title.

        Args:
            title: Title đã clean từ CleaningResult. None nếu không có.

        Returns:
            FieldValidation với score [0.0, 1.0].
        """
        weights = TITLE_RULE_WEIGHTS
        rules: list[RuleResult] = []
        issues: list[str] = []
        warnings: list[str] = []

        # ── Rule 1: not_null ──
        r = TitleValidator._check_not_null(title, weights["not_null"])
        rules.append(r)
        if not r.passed:
            issues.append(r.message)
            # Short-circuit: nếu null, tất cả rules khác fail
            for rule_name in list(weights.keys())[1:]:
                rules.append(RuleResult(
                    rule_name=rule_name,
                    passed=False,
                    score=0.0,
                    weight=weights[rule_name],
                    message="skipped (title is null)",
                ))
            score = 0.0
            return FieldValidation(
                field_name="title",
                score=score,
                passed=score >= VALIDATION_PASS_THRESHOLD,
                issues=issues,
                warnings=warnings,
                checked_rules=rules,
            )

        # Title is not null from here
        assert title is not None
        stripped = title.strip()

        # ── Rule 2: length_ok ──
        r = TitleValidator._check_length(stripped, weights["length_ok"])
        rules.append(r)
        if not r.passed:
            issues.append(r.message)

        # ── Rule 3: has_alpha ──
        r = TitleValidator._check_has_alpha(stripped, weights["has_alpha"])
        rules.append(r)
        if not r.passed:
            issues.append(r.message)

        # ── Rule 4: not_all_digits ──
        r = TitleValidator._check_not_all_digits(stripped, weights["not_all_digits"])
        rules.append(r)
        if not r.passed:
            issues.append(r.message)

        # ── Rule 5: word_count_ok ──
        r = TitleValidator._check_word_count(stripped, weights["word_count_ok"])
        rules.append(r)
        if not r.passed:
            issues.append(r.message)

        # ── Rule 6: not_doi ──
        r = TitleValidator._check_not_doi(stripped, weights["not_doi"])
        rules.append(r)
        if not r.passed:
            issues.append(r.message)

        # ── Rule 7: not_url ──
        r = TitleValidator._check_not_url(stripped, weights["not_url"])
        rules.append(r)
        if not r.passed:
            issues.append(r.message)

        # ── Rule 8: not_footer ──
        r = TitleValidator._check_not_footer(stripped, weights["not_footer"])
        rules.append(r)
        if not r.passed:
            issues.append(r.message)

        # ── Rule 9: no_noise ──
        r = TitleValidator._check_no_noise(stripped, weights["no_noise"])
        rules.append(r)
        if not r.passed:
            issues.append(r.message)

        # ── Rule 10: title_like ──
        r = TitleValidator._check_title_like(stripped, weights["title_like"])
        rules.append(r)
        if not r.passed:
            warnings.append(r.message)  # Warning, not critical

        # Compute total score
        score = sum(r.score for r in rules)
        score = min(score, 1.0)

        logger.debug(
            f"Title validation: score={score:.4f} "
            f"issues={len(issues)} warnings={len(warnings)}"
        )

        return FieldValidation(
            field_name="title",
            score=score,
            passed=score >= VALIDATION_PASS_THRESHOLD,
            issues=issues,
            warnings=warnings,
            checked_rules=rules,
        )

    # ── Individual Rule Checks ──

    @staticmethod
    def _check_not_null(title: str | None, weight: float) -> RuleResult:
        """Title không None/empty."""
        if title is None or not title.strip():
            return RuleResult(
                rule_name="not_null",
                passed=False,
                score=0.0,
                weight=weight,
                message="title is null or empty",
            )
        return RuleResult(rule_name="not_null", passed=True, score=weight, weight=weight)

    @staticmethod
    def _check_length(text: str, weight: float) -> RuleResult:
        """Độ dài trong [VALID_TITLE_MIN_LENGTH, VALID_TITLE_MAX_LENGTH]."""
        length = len(text)
        if length < VALID_TITLE_MIN_LENGTH:
            return RuleResult(
                rule_name="length_ok",
                passed=False,
                score=0.0,
                weight=weight,
                message=f"title too short ({length} chars, min {VALID_TITLE_MIN_LENGTH})",
            )
        if length > VALID_TITLE_MAX_LENGTH:
            return RuleResult(
                rule_name="length_ok",
                passed=False,
                score=0.0,
                weight=weight,
                message=f"title too long ({length} chars, max {VALID_TITLE_MAX_LENGTH})",
            )
        return RuleResult(rule_name="length_ok", passed=True, score=weight, weight=weight)

    @staticmethod
    def _check_has_alpha(text: str, weight: float) -> RuleResult:
        """Title phải chứa ít nhất 1 ký tự alphabetic."""
        if any(c.isalpha() for c in text):
            return RuleResult(
                rule_name="has_alpha", passed=True, score=weight, weight=weight
            )
        return RuleResult(
            rule_name="has_alpha",
            passed=False,
            score=0.0,
            weight=weight,
            message="title contains no alphabetic characters",
        )

    @staticmethod
    def _check_not_all_digits(text: str, weight: float) -> RuleResult:
        """Title không phải toàn số."""
        if text.strip().isdigit():
            return RuleResult(
                rule_name="not_all_digits",
                passed=False,
                score=0.0,
                weight=weight,
                message="title is all digits",
            )
        return RuleResult(
            rule_name="not_all_digits", passed=True, score=weight, weight=weight
        )

    @staticmethod
    def _check_word_count(text: str, weight: float) -> RuleResult:
        """Số từ trong [VALID_TITLE_MIN_WORDS, VALID_TITLE_MAX_WORDS]."""
        words = text.split()
        count = len(words)
        if count < VALID_TITLE_MIN_WORDS:
            return RuleResult(
                rule_name="word_count_ok",
                passed=False,
                score=0.0,
                weight=weight,
                message=f"title has too few words ({count}, min {VALID_TITLE_MIN_WORDS})",
            )
        if count > VALID_TITLE_MAX_WORDS:
            return RuleResult(
                rule_name="word_count_ok",
                passed=False,
                score=0.0,
                weight=weight,
                message=f"title has too many words ({count}, max {VALID_TITLE_MAX_WORDS})",
            )
        return RuleResult(
            rule_name="word_count_ok", passed=True, score=weight, weight=weight
        )

    @staticmethod
    def _check_not_doi(text: str, weight: float) -> RuleResult:
        """Title không phải DOI string."""
        if DOI_PATTERN.search(text):
            return RuleResult(
                rule_name="not_doi",
                passed=False,
                score=0.0,
                weight=weight,
                message="title matches DOI pattern",
            )
        return RuleResult(rule_name="not_doi", passed=True, score=weight, weight=weight)

    @staticmethod
    def _check_not_url(text: str, weight: float) -> RuleResult:
        """Title không phải URL."""
        if URL_PATTERN.search(text):
            return RuleResult(
                rule_name="not_url",
                passed=False,
                score=0.0,
                weight=weight,
                message="title matches URL pattern",
            )
        return RuleResult(rule_name="not_url", passed=True, score=weight, weight=weight)

    @staticmethod
    def _check_not_footer(text: str, weight: float) -> RuleResult:
        """Title không match header/footer patterns."""
        for pattern in HEADER_FOOTER_PATTERNS:
            if pattern.search(text):
                return RuleResult(
                    rule_name="not_footer",
                    passed=False,
                    score=0.0,
                    weight=weight,
                    message="title matches header/footer pattern",
                )
        return RuleResult(
            rule_name="not_footer", passed=True, score=weight, weight=weight
        )

    @staticmethod
    def _check_no_noise(text: str, weight: float) -> RuleResult:
        """Title không chứa noise patterns (arxiv, journal, proceedings, etc.)."""
        for pattern in NOISE_PATTERNS:
            if pattern.search(text):
                return RuleResult(
                    rule_name="no_noise",
                    passed=False,
                    score=0.0,
                    weight=weight,
                    message="title matches noise pattern",
                )
        return RuleResult(
            rule_name="no_noise", passed=True, score=weight, weight=weight
        )

    @staticmethod
    def _check_title_like(text: str, weight: float) -> RuleResult:
        """
        Title có tính giống tiêu đề paper.

        Heuristic: Title Case hoặc ALL CAPS → full score.
        Mixed/lowercase → partial score (0.5 * weight).
        Quá ngắn (< 3 words) và lowercase → fail.
        """
        words = text.split()

        if is_all_upper(text):
            return RuleResult(
                rule_name="title_like", passed=True, score=weight, weight=weight
            )

        if is_title_case(text):
            return RuleResult(
                rule_name="title_like", passed=True, score=weight, weight=weight
            )

        # Mixed case / sentence case — common in academic papers
        # Give partial score if it starts with uppercase
        if len(words) >= 2 and words[0][0:1].isupper():
            return RuleResult(
                rule_name="title_like",
                passed=True,
                score=weight * 0.7,
                weight=weight,
                message="title has sentence case (partial score)",
            )

        return RuleResult(
            rule_name="title_like",
            passed=False,
            score=0.0,
            weight=weight,
            message="title does not resemble a paper title",
        )
