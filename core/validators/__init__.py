# core/validators package
"""
Module Validation & Scoring (Milestone 8) + LLM Enhancement (Milestone 9).

Pipeline: Cleaned Metadata (M7) -> Title Validation -> Author Validation
    -> Abstract Validation -> Scoring -> ValidationReport
    -> [Optional] LLM Enhancement -> Enhanced ValidationReport

Input: CleaningResult (title, authors, abstract) từ M7.
Output: ValidationReport với per-field scores, issues, warnings, overall pass/fail.

NOTE: Đây là validation CHẤT LƯỢNG metadata, KHÔNG phải extraction confidence.
- Confidence (M4/M5/M6) = hệ thống tin candidate nào đúng nhất.
- Validation Score (M8) = kết quả cuối có đạt tiêu chí chất lượng không.
- LLM Enhancement (M9) = semantic validation bổ sung cho low-confidence fields.
"""

from core.validators.models import (
    RuleResult,
    FieldValidation,
    ValidationReport,
)
from core.validators.title_validator import TitleValidator
from core.validators.author_validator import AuthorValidator
from core.validators.abstract_validator import AbstractValidator
from core.validators.scoring import ValidationScorer
from core.validators.validation_engine import ValidationEngine
from core.validators.llm_validator import LLMValidator

__all__ = [
    # Models
    "RuleResult",
    "FieldValidation",
    "ValidationReport",
    # Validators (M8)
    "TitleValidator",
    "AuthorValidator",
    "AbstractValidator",
    # Scoring (M8)
    "ValidationScorer",
    # Engine (M8)
    "ValidationEngine",
    # LLM Enhancement (M9)
    "LLMValidator",
]
