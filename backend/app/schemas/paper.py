"""
app/schemas/paper.py
Pydantic request/response schemas cho Paper API endpoints.

Reuse domain model ExtractedMetadata.to_dict() format.
Không duplicate domain logic — chỉ define API contract.
"""

from pydantic import BaseModel, Field
from typing import Optional


# ─────────────────────────────────────────────
# Response Schemas
# ─────────────────────────────────────────────

class FieldConfidenceResponse(BaseModel):
    """Confidence score cho một field."""
    score: float = 0.0
    issues: list[str] = Field(default_factory=list)
    method: str = ""


class ConfidenceResponse(BaseModel):
    """Confidence scores cho tất cả fields."""
    overall: float = 0.0
    title: FieldConfidenceResponse = Field(default_factory=FieldConfidenceResponse)
    authors: FieldConfidenceResponse = Field(default_factory=FieldConfidenceResponse)
    abstract: FieldConfidenceResponse = Field(default_factory=FieldConfidenceResponse)


class ProcessingResponse(BaseModel):
    """Processing tracking info."""
    steps_completed: list[str] = Field(default_factory=list)
    processing_steps: list[dict] = Field(default_factory=list)
    created_at: Optional[str] = None
    elapsed_seconds: Optional[float] = None


class ReviewResponse(BaseModel):
    """Review status."""
    is_reviewed: bool = False
    reviewer_notes: str = ""


class UploadResponse(BaseModel):
    """Response cho POST /upload khi pipeline thành công."""
    paper_id: str
    status: str = "completed"
    title: Optional[str] = None
    authors: list[str] = Field(default_factory=list)
    abstract: Optional[str] = None
    confidence: dict = Field(default_factory=dict)
    validation: dict = Field(default_factory=dict)
    processing: dict = Field(default_factory=dict)


class DuplicateResponse(BaseModel):
    """Response cho upload PDF bị trùng (409)."""
    error: str = "duplicate"
    message: str
    paper_id: str


class PaperListResponse(BaseModel):
    """Response cho GET /results — paginated list."""
    items: list[dict]
    page: int
    limit: int
    total: int


class HealthResponse(BaseModel):
    """Response cho GET /health."""
    status: str
    database: str
    version: str = "0.1.0"


# ─────────────────────────────────────────────
# Request Schemas
# ─────────────────────────────────────────────

class ReviewRequest(BaseModel):
    """Request cho PATCH /results/{paper_id}/review."""
    is_reviewed: bool
    reviewer_notes: str = Field(default="", max_length=4000)


class ErrorResponse(BaseModel):
    """Standard error response format."""
    error: str
    message: str
    detail: Optional[str] = None
