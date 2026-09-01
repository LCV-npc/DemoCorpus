"""
app/routers/scraper_router.py
API endpoints cho scraping, upload, và quản lý PDF.
"""

import threading
import uuid
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from config.settings import settings
from app.dependencies import require_write_access
from config.constants import MAX_FILE_SIZE_BYTES, PDF_MAGIC_BYTES
from infrastructure.scraper.pdf_scraper import PDFScraper, scrape_status
from infrastructure.scraper.url_safety import UnsafeURL, validate_public_http_url
from core.pipeline.extractor_pipeline import PipelineError
from infrastructure.database.persistence_service import (
    DuplicatePaperError,
    PersistenceError,
    PersistenceService,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Shared instances
_scraper = PDFScraper()
_scrape_thread: threading.Thread | None = None
_extraction_thread: threading.Thread | None = None

# MongoDB repository (lazy init)
_repo = None


class ExtractionStatus:
    """Thread-safe status for metadata extraction of stored scraped PDFs."""

    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.running = False
            self.done = False
            self.stop_requested = False
            self.stopped = False
            self.total = 0
            self.completed = 0
            self.extracted = 0
            self.skipped = 0
            self.failed = 0
            self.current_filename = ""
            self.errors: list[str] = []

    def try_start(self, total: int, skipped: int) -> bool:
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.done = False
            self.stop_requested = False
            self.stopped = False
            self.total = total
            self.completed = 0
            self.extracted = 0
            self.skipped = skipped
            self.failed = 0
            self.current_filename = ""
            self.errors = []
            return True

    def request_stop(self) -> bool:
        with self._lock:
            if not self.running:
                return False
            self.stop_requested = True
            return True

    def should_stop(self) -> bool:
        with self._lock:
            return self.stop_requested

    def set_current(self, filename: str) -> None:
        with self._lock:
            self.current_filename = filename

    def record_success(self) -> None:
        with self._lock:
            self.completed += 1
            self.extracted += 1

    def record_failure(self, filename: str, error: Exception) -> None:
        with self._lock:
            self.completed += 1
            self.failed += 1
            self.errors.append(f"{filename}: {error}")
            self.errors = self.errors[-20:]

    def complete(self, *, stopped: bool = False) -> None:
        with self._lock:
            self.running = False
            self.done = True
            self.stopped = stopped
            self.current_filename = ""

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "done": self.done,
                "stop_requested": self.stop_requested,
                "stopped": self.stopped,
                "total": self.total,
                "completed": self.completed,
                "extracted": self.extracted,
                "skipped": self.skipped,
                "failed": self.failed,
                "current_filename": self.current_filename,
                "errors": list(self.errors),
            }


extraction_status = ExtractionStatus()


def _get_repo():
    global _repo
    if _repo is None:
        try:
            from infrastructure.database.repositories.paper_repository import PaperRepository
            _repo = PaperRepository()
        except Exception as e:
            logger.warning(f"MongoDB not available: {e}. Running without database.")
    return _repo


def _path_key(path: str | Path) -> str:
    """Return a stable, case-insensitive key for a local Windows path."""
    return str(Path(path).resolve()).casefold()


def _scraped_records_by_path() -> dict[str, dict]:
    """Index MongoDB records by their PDF path without inventing file entries."""
    repo = _get_repo()
    if repo is None:
        return {}

    try:
        records = repo.papers.find({"source": "scrape"}, {"_id": 0})
        return {
            _path_key(record["file_path"]): record
            for record in records
            if isinstance(record.get("file_path"), str) and record["file_path"]
        }
    except Exception as exc:
        logger.warning("Could not load scraped PDF metadata: %s", exc)
        return {}


def _has_pipeline_result(record: dict | None) -> bool:
    if not record:
        return False
    steps = record.get("processing", {}).get("steps_completed")
    if not isinstance(steps, list) or not steps:
        return False
    # A crawl record has only the lightweight "scrape" step.  It is not
    # metadata extraction, even though it already has a paper id and a hash.
    # FullPipeline always records text_extraction before it can produce the
    # title, author and abstract shown in the library/detail views.
    if "text_extraction" not in steps:
        return False
    # A record is considered extracted once the PDF text pipeline has run.
    # Optional later stages (including LLM enhancement) must not make the
    # bulk action process the same PDF again. Users can explicitly re-extract
    # an individual row when they want to refresh its metadata.
    return True


