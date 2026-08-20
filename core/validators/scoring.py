"""
core/validators/scoring.py
ValidationScorer — tính score cho validation results.

Scoring logic:
1. Field score = weighted sum of rule scores (weights từ constants.py).
   Mỗi rule đã trả về score = weight (nếu pass) hoặc 0.0 (nếu fail).
   Tổng weights mỗi field = 1.0, nên field score ∈ [0.0, 1.0].

2. Overall score = weighted combination theo OVERALL_FIELD_WEIGHTS.
   title × 0.35 + authors × 0.30 + abstract × 0.35

3. Passed = overall_score >= VALIDATION_PASS_THRESHOLD
"""

from __future__ import annotations

import logging

from core.validators.models import RuleResult, FieldValidation
from config.constants import (
    OVERALL_FIELD_WEIGHTS,
    VALIDATION_PASS_THRESHOLD,
)

logger = logging.getLogger(__name__)


class ValidationScorer:
    """
    Tính toán validation scores.

    Thiết kế: Pure computation, stateless, không side effects.
    """

    @staticmethod
    def compute_field_score(rules: list[RuleResult]) -> float:
        """
        Tính field score từ danh sách rule results.

        Mỗi rule.score đã được set = weight (pass) hoặc 0.0 (fail)
        trong các validator. Tổng weights = 1.0.

        Args:
            rules: Danh sách RuleResult từ validator.

        Returns:
            Score [0.0, 1.0].
        """
        if not rules:
            return 0.0
        total = sum(r.score for r in rules)
        return min(total, 1.0)

    @staticmethod
    def compute_overall_score(
        title: FieldValidation,
        authors: FieldValidation,
        abstract: FieldValidation,
    ) -> float:
        """
        Tính overall score từ 3 field validations.

        Formula:
            overall = title.score × w_title
                    + authors.score × w_authors
                    + abstract.score × w_abstract

        Weights từ OVERALL_FIELD_WEIGHTS:
            title=0.35, authors=0.30, abstract=0.35

        Args:
            title: FieldValidation cho title.
            authors: FieldValidation cho authors.
            abstract: FieldValidation cho abstract.

        Returns:
            Overall score [0.0, 1.0].
        """
        overall = (
            title.score * OVERALL_FIELD_WEIGHTS["title"]
            + authors.score * OVERALL_FIELD_WEIGHTS["authors"]
            + abstract.score * OVERALL_FIELD_WEIGHTS["abstract"]
        )
        return min(overall, 1.0)

    @staticmethod
    def is_passed(overall_score: float) -> bool:
        """
        Kiểm tra overall score có đạt ngưỡng pass.

        Args:
            overall_score: Overall validation score.

        Returns:
            True nếu >= VALIDATION_PASS_THRESHOLD.
        """
        return overall_score >= VALIDATION_PASS_THRESHOLD
