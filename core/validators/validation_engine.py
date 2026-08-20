"""
core/validators/validation_engine.py
ValidationEngine — orchestrator cho Validation & Scoring pipeline (Milestone 8).

Pipeline:
1. Nhận CleaningResult từ M7 (hoặc raw title/authors/abstract).
2. Chạy TitleValidator, AuthorValidator, AbstractValidator.
3. Tính overall score qua ValidationScorer.
4. Trả về ValidationReport.

NOTE: Module này hoạt động độc lập và deterministic.
      Không có LLM, không có side effects, không sửa dữ liệu.
"""

from __future__ import annotations

import logging
import time

from core.validators.models import ValidationReport
from core.validators.title_validator import TitleValidator
from core.validators.author_validator import AuthorValidator
from core.validators.abstract_validator import AbstractValidator
from core.validators.scoring import ValidationScorer
from core.data_cleaning.models import CleaningResult

logger = logging.getLogger(__name__)


class ValidationEngine:
    """
    Orchestrator cho validation pipeline.

    Nhận cleaned metadata, chạy validators, tính scores.
    """

    def __init__(self):
        logger.info("ValidationEngine initialized")

    def validate(
        self,
        cleaning_result: CleaningResult | None = None,
        *,
        title: str | None = None,
        authors: list[str] | None = None,
        abstract: str | None = None,
    ) -> ValidationReport:
        """
        Chạy full validation pipeline.

        Có thể nhận input qua CleaningResult hoặc trực tiếp.
        Nếu cả hai được cung cấp, CleaningResult sẽ được ưu tiên.

        Args:
            cleaning_result: Output từ M7 DataCleaningService.
            title: Title string (override nếu không dùng cleaning_result).
            authors: Author list (override nếu không dùng cleaning_result).
            abstract: Abstract string (override nếu không dùng cleaning_result).

        Returns:
            ValidationReport với scores, issues, warnings cho tất cả fields.
        """
        start_time = time.time()

        # Extract data từ CleaningResult hoặc parameters
        if cleaning_result is not None:
            val_title = cleaning_result.title
            val_authors = cleaning_result.authors
            val_abstract = cleaning_result.abstract
        else:
            val_title = title
            val_authors = authors if authors is not None else []
            val_abstract = abstract

        # ── Step 1: Validate Title ──
        title_validation = TitleValidator.validate(val_title)

        # ── Step 2: Validate Authors ──
        author_validation = AuthorValidator.validate(val_authors)

        # ── Step 3: Validate Abstract ──
        abstract_validation = AbstractValidator.validate(val_abstract)

        # ── Step 4: Compute Overall Score ──
        overall_score = ValidationScorer.compute_overall_score(
            title_validation, author_validation, abstract_validation
        )
        passed = ValidationScorer.is_passed(overall_score)

        # Build report
        report = ValidationReport(
            title=title_validation,
            authors=author_validation,
            abstract=abstract_validation,
            overall_score=overall_score,
            passed=passed,
        )

        elapsed = time.time() - start_time

        logger.info(
            f"Validation complete: "
            f"title={title_validation.score:.4f} "
            f"authors={author_validation.score:.4f} "
            f"abstract={abstract_validation.score:.4f} "
            f"overall={overall_score:.4f} "
            f"passed={passed} "
            f"time={elapsed:.3f}s"
        )

        return report
