"""
app/routers/paper_router.py
API endpoints cho Paper CRUD: results, search, review, health.

Router chỉ:
- Nhận request
- Validate input
- Gọi service
- Trả response

Business logic nằm trong PaperService.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.dependencies import get_paper_service, require_write_access
from config.constants import MAX_FILE_SIZE_BYTES
from app.services.paper_service import (
    PaperService,
    UploadValidationError,
)
from app.schemas.paper import (
    UploadResponse,
    DuplicateResponse,
    PaperListResponse,
    ReviewRequest,
    HealthResponse,
)
from infrastructure.database.persistence_service import (
    DuplicatePaperError,
    PersistenceError,
)
from core.pipeline.extractor_pipeline import PipelineError

logger = logging.getLogger(__name__)
router = APIRouter()


# ─────────────────────────────────────────────
# Upload — Full Pipeline
# ─────────────────────────────────────────────

@router.post(
    "/upload",
    response_model=UploadResponse,
    summary="Upload PDF và chạy full extraction pipeline",
    description=(
        "Upload file PDF, chạy toàn bộ pipeline M1–M9 "
        "(precheck, text extraction, layout analysis, title/author/abstract detection, "
        "cleaning, validation, LLM enhancement), lưu kết quả vào MongoDB."
    ),
    responses={
        400: {"description": "File không hợp lệ (extension, magic bytes)"},
        409: {"description": "PDF đã tồn tại (trùng SHA-256 hash)"},
        413: {"description": "File quá lớn"},
        500: {"description": "Lỗi server không mong đợi"},
    },
)
async def upload_pdf(
    file: UploadFile = File(..., description="File PDF cần xử lý"),
    service: PaperService = Depends(get_paper_service),
    _: None = Depends(require_write_access),
):
    """Upload PDF và chạy toàn bộ extraction pipeline."""
    # Validate content type
    if file.content_type and "pdf" not in file.content_type.lower():
        raise HTTPException(status_code=400, detail="Chỉ chấp nhận file PDF")

    try:
        content = await _read_limited_upload(file)
        result = await run_in_threadpool(
            service.process_upload,
            file_bytes=content,
            filename=file.filename or "unknown.pdf",
        )
        return result

    except UploadValidationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    except DuplicatePaperError as e:
        return JSONResponse(
            status_code=409,
            content={
                "error": "duplicate",
                "message": str(e),
                "paper_id": e.existing_paper_id,
            },
        )

    except PipelineError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Pipeline error at stage '{e.step}': {str(e)}",
        )

    except PersistenceError as e:
        logger.error(f"Persistence error during upload: {e}")
        raise HTTPException(
            status_code=500,
            detail="Lỗi lưu trữ dữ liệu. Vui lòng thử lại.",
        )

    except Exception as e:
        logger.error(f"Unexpected upload error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Lỗi server không mong đợi. Vui lòng thử lại.",
        )


# ─────────────────────────────────────────────
# Results — List + Detail
# ─────────────────────────────────────────────

@router.get(
    "/results",
    response_model=PaperListResponse,
    summary="Danh sách bài báo đã xử lý",
    description="Phân trang danh sách papers. Hỗ trợ filter theo min_confidence.",
)
def list_results(
    page: int = Query(1, ge=1, description="Số trang (1-indexed)"),
    limit: int = Query(10, ge=1, le=100, description="Số items/trang"),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0, description="Confidence tối thiểu"),
    service: PaperService = Depends(get_paper_service),
):
    """Danh sách bài báo đã xử lý, phân trang."""
    return service.list_papers(
        page=page,
        limit=limit,
        min_confidence=min_confidence,
    )


@router.get(
    "/results/{paper_id}",
    summary="Chi tiết một bài báo",
    description="Trả về toàn bộ metadata: title, authors, abstract, confidence, validation, review.",
    responses={
        404: {"description": "Không tìm thấy paper_id"},
    },
)
def get_result(
    paper_id: str,
    service: PaperService = Depends(get_paper_service),
):
    """Chi tiết một bài báo theo paper_id."""
    paper = service.get_paper(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy paper: {paper_id}")
    return paper


# ─────────────────────────────────────────────
# Search
# ─────────────────────────────────────────────

@router.get(
    "/search",
    summary="Tìm kiếm bài báo",
    description="Full-text search trên title và abstract. Reuse MongoDB text index.",
    responses={
        400: {"description": "Query rỗng"},
    },
)
def search_papers(
    q: str = Query(..., min_length=1, description="Từ khóa tìm kiếm"),
    limit: int = Query(20, ge=1, le=100, description="Số kết quả tối đa"),
    service: PaperService = Depends(get_paper_service),
):
    """Tìm kiếm bài báo theo title/abstract."""
    results = service.search_papers(query=q, limit=limit)
    return {
        "query": q,
        "results": results,
        "total": len(results),
    }


# ─────────────────────────────────────────────
# Review
# ─────────────────────────────────────────────

@router.patch(
    "/results/{paper_id}/review",
    summary="Cập nhật review status",
    description="Đánh dấu paper đã review hoặc chưa. Có thể thêm ghi chú.",
    responses={
        404: {"description": "Không tìm thấy paper_id"},
    },
)
def update_review(
    paper_id: str,
    review: ReviewRequest,
    service: PaperService = Depends(get_paper_service),
    _: None = Depends(require_write_access),
):
    """Cập nhật trạng thái review cho bài báo."""
    # Check paper exists
    paper = service.get_paper(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy paper: {paper_id}")

    updated = service.update_review(
        paper_id=paper_id,
        is_reviewed=review.is_reviewed,
        reviewer_notes=review.reviewer_notes,
    )

    return {
        "paper_id": paper_id,
        "is_reviewed": review.is_reviewed,
        "reviewer_notes": review.reviewer_notes,
        "updated": updated,
    }


# ─────────────────────────────────────────────
# Health Check
# ─────────────────────────────────────────────

@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Kiểm tra trạng thái application và MongoDB.",
)
def health_check(
    service: PaperService = Depends(get_paper_service),
):
    """Health check: application + database status."""
    return service.get_health()


async def _read_limited_upload(file: UploadFile) -> bytes:
    """Read multipart data incrementally and reject it as soon as it is too large."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > MAX_FILE_SIZE_BYTES:
            raise HTTPException(status_code=413, detail="File too large")
        chunks.append(chunk)
    return b"".join(chunks)
