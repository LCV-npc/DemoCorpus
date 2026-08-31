"""
core/models/metadata.py
Domain models cho extracted metadata, validation results, và processing tracking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import uuid


@dataclass
class FieldConfidence:
    """Độ tin cậy cho một trường metadata đã trích xuất."""

    field_name: str = ""
    score: float = 0.0
    issues: list[str] = field(default_factory=list)
    method: str = ""  # "heuristic", "ner", "llm", "rule"

    @property
    def passed(self) -> bool:
        """Trường đạt yêu cầu nếu score ≥ 0.5."""
        return self.score >= 0.5


@dataclass
class ValidationResult:
    """Kết quả validation cho 3 trường chính: title, authors, abstract."""

    title: FieldConfidence = field(default_factory=lambda: FieldConfidence(field_name="title"))
    authors: FieldConfidence = field(default_factory=lambda: FieldConfidence(field_name="authors"))
    abstract: FieldConfidence = field(default_factory=lambda: FieldConfidence(field_name="abstract"))

    @property
    def overall_score(self) -> float:
        """Điểm trung bình của 3 trường."""
        scores = [self.title.score, self.authors.score, self.abstract.score]
        return sum(scores) / len(scores)

    @property
    def is_valid(self) -> bool:
        """Metadata hợp lệ nếu overall_score ≥ 0.5."""
        return self.overall_score >= 0.5


@dataclass
class FilterResult:
    """Kết quả noise filter (CBS - Composite Badness Score)."""

    passed: bool = True
    flags: list[str] = field(default_factory=list)
    non_alpha_ratio: float = 0.0
    newline_ratio: float = 0.0
    misspelled_ratio: float = 0.0
    cbs_score: float = 0.0


@dataclass
class ProcessingStep:
    """Theo dõi một bước trong pipeline."""

    step_name: str = ""
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    success: bool = False
    error_message: str = ""

    def start(self):
        self.started_at = datetime.now(timezone.utc)

    def complete(self, success: bool = True, error: str = ""):
        self.completed_at = datetime.now(timezone.utc)
        self.success = success
        self.error_message = error


@dataclass
class ExtractedMetadata:
    """Toàn bộ metadata đã trích xuất từ một bài báo PDF."""

    # Identification
    paper_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: str = ""          # "upload", "scrape", "local"
    source_url: str = ""      # URL nguồn (trang web chứa bài báo)
    pdf_url: str = ""         # URL trực tiếp đến file PDF
    file_path: str = ""
    file_hash_sha256: str = ""

    # Extracted fields
    title: Optional[str] = None
    authors: list[str] = field(default_factory=list)
    abstract: Optional[str] = None

    # Quality metrics
    confidence: Optional[ValidationResult] = None
    filter_result: Optional[FilterResult] = None

    # Processing tracking
    steps_completed: list[str] = field(default_factory=list)
    processing_steps: list[ProcessingStep] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None

    # Review
    is_reviewed: bool = False
    reviewer_notes: str = ""

    # ── Properties ──

    @property
    def overall_confidence(self) -> float:
        """Confidence score tổng thể. 0.0 nếu chưa validate."""
        if self.confidence is None:
            return 0.0
        return self.confidence.overall_score

    @property
    def has_all_fields(self) -> bool:
        """True nếu đã trích xuất đầy đủ title, authors, abstract."""
        return (
            self.title is not None
            and len(self.authors) > 0
            and self.abstract is not None
        )

    # ── Methods ──

    def to_dict(self) -> dict:
        """Serialize thành dict cho MongoDB/JSON storage."""
        result = {
            "paper_id": self.paper_id,
            "source": self.source,
            "source_url": self.source_url,
            "pdf_url": self.pdf_url,
            "file_path": self.file_path,
            "file_hash_sha256": self.file_hash_sha256,
            "extracted": {
                "title": self.title,
                "authors": self.authors,
                "abstract": self.abstract,
            },
            "confidence": {
                "overall": self.overall_confidence,
                "title": {
                    "score": self.confidence.title.score if self.confidence else 0,
                    "issues": self.confidence.title.issues if self.confidence else [],
                    "method": self.confidence.title.method if self.confidence else "",
                },
                "authors": {
                    "score": self.confidence.authors.score if self.confidence else 0,
                    "issues": self.confidence.authors.issues if self.confidence else [],
                    "method": self.confidence.authors.method if self.confidence else "",
                },
                "abstract": {
                    "score": self.confidence.abstract.score if self.confidence else 0,
                    "issues": self.confidence.abstract.issues if self.confidence else [],
                    "method": self.confidence.abstract.method if self.confidence else "",
                },
            },
            "filter_result": None,
            "processing": {
                "steps_completed": self.steps_completed,
                "processing_steps": [
                    {
                        "step_name": s.step_name,
                        "started_at": s.started_at.isoformat() if s.started_at else None,
                        "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                        "success": s.success,
                        "error_message": s.error_message,
                    }
                    for s in self.processing_steps
                ],
                "created_at": self.created_at.isoformat(),
            },
            "review": {
                "is_reviewed": self.is_reviewed,
                "reviewer_notes": self.reviewer_notes,
            },
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        # Serialize filter_result nếu có
        if self.filter_result is not None:
            result["filter_result"] = {
                "passed": self.filter_result.passed,
                "flags": self.filter_result.flags,
                "non_alpha_ratio": self.filter_result.non_alpha_ratio,
                "newline_ratio": self.filter_result.newline_ratio,
                "misspelled_ratio": self.filter_result.misspelled_ratio,
                "cbs_score": self.filter_result.cbs_score,
            }

        return result

    @classmethod
    def from_dict(cls, data: dict) -> "ExtractedMetadata":
        """
        Reconstruct ExtractedMetadata từ MongoDB document / dict.

        Hỗ trợ roundtrip: to_dict() → MongoDB → from_dict() → domain object.
        """
        extracted = data.get("extracted", {})
        conf_data = data.get("confidence", {})
        proc_data = data.get("processing", {})
        review_data = data.get("review", {})
        filter_data = data.get("filter_result")

        # Reconstruct ValidationResult from confidence dict
        confidence = None
        if conf_data:
            title_conf = conf_data.get("title", {})
            authors_conf = conf_data.get("authors", {})
            abstract_conf = conf_data.get("abstract", {})
            confidence = ValidationResult(
                title=FieldConfidence(
                    field_name="title",
                    score=title_conf.get("score", 0),
                    issues=title_conf.get("issues", []),
                    method=title_conf.get("method", ""),
                ),
                authors=FieldConfidence(
                    field_name="authors",
                    score=authors_conf.get("score", 0),
                    issues=authors_conf.get("issues", []),
                    method=authors_conf.get("method", ""),
                ),
                abstract=FieldConfidence(
                    field_name="abstract",
                    score=abstract_conf.get("score", 0),
                    issues=abstract_conf.get("issues", []),
                    method=abstract_conf.get("method", ""),
                ),
            )

        # Reconstruct FilterResult
        filter_result = None
        if filter_data and isinstance(filter_data, dict):
            filter_result = FilterResult(
                passed=filter_data.get("passed", True),
                flags=filter_data.get("flags", []),
                non_alpha_ratio=filter_data.get("non_alpha_ratio", 0.0),
                newline_ratio=filter_data.get("newline_ratio", 0.0),
                misspelled_ratio=filter_data.get("misspelled_ratio", 0.0),
                cbs_score=filter_data.get("cbs_score", 0.0),
            )

        # Reconstruct ProcessingSteps
        processing_steps = []
        for step_data in proc_data.get("processing_steps", []):
            step = ProcessingStep(
                step_name=step_data.get("step_name", ""),
                success=step_data.get("success", False),
                error_message=step_data.get("error_message", ""),
            )
            if step_data.get("started_at"):
                step.started_at = datetime.fromisoformat(step_data["started_at"])
            if step_data.get("completed_at"):
                step.completed_at = datetime.fromisoformat(step_data["completed_at"])
            processing_steps.append(step)

        # Parse timestamps
        created_at_str = proc_data.get("created_at")
        created_at = (
            datetime.fromisoformat(created_at_str)
            if created_at_str
            else datetime.now(timezone.utc)
        )
        updated_at_str = data.get("updated_at")
        updated_at = (
            datetime.fromisoformat(updated_at_str)
            if updated_at_str
            else None
        )

        return cls(
            paper_id=data.get("paper_id", str(uuid.uuid4())),
            source=data.get("source", ""),
            source_url=data.get("source_url", ""),
            pdf_url=data.get("pdf_url", ""),
            file_path=data.get("file_path", ""),
            file_hash_sha256=data.get("file_hash_sha256", ""),
            title=extracted.get("title"),
            authors=extracted.get("authors", []),
            abstract=extracted.get("abstract"),
            confidence=confidence,
            filter_result=filter_result,
            steps_completed=proc_data.get("steps_completed", []),
            processing_steps=processing_steps,
            created_at=created_at,
            updated_at=updated_at,
            is_reviewed=review_data.get("is_reviewed", False),
            reviewer_notes=review_data.get("reviewer_notes", ""),
        )