def _stored_scraped_pdfs(query: str = "") -> list[dict]:
    """List PDFs that physically exist under the configured scrape folder."""
    scrape_dir = Path(settings.SCRAPE_DIR)
    if not scrape_dir.exists():
        return []

    needle = query.strip().lower()
    records_by_path = _scraped_records_by_path()
    items = []
    for pdf_file in scrape_dir.rglob("*.pdf"):
        if not pdf_file.is_file():
            continue
        record = records_by_path.get(_path_key(pdf_file))
        extracted_ready = _has_pipeline_result(record)
        extracted = record.get("extracted", {}) if record and extracted_ready else {}
        searchable = " ".join([
            pdf_file.name,
            str(extracted.get("title", "")),
            " ".join(extracted.get("authors", [])),
            str(extracted.get("abstract", "")),
        ]).lower()
        if needle and needle not in searchable:
            continue

        stat = pdf_file.stat()
        item = {
            "filename": pdf_file.name,
            "file_path": str(pdf_file.resolve()),
            "file_size_bytes": stat.st_size,
            "source": "scrape",
            "scraped_at": stat.st_mtime,
            "extracted": extracted,
            "extracted_ready": extracted_ready,
        }
        if record:
            for key in ("paper_id", "confidence", "validation", "processing"):
                if key in record:
                    item[key] = record[key]
        items.append(item)

    return sorted(items, key=lambda item: item["scraped_at"], reverse=True)


def _public_current_crawl_record(record: dict) -> dict:
    """Remove local filesystem paths before returning a transient crawl record."""
    public_record = record.copy()
    public_record.pop("file_path", None)
    public_record.pop("pdf_path", None)
    return public_record


# ─────────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────────

class ScrapeRequest(BaseModel):
    url: str
    max_depth: int = Field(default=2, ge=0, le=5)
    start_year: int | None = Field(default=None, ge=1900)
    end_year: int | None = Field(default=None, ge=1900)


class CrawlRequest(BaseModel):
    website_url: str
    start_year: int = Field(ge=1900)
    end_year: int = Field(ge=1900)
    max_depth: int = Field(default=2, ge=0, le=5)


class ScrapeResponse(BaseModel):
    message: str
    status: str


class ExtractScrapedRequest(BaseModel):
    force: bool = False


def _normalize_year_range(start_year: int | None, end_year: int | None) -> tuple[int | None, int | None]:
    if start_year is None and end_year is None:
        return None, None
    if start_year is None or end_year is None:
        raise HTTPException(status_code=422, detail="start_year and end_year must be provided together")
    current_year = datetime.now().year
    if end_year > current_year:
        end_year = current_year
    if start_year > end_year:
        raise HTTPException(status_code=422, detail="start_year must not exceed end_year")
    if end_year - start_year + 1 > settings.MAX_YEAR_RANGE:
        raise HTTPException(status_code=422, detail=f"year range must not exceed {settings.MAX_YEAR_RANGE} years")
    return start_year, end_year


# ─────────────────────────────────────────────
# Scraping Endpoints
# ─────────────────────────────────────────────

@router.post("/scrape")
def start_scrape(request: ScrapeRequest, _: None = Depends(require_write_access)):
    """Bắt đầu scraping PDF từ URL."""
    global _scrape_thread
    try:
        url = validate_public_http_url(request.url)
    except UnsafeURL as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    start_year, end_year = _normalize_year_range(request.start_year, request.end_year)
    if not scrape_status.try_start():
        raise HTTPException(status_code=409, detail="Đang có tiến trình scraping chạy")

    def _run():
        try:
            _scraper.scrape(
                url=url, max_depth=request.max_depth, start_year=start_year,
                end_year=end_year, status_started=True, complete_status=False,
            )
            if scrape_status.to_dict().get("job_phase") != "quota_reached":
                scrape_status.set_job_phase("finalizing")
            # Keep the job reserved until its records are durable. Otherwise a
            # new crawl can reset the shared record list between download and
            # persistence, leaving files that future duplicate checks cannot
            # see in MongoDB.
            repo = _get_repo()
            records = scrape_status.snapshot_pdf_records()
            persisted_urls: set[str] = set()
            duplicate_urls: set[str] = set()
            if repo:
                for record in records:
                    try:
                        repo.insert_paper(record.copy())
                        pdf_url = record.get("pdf_url")
                        if isinstance(pdf_url, str):
                            persisted_urls.add(pdf_url)
                    except DuplicateKeyError:
                        pdf_url = record.get("pdf_url")
                        if isinstance(pdf_url, str):
                            duplicate_urls.add(pdf_url)
                        logger.info("Scraped PDF is already persisted: %s", pdf_url)
                    except Exception as e:
                        logger.warning(f"Could not save to MongoDB: {e}")
            _scraper.finalize_manifest_records(
                records, persisted_urls, duplicate_urls
            )
        finally:
            scrape_status.complete()
            current = scrape_status.to_dict()
            scrape_status.log(
                "🏁 Hoàn tất! "
                f"Tải: {current['downloaded']}, "
                f"Bỏ qua: {current['skipped']}, "
                f"Trùng: {current['duplicates']}, "
                f"Lỗi: {current['errors']}"
            )

    _scrape_thread = threading.Thread(target=_run, daemon=True)
    _scrape_thread.start()

    return {"message": "Đã bắt đầu quét", "status": "started"}


