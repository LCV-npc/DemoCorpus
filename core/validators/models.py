"""
core/validators/models.py
Data models cho Validation & Scoring module (Milestone 8 + 9).

RuleResult — kết quả của một validation rule.
FieldValidation — kết quả validation cho một field (title/authors/abstract).
ValidationReport — kết quả validation tổng hợp cho toàn bộ metadata.

NOTE: Đây KHÔNG phải Extraction Confidence (FieldConfidence trong metadata.py).
      Đây là Validation Score — đánh giá chất lượng metadata đã trích xuất.

Milestone 9 additions:
- FieldValidation: llm_called, llm_score, llm_reason
- ValidationReport: llm_enhanced
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RuleResult:
    """
    Kết quả của một validation rule.

    Attributes:
        rule_name: Tên rule (e.g., "not_null", "length_ok").
        passed: True nếu rule pass.
        score: Điểm đạt được (= weight nếu pass, 0.0 nếu fail).
        weight: Trọng số tối đa của rule.
        message: Mô tả issue/warning (rỗng nếu pass).
    """

    rule_name: str = ""
    passed: bool = True
    score: float = 0.0
    weight: float = 0.0
    message: str = ""

    def to_dict(self) -> dict:
        """Serialize."""
        result: dict = {
            "rule": self.rule_name,
            "passed": self.passed,
            "score": round(self.score, 4),
            "weight": round(self.weight, 4),
        }
        if self.message:
            result["message"] = self.message
        return result


@dataclass
class FieldValidation:
    """
    Kết quả validation cho một field (title, authors, hoặc abstract).

    Attributes:
        field_name: Tên field ("title", "authors", "abstract").
        score: Tổng score [0.0, 1.0] (weighted sum of rule scores).
        passed: True nếu score >= VALIDATION_PASS_THRESHOLD.
        issues: Danh sách lỗi nghiêm trọng (rule failed).
        warnings: Danh sách cảnh báo (rule pass nhưng có concern).
        checked_rules: Danh sách tất cả rule results.
        llm_called: True nếu LLM được gọi cho field này (M9).
        llm_score: LLM confidence [0.0, 1.0], None nếu LLM không gọi (M9).
        llm_reason: LLM explanation string (M9).
    """

    field_name: str = ""
    score: float = 0.0
    passed: bool = False
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_rules: list[RuleResult] = field(default_factory=list)
    # LLM enhancement fields (M9, defaults preserve M8 behavior)
    llm_called: bool = False
    llm_score: Optional[float] = None
    llm_reason: str = ""

    def to_dict(self) -> dict:
        """Serialize."""
        result = {
            "field": self.field_name,
            "score": round(self.score, 4),
            "passed": self.passed,
            "issues": self.issues,
            "warnings": self.warnings,
            "checked_rules": [r.to_dict() for r in self.checked_rules],
        }
        # Only include LLM fields when LLM was actually used (M9)
        if self.llm_called:
            result["llm_called"] = True
            result["llm_score"] = (
                round(self.llm_score, 4) if self.llm_score is not None else None
            )
            result["llm_reason"] = self.llm_reason
        return result


@dataclass
class ValidationReport:
    """
    Kết quả validation tổng hợp cho toàn bộ metadata.

    Chứa validation cho 3 trường: title, authors, abstract.
    overall_score = weighted combination theo OVERALL_FIELD_WEIGHTS.

    NOTE: Đây KHÔNG phải Extraction Confidence.
    - Confidence = hệ thống tin rằng candidate nào tốt hơn (M4/M5/M6).
    - Validation Score = kết quả cuối cùng có đạt tiêu chí chất lượng không (M8).
    - LLM Enhancement = tầng semantic validation bổ sung (M9).
    """

    title: FieldValidation = field(
        default_factory=lambda: FieldValidation(field_name="title")
    )
    authors: FieldValidation = field(
        default_factory=lambda: FieldValidation(field_name="authors")
    )
    abstract: FieldValidation = field(
        default_factory=lambda: FieldValidation(field_name="abstract")
    )
    overall_score: float = 0.0
    passed: bool = False
    # M9: True if any field was enhanced by LLM
    llm_enhanced: bool = False

    def to_dict(self) -> dict:
        """Serialize thành dict cho JSON output."""
        result = {
            "title": self.title.to_dict(),
            "authors": self.authors.to_dict(),
            "abstract": self.abstract.to_dict(),
            "overall_score": round(self.overall_score, 4),
            "passed": self.passed,
        }
        if self.llm_enhanced:
            result["llm_enhanced"] = True
        return result
