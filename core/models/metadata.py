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
        return {
            "paper_id": self.paper_id,
            "source": self.source,
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
            "processing": {
                "steps_completed": self.steps_completed,
                "created_at": self.created_at.isoformat(),
            },
            "review": {
                "is_reviewed": self.is_reviewed,
                "reviewer_notes": self.reviewer_notes,
            },
        }