@router.post("/crawl")
def start_crawl(request: CrawlRequest, _: None = Depends(require_write_access)):
    """Start a non-blocking crawl with an explicit inclusive year range."""
    start_year, end_year = _normalize_year_range(request.start_year, request.end_year)
    start_scrape(
        ScrapeRequest(
            url=request.website_url,
            start_year=start_year,
            end_year=end_year,
            max_depth=request.max_depth,
        ),
        _,
    )
    return {
        "job_id": str(uuid.uuid4()),
        "website": request.website_url,
        "start_year": start_year,
        "end_year": end_year,
        "status": "started",
    }


@router.get("/scrape/status")
def get_scrape_status():
    """Lấy trạng thái scraping realtime."""
    return scrape_status.to_dict()


@router.get("/scrape/results")
def list_current_crawl_results(
    page: int = Query(1, ge=1, description="Số trang (1-indexed)"),
    limit: int = Query(10, ge=1, le=100, description="Số kết quả mỗi trang"),
    q: str = Query("", description="Từ khóa trong kết quả của lượt crawl hiện tại"),
):
    """List files downloaded in this in-process crawl session only.

    The list is reset at the start of every crawl. Persistent PDFs and their
    metadata belong to the separate PDF library.
    """
    needle = q.strip().casefold()
    records = scrape_status.snapshot_pdf_records()
    if needle:
        records = [
            record
            for record in records
            if needle in " ".join(
                [
                    str(record.get("filename", "")),
                    str(record.get("extracted", {}).get("title", "")),
                    " ".join(record.get("extracted", {}).get("authors", [])),
                    str(record.get("extracted", {}).get("abstract", "")),
                ]
            ).casefold()
        ]

    total = len(records)
    start = (page - 1) * limit
    return {
        "items": [_public_current_crawl_record(record) for record in records[start:start + limit]],
        "total": total,
        "page": page,
        "limit": limit,
        "scope": "current_crawl_session",
    }


@router.get("/scrape/results/{paper_id}")
def get_current_crawl_result(paper_id: str):
    """Get one transient result, without falling back to the PDF library."""
    for record in scrape_status.snapshot_pdf_records():
        if record.get("paper_id") == paper_id:
            return _public_current_crawl_record(record)
    raise HTTPException(status_code=404, detail=f"Không tìm thấy kết quả trong lượt crawl hiện tại: {paper_id}")


@router.post("/scrape/stop")
def stop_scrape(_: None = Depends(require_write_access)):
    """Dừng scraping."""
    if not scrape_status.request_stop():
        raise HTTPException(status_code=400, detail="Không có tiến trình đang chạy")

    return {"message": "Đã gửi yêu cầu dừng", "status": "stopping"}


# ─────────────────────────────────────────────
# Upload Endpoint
# ─────────────────────────────────────────────
# NOTE: Upload endpoint đã được chuyển sang paper_router.py
# với full pipeline M1–M9. Xem app/routers/paper_router.py.


# ─────────────────────────────────────────────
# PDF List & Stats Endpoints
# ─────────────────────────────────────────────

def _start_extraction_job(
    *,
    pending: list[dict],
    records_by_path: dict[str, dict],
    skipped: int,
    repo,
) -> None:
    """Start one shared background job for bulk or single-PDF extraction."""
    global _extraction_thread
    if not extraction_status.try_start(len(pending), skipped):
        raise HTTPException(status_code=409, detail="Metadata extraction is already running")

    def _run_extraction() -> None:
        persistence = PersistenceService(repo=repo)
        stopped_early = False
        try:
            for item in pending:
                if extraction_status.should_stop():
                    stopped_early = True
                    break
                path = item["file_path"]
                filename = item["filename"]
                extraction_status.set_current(filename)
                record = records_by_path.get(_path_key(path), {})
                source_url = (
                    record.get("article_url")
                    or record.get("source_journal_url")
                    or record.get("source_url")
                    or ""
                )
                try:
                    source_metadata = _scraper.extract_source_metadata(source_url)
                    persistence.process_and_update_existing(
                        file_path=path,
                        source="scrape",
                        source_url=source_url,
                        paper_id=record.get("paper_id", ""),
                        enable_llm=True,
                        source_metadata=source_metadata,
                    )
                    extraction_status.record_success()
                except (DuplicatePaperError, PersistenceError, PipelineError) as exc:
                    logger.warning("Metadata extraction failed for %s: %s", filename, exc)
                    extraction_status.record_failure(filename, exc)
                except Exception as exc:
                    logger.exception("Unexpected metadata extraction error for %s", filename)
                    extraction_status.record_failure(filename, exc)
        finally:
            extraction_status.complete(stopped=stopped_early)

    _extraction_thread = threading.Thread(target=_run_extraction, daemon=True)
    _extraction_thread.start()


