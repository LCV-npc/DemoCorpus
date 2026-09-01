"""
infrastructure/database/repositories/paper_repository.py
CRUD operations cho papers collection trong MongoDB.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from pymongo import ASCENDING, TEXT
from pymongo.errors import DuplicateKeyError

from infrastructure.database.mongo_client import get_db

logger = logging.getLogger(__name__)


class PaperRepository:
    """Repository cho collection 'papers' trong MongoDB."""

    def __init__(self, db=None):
        self.db = db if db is not None else get_db()
        self.papers = self.db["papers"]
        self._ensure_indexes()
        logger.info("PaperRepository initialized")

    def _ensure_indexes(self) -> None:
        """
        Tạo indexes cho tìm kiếm và deduplication.

        Index justification:
        - paper_id (unique): primary lookup key
        - file_hash_sha256 (unique, sparse): duplicate PDF detection
        - extracted.title + extracted.abstract (text): full-text search
        - confidence.overall: filter papers by quality score
        - processing.created_at: sort by creation date
        - source: filter by source type (upload/scrape/local)
        """
        try:
            # Unique index on paper_id
            self.papers.create_index("paper_id", unique=True)
            # Unique index on file hash (duplicate detection)
            self.papers.create_index("file_hash_sha256", unique=True, sparse=True)
            # Text index cho search
            self.papers.create_index([
                ("extracted.title", TEXT),
                ("extracted.abstract", TEXT),
            ])
            # Index for listing/filtering
            self.papers.create_index([("confidence.overall", ASCENDING)])
            self.papers.create_index([("processing.created_at", ASCENDING)])
            # Index for source type filtering
            self.papers.create_index([("source", ASCENDING)])
            logger.info("Database indexes ensured")
        except Exception as e:
            logger.warning(f"Index creation warning: {e}")

    # ── CRUD Operations ──

    def insert_paper(self, metadata_dict: dict) -> str:
        """
        Insert paper metadata vào MongoDB.

        Tự động thêm created_at/updated_at timestamps nếu chưa có.

        Args:
            metadata_dict: Output của ExtractedMetadata.to_dict()

        Returns:
            paper_id

        Raises:
            DuplicateKeyError nếu hash đã tồn tại.
        """
        now = datetime.now(timezone.utc).isoformat()

        # Ensure timestamps
        if "processing" not in metadata_dict:
            metadata_dict["processing"] = {}
        metadata_dict["processing"].setdefault("created_at", now)
        metadata_dict.setdefault("updated_at", now)

        try:
            self.papers.insert_one(metadata_dict)
            paper_id = metadata_dict["paper_id"]
            logger.info(f"Inserted paper: {paper_id}")
            return paper_id
        except DuplicateKeyError:
            file_hash = metadata_dict.get("file_hash_sha256", "unknown")
            paper_id = metadata_dict.get("paper_id", "unknown")
            logger.warning(
                f"Duplicate paper detected: paper_id={paper_id}, "
                f"file_hash={file_hash[:16]}..."
            )
            raise

    def get_paper(self, paper_id: str) -> Optional[dict]:
        """Lấy paper theo paper_id."""
        doc = self.papers.find_one({"paper_id": paper_id}, {"_id": 0})
        return doc

    def get_by_hash(self, file_hash: str) -> Optional[dict]:
        """Tìm paper theo SHA-256 hash (duplicate detection)."""
        doc = self.papers.find_one({"file_hash_sha256": file_hash}, {"_id": 0})
        return doc

    def list_papers(
        self,
        page: int = 1,
        limit: int = 20,
        min_confidence: float = 0.0,
    ) -> list[dict]:
        """
        Phân trang danh sách papers.

        Args:
            page: Số trang (1-indexed).
            limit: Số items/trang.
            min_confidence: Lọc confidence tối thiểu.
        """
        query = {}
        if min_confidence > 0:
            query["confidence.overall"] = {"$gte": min_confidence}

        skip = (page - 1) * limit
        cursor = (
            self.papers
            .find(query, {"_id": 0})
            .sort("processing.created_at", -1)
            .skip(skip)
            .limit(limit)
        )
        return list(cursor)

    def search_papers(self, query: str, limit: int = 20) -> list[dict]:
        """Full-text search trên title và abstract."""
        cursor = (
            self.papers
            .find(
                {"$text": {"$search": query}},
                {"_id": 0, "score": {"$meta": "textScore"}},
            )
            .sort([("score", {"$meta": "textScore"})])
            .limit(limit)
        )
        return list(cursor)

    def update_paper(self, paper_id: str, fields: dict) -> bool:
        """
        Update fields cho paper.
        Tự động set updated_at timestamp.
        """
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        result = self.papers.update_one(
            {"paper_id": paper_id},
            {"$set": fields},
        )
        # Idempotent PATCH requests still succeed when the document matched
        # but already had the requested values.
        return result.matched_count > 0

    def delete_paper(self, paper_id: str) -> bool:
        """Xóa paper theo paper_id. Dùng chủ yếu cho testing/cleanup."""
        result = self.papers.delete_one({"paper_id": paper_id})
        if result.deleted_count > 0:
            logger.info(f"Deleted paper: {paper_id}")
            return True
        return False

    def count(self, query: dict | None = None) -> int:
        """Đếm số papers."""
        return self.papers.count_documents(query or {})

    # ── Scraped PDF Records ──

    def insert_scraped_pdf(self, record: dict) -> str:
        """Insert record cho PDF đã crawl."""
        record.setdefault("scraped_at", datetime.now(timezone.utc).isoformat())
        self.papers.insert_one(record)
        return record.get("paper_id", "")

    def is_url_scraped(self, url: str) -> bool:
        """Kiểm tra URL đã crawl chưa."""
        return self.papers.find_one({"source_url": url}) is not None

    def get_scrape_stats(self) -> dict:
        """Thống kê tổng quan."""
        total = self.papers.count_documents({})
        scraped = self.papers.count_documents({"source": "scrape"})
        uploaded = self.papers.count_documents({"source": "upload"})
        return {
            "total": total,
            "scraped": scraped,
            "uploaded": uploaded,
        }
