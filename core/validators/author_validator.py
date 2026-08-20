"""
core/validators/author_validator.py
AuthorValidator — 9 rules kiểm tra chất lượng danh sách tác giả đã trích xuất.

Rules:
 1. not_empty        — danh sách không rỗng
 2. count_ok         — số lượng author hợp lý [1, 50]
 3. names_structured — mỗi tên có cấu trúc hợp lý (≥ 1 word, bắt đầu bằng chữ)
 4. no_emails        — không chứa email trong tên
 5. no_urls          — không chứa URL trong tên
 6. no_affiliations  — không chứa affiliation keywords
 7. length_ok        — mỗi tên không quá dài (≤ 80 chars)
 8. not_all_digits   — tên không phải toàn số
 9. no_duplicates    — không có tên trùng lặp
"""

from __future__ import annotations

import logging

from core.validators.models import RuleResult, FieldValidation
from config.constants import (
    AUTHOR_RULE_WEIGHTS,
    VALID_AUTHOR_MAX_COUNT,
    VALID_AUTHOR_NAME_MAX_LENGTH,
    VALIDATION_PASS_THRESHOLD,
    EMAIL_PATTERN,
    URL_PATTERN,
    AFFILIATION_KEYWORDS,
)

logger = logging.getLogger(__name__)