def _ensure_extraction_available():
    if scrape_status.to_dict()["running"]:
        raise HTTPException(
            status_code=409,
            detail="Wait for the crawl to finish before extracting metadata",
        )
    repo = _get_repo()
    if repo is None:
        raise HTTPException(
            status_code=503,
            detail="MongoDB is required to save extracted metadata",
        )
    return repo


@router.post("/scrape/extract")
def extract_scraped_pdfs(
    request: ExtractScrapedRequest,
    _: None = Depends(require_write_access),
):
    """Extract only stored PDFs that have not completed metadata extraction."""
    repo = _ensure_extraction_available()
    records_by_path = _scraped_records_by_path()
    all_files = _stored_scraped_pdfs()
    pending = [
        item for item in all_files
        if request.force or not _has_pipeline_result(
            records_by_path.get(_path_key(item["file_path"]))
        )
    ]
    skipped = len(all_files) - len(pending)
    if not pending:
        return {
            "status": "nothing_to_extract",
            "total_files": len(all_files),
            "skipped": skipped,
        }

    _start_extraction_job(
        pending=pending,
        records_by_path=records_by_path,
        skipped=skipped,
        repo=repo,
    )
    return {
        "status": "started",
        "total_files": len(pending),
        "skipped": skipped,
        "llm_enabled": True,
    }


@router.post("/scrape/extract/stop")
def stop_metadata_extraction(_: None = Depends(require_write_access)):
    """Request a safe stop after the PDF currently being processed."""
    if not extraction_status.request_stop():
        raise HTTPException(status_code=400, detail="Metadata extraction is not running")
    return {"status": "stopping", "message": "Stop requested"}


@router.get("/scrape/extract/status")
def get_extraction_status():
    """Return the live status of the current or last metadata extraction job."""
    return extraction_status.to_dict()


@router.post("/pdfs/{paper_id}/extract")
def extract_one_scraped_pdf(
    paper_id: str,
    _: None = Depends(require_write_access),
):
    """Extract or re-extract metadata for one stored PDF."""
    repo = _ensure_extraction_available()
    records_by_path = _scraped_records_by_path()
    item = next(
        (candidate for candidate in _stored_scraped_pdfs() if candidate.get("paper_id") == paper_id),
        None,
    )
    if item is None:
        raise HTTPException(status_code=404, detail=f"Stored PDF not found: {paper_id}")

    _start_extraction_job(
        pending=[item],
        records_by_path=records_by_path,
        skipped=0,
        repo=repo,
    )
    return {
        "status": "started",
        "paper_id": paper_id,
        "filename": item["filename"],
        "total_files": 1,
        "skipped": 0,
        "llm_enabled": True,
    }


@router.get("/pdfs")
def list_pdfs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    q: str = Query("", max_length=200),
):
    """Danh sách PDF đã thu thập."""
    pdf_files = _stored_scraped_pdfs(q)

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
    stored_pdfs = _stored_scraped_pdfs()
    stored_count = len(stored_pdfs)
    registered_count = sum(1 for item in stored_pdfs if item.get("paper_id"))

    paper_records = None
    scraped_records = None
    repo = _get_repo()
    if repo is not None:
        try:
            repository_stats = repo.get_scrape_stats()
            paper_records = repository_stats["total"]
            scraped_records = repository_stats["scraped"]
        except Exception as exc:
            logger.warning("Could not load MongoDB statistics: %s", exc)

    current = scrape_status.to_dict()
    return {
        # Preserve the existing fields for API compatibility. They count PDF
        # files in storage, while the new fields expose MongoDB coverage.
        "total": stored_count,
        "scraped": stored_count,
        "uploaded": 0,
        "storage_files": stored_count,
        "registered_files": registered_count,
        "unregistered_files": stored_count - registered_count,
        "paper_records": paper_records,
        "scraped_records": scraped_records,
        "current_job": {
            key: current[key]
            for key in ("running", "downloaded", "duplicates", "errors", "done")
        },
    }
