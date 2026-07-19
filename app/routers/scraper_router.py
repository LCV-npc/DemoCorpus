"""
app/routers/scraper_router.py
API endpoints cho scraping, upload, và quản lý PDF.
"""

import threading
import uuid
import logging
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

from config.settings import settings
from config.constants import MAX_FILE_SIZE_BYTES, PDF_MAGIC_BYTES
from infrastructure.scraper.pdf_scraper import PDFScraper, scrape_status
from core.pipeline.extractor_pipeline import ExtractorPipeline, PipelineError
from infrastructure.storage.file_storage import FileStorage

logger = logging.getLogger(__name__)
router = APIRouter()

# Shared instances
_scraper = PDFScraper()
_storage = FileStorage()
_pipeline = ExtractorPipeline()
_scrape_thread: threading.Thread | None = None

# MongoDB repository (lazy init)
_repo = None


def _get_repo():
    global _repo
    if _repo is None:
        try:
            from infrastructure.database.repositories.paper_repository import PaperRepository
            _repo = PaperRepository()
        except Exception as e:
            logger.warning(f"MongoDB not available: {e}. Running without database.")
    return _repo


# ─────────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────────

class ScrapeRequest(BaseModel):
    url: str
    max_depth: int = 2


class ScrapeResponse(BaseModel):
    message: str
    status: str


# ─────────────────────────────────────────────
# Scraping Endpoints
# ─────────────────────────────────────────────

@router.post("/scrape")
def start_scrape(request: ScrapeRequest):
    """Bắt đầu scraping PDF từ URL."""
    global _scrape_thread

    if scrape_status.running:
        raise HTTPException(status_code=409, detail="Đang có tiến trình scraping chạy")

    def _run():
        _scraper.scrape(url=request.url, max_depth=request.max_depth)
        # After scraping done, save records to MongoDB
        repo = _get_repo()
        if repo:
            for record in scrape_status.pdf_records:
                try:
                    repo.insert_paper(record.copy())
                except Exception as e:
                    logger.warning(f"Could not save to MongoDB: {e}")

    _scrape_thread = threading.Thread(target=_run, daemon=True)
    _scrape_thread.start()

    return {"message": "Đã bắt đầu quét", "status": "started"}


@router.get("/scrape/status")
def get_scrape_status():
    """Lấy trạng thái scraping realtime."""
    return scrape_status.to_dict()


@router.post("/scrape/stop")
def stop_scrape():
    """Dừng scraping."""
    if not scrape_status.running:
        raise HTTPException(status_code=400, detail="Không có tiến trình đang chạy")

    scrape_status.should_stop = True
    return {"message": "Đã gửi yêu cầu dừng", "status": "stopping"}


# ─────────────────────────────────────────────
# Upload Endpoint
# ─────────────────────────────────────────────

@router.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    """Upload file PDF thủ công."""
    # Validate content type
    if file.content_type and "pdf" not in file.content_type.lower():
        raise HTTPException(status_code=400, detail="Chỉ chấp nhận file PDF")

    # Read file
    content = await file.read()

    # Check size
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File quá lớn ({len(content)/(1024*1024):.1f}MB). Giới hạn: {MAX_FILE_SIZE_BYTES/(1024*1024):.0f}MB"
        )

    # Check magic bytes
    if not content[:4].startswith(PDF_MAGIC_BYTES):
        raise HTTPException(status_code=400, detail="File không phải PDF hợp lệ")

    # Save file
    paper_id = str(uuid.uuid4())[:8]
    file_path = _storage.save(content, paper_id)

    # Run pre-check
    try:
        from core.models.metadata import ExtractedMetadata
        metadata = ExtractedMetadata(paper_id=paper_id, source="upload", file_path=file_path)
        _pipeline._step_precheck(file_path, metadata)

        # Save to MongoDB
        repo = _get_repo()
        if repo:
            # Check duplicate
            existing = repo.get_by_hash(metadata.file_hash_sha256)
            if existing:
                _storage.delete(file_path)
                raise HTTPException(status_code=409, detail="File PDF này đã tồn tại (trùng hash)")
            repo.insert_paper(metadata.to_dict())

        return {
            "message": "Upload thành công",
            "paper_id": paper_id,
            "file_path": file_path,
            "hash": metadata.file_hash_sha256,
        }

    except PipelineError as e:
        _storage.delete(file_path)
        raise HTTPException(status_code=400, detail=str(e))


# ─────────────────────────────────────────────
# PDF List & Stats Endpoints
# ─────────────────────────────────────────────

@router.get("/pdfs")
def list_pdfs(page: int = 1, limit: int = 20):
    """Danh sách PDF đã thu thập."""
    repo = _get_repo()
    if repo:
        items = repo.list_papers(page=page, limit=limit)
        total = repo.count()
        return {
            "items": items,
            "page": page,
            "limit": limit,
            "total": total,
        }

    # Fallback: đọc từ file system
    scrape_dir = Path(settings.SCRAPE_DIR)
    upload_dir = Path(settings.UPLOAD_DIR)

    pdf_files = []
    for directory in [scrape_dir, upload_dir]:
        if directory.exists():
            for pdf_file in directory.rglob("*.pdf"):
                stat = pdf_file.stat()
                pdf_files.append({
                    "filename": pdf_file.name,
                    "file_path": str(pdf_file),
                    "file_size_bytes": stat.st_size,
                    "source": "scrape" if scrape_dir in pdf_file.parents or pdf_file.parent == scrape_dir else "upload",
                    "scraped_at": stat.st_mtime,
                })

    # Sort by modified time descending
    pdf_files.sort(key=lambda x: x.get("scraped_at", 0), reverse=True)

    start = (page - 1) * limit
    end = start + limit

    return {
        "items": pdf_files[start:end],
        "page": page,
        "limit": limit,
        "total": len(pdf_files),
    }


@router.get("/stats")
def get_stats():
    """Thống kê tổng quan."""
    repo = _get_repo()
    if repo:
        return repo.get_scrape_stats()

    # Fallback: count files
    scrape_dir = Path(settings.SCRAPE_DIR)
    upload_dir = Path(settings.UPLOAD_DIR)

    scraped = len(list(scrape_dir.rglob("*.pdf"))) if scrape_dir.exists() else 0
    uploaded = len(list(upload_dir.rglob("*.pdf"))) if upload_dir.exists() else 0

    return {
        "total": scraped + uploaded,
        "scraped": scraped,
        "uploaded": uploaded,
    }