class AuthorValidator:
    """
    Validate danh sách tác giả bằng 9 deterministic rules.

    Input: list[str] tên tác giả (cleaned, from M7).
    Output: FieldValidation với score, issues, warnings.
    """

    @staticmethod
    def validate(authors: list[str]) -> FieldValidation:
        """
        Chạy 9 rules trên danh sách tác giả.

        Args:
            authors: Danh sách tên tác giả đã clean.

        Returns:
            FieldValidation với score [0.0, 1.0].
        """
        weights = AUTHOR_RULE_WEIGHTS
        rules: list[RuleResult] = []
        issues: list[str] = []
        warnings: list[str] = []

        # ── Rule 1: not_empty ──
        r = AuthorValidator._check_not_empty(authors, weights["not_empty"])
        rules.append(r)
        if not r.passed:
            issues.append(r.message)
            # Short-circuit: danh sách rỗng → tất cả rules khác fail
            for rule_name in list(weights.keys())[1:]:
                rules.append(RuleResult(
                    rule_name=rule_name,
                    passed=False,
                    score=0.0,
                    weight=weights[rule_name],
                    message="skipped (author list is empty)",
                ))
            return FieldValidation(
                field_name="authors",
                score=0.0,
                passed=False,
                issues=issues,
                warnings=warnings,
                checked_rules=rules,
            )

        # ── Rule 2: count_ok ──
        r = AuthorValidator._check_count(authors, weights["count_ok"])
        rules.append(r)
        if not r.passed:
            issues.append(r.message)

        # ── Rule 3: names_structured ──
        r = AuthorValidator._check_names_structured(
            authors, weights["names_structured"]
        )
        rules.append(r)
        if not r.passed:
            issues.append(r.message)
        elif r.message:
            warnings.append(r.message)

        # ── Rule 4: no_emails ──
        r = AuthorValidator._check_no_emails(authors, weights["no_emails"])
        rules.append(r)
        if not r.passed:
            issues.append(r.message)

        # ── Rule 5: no_urls ──
        r = AuthorValidator._check_no_urls(authors, weights["no_urls"])
        rules.append(r)
        if not r.passed:
            issues.append(r.message)

        # ── Rule 6: no_affiliations ──
        r = AuthorValidator._check_no_affiliations(
            authors, weights["no_affiliations"]
        )
        rules.append(r)
        if not r.passed:
            issues.append(r.message)

        # ── Rule 7: length_ok ──
        r = AuthorValidator._check_length(authors, weights["length_ok"])
        rules.append(r)
        if not r.passed:
            issues.append(r.message)

        # ── Rule 8: not_all_digits ──
        r = AuthorValidator._check_not_all_digits(
            authors, weights["not_all_digits"]
        )
        rules.append(r)
        if not r.passed:
            issues.append(r.message)

        # ── Rule 9: no_duplicates ──
        r = AuthorValidator._check_no_duplicates(authors, weights["no_duplicates"])
        rules.append(r)
        if not r.passed:
            issues.append(r.message)

        # Compute total score
        score = sum(r.score for r in rules)
        score = min(score, 1.0)

        logger.debug(
            f"Author validation: score={score:.4f} "
            f"issues={len(issues)} warnings={len(warnings)}"
        )

        return FieldValidation(
            field_name="authors",
            score=score,
            passed=score >= VALIDATION_PASS_THRESHOLD,
            issues=issues,
            warnings=warnings,
            checked_rules=rules,
        )

    # ── Individual Rule Checks ──

    @staticmethod
    def _check_not_empty(authors: list[str], weight: float) -> RuleResult:
        """Danh sách không rỗng."""
        if not authors:
            return RuleResult(
                rule_name="not_empty",
                passed=False,
                score=0.0,
                weight=weight,
                message="author list is empty",
            )
        return RuleResult(
            rule_name="not_empty", passed=True, score=weight, weight=weight
        )

    @staticmethod
    def _check_count(authors: list[str], weight: float) -> RuleResult:
        """Số lượng author trong [1, VALID_AUTHOR_MAX_COUNT]."""
        count = len(authors)
        if count > VALID_AUTHOR_MAX_COUNT:
            return RuleResult(
                rule_name="count_ok",
                passed=False,
                score=0.0,
                weight=weight,
                message=f"too many authors ({count}, max {VALID_AUTHOR_MAX_COUNT})",
            )
        return RuleResult(
            rule_name="count_ok", passed=True, score=weight, weight=weight
        )

    @staticmethod
    def _check_names_structured(authors: list[str], weight: float) -> RuleResult:
        """
        Mỗi tên có cấu trúc hợp lý.

        Kiểm tra: ≥ 1 word token, bắt đầu bằng ký tự alphabetic.
        Cho phép partial pass nếu phần lớn tên OK.
        """
        if not authors:
            return RuleResult(
                rule_name="names_structured",
                passed=False,
                score=0.0,
                weight=weight,
                message="no authors to check",
            )

        bad_names = []
        for name in authors:
            stripped = name.strip()
            if not stripped:
                bad_names.append(name)
                continue
            # Phải bắt đầu bằng ký tự alphabetic
            if not stripped[0].isalpha():
                bad_names.append(name)
                continue

        if not bad_names:
            return RuleResult(
                rule_name="names_structured",
                passed=True,
                score=weight,
                weight=weight,
            )

        bad_ratio = len(bad_names) / len(authors)
        if bad_ratio <= 0.3:
            # Partial pass: phần lớn OK
            partial_score = weight * (1.0 - bad_ratio)
            return RuleResult(
                rule_name="names_structured",
                passed=True,
                score=partial_score,
                weight=weight,
                message=f"{len(bad_names)}/{len(authors)} names have poor structure",
            )

        return RuleResult(
            rule_name="names_structured",
            passed=False,
            score=0.0,
            weight=weight,
            message=f"{len(bad_names)}/{len(authors)} names have poor structure",
        )

    @staticmethod
    def _check_no_emails(authors: list[str], weight: float) -> RuleResult:
        """Không có email trong tên tác giả."""
        for name in authors:
            if EMAIL_PATTERN.search(name):
                return RuleResult(
                    rule_name="no_emails",
                    passed=False,
                    score=0.0,
                    weight=weight,
                    message=f"author name contains email: {name!r}",
                )
        return RuleResult(
            rule_name="no_emails", passed=True, score=weight, weight=weight
        )

    @staticmethod
    def _check_no_urls(authors: list[str], weight: float) -> RuleResult:
        """Không có URL trong tên tác giả."""
        for name in authors:
            if URL_PATTERN.search(name):
                return RuleResult(
                    rule_name="no_urls",
                    passed=False,
                    score=0.0,
                    weight=weight,
                    message=f"author name contains URL: {name!r}",
                )
        return RuleResult(
            rule_name="no_urls", passed=True, score=weight, weight=weight
        )

    @staticmethod
    def _check_no_affiliations(authors: list[str], weight: float) -> RuleResult:
        """
        Tên tác giả không chứa affiliation keywords.

        Kiểm tra từng tên xem có chứa keywords như
        "university", "institute", "department", etc.
        """
        for name in authors:
            name_lower = name.lower()
            for keyword in AFFILIATION_KEYWORDS:
                if keyword in name_lower:
                    return RuleResult(
                        rule_name="no_affiliations",
                        passed=False,
                        score=0.0,
                        weight=weight,
                        message=(
                            f"author name contains affiliation keyword "
                            f"'{keyword}': {name!r}"
                        ),
                    )
        return RuleResult(
            rule_name="no_affiliations", passed=True, score=weight, weight=weight
        )

    @staticmethod
    def _check_length(authors: list[str], weight: float) -> RuleResult:
        """Mỗi tên không quá dài (≤ VALID_AUTHOR_NAME_MAX_LENGTH chars)."""
        for name in authors:
            if len(name) > VALID_AUTHOR_NAME_MAX_LENGTH:
                return RuleResult(
                    rule_name="length_ok",
                    passed=False,
                    score=0.0,
                    weight=weight,
                    message=(
                        f"author name too long ({len(name)} chars, "
                        f"max {VALID_AUTHOR_NAME_MAX_LENGTH}): {name[:50]!r}"
                    ),
                )
        return RuleResult(
            rule_name="length_ok", passed=True, score=weight, weight=weight
        )

    @staticmethod
    def _check_not_all_digits(authors: list[str], weight: float) -> RuleResult:
        """Tên tác giả không phải toàn số."""
        for name in authors:
            stripped = name.strip()
            if stripped and stripped.isdigit():
                return RuleResult(
                    rule_name="not_all_digits",
                    passed=False,
                    score=0.0,
                    weight=weight,
                    message=f"author name is all digits: {name!r}",
                )
        return RuleResult(
            rule_name="not_all_digits", passed=True, score=weight, weight=weight
        )

    @staticmethod
    def _check_no_duplicates(authors: list[str], weight: float) -> RuleResult:
        """Không có tên trùng lặp (case-insensitive)."""
        seen: set[str] = set()
        duplicates: list[str] = []
        for name in authors:
            normalized = name.strip().lower()
            if normalized in seen:
                duplicates.append(name)
            else:
                seen.add(normalized)

        if duplicates:
            return RuleResult(
                rule_name="no_duplicates",
                passed=False,
                score=0.0,
                weight=weight,
                message=f"duplicate author names found: {duplicates}",
            )
        return RuleResult(
            rule_name="no_duplicates", passed=True, score=weight, weight=weight
        )
