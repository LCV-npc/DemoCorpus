"""Durable crawl catalog for resumable, quota-limited downloads.

The crawler may need to inspect thousands of article pages once to establish
the exact publication range.  A manifest stores that expensive discovery
result separately from the PDF files, so later 500-file batches can resume
from MongoDB without rediscovering the publisher archive.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit

from pymongo import ASCENDING

from infrastructure.database.mongo_client import get_db

logger = logging.getLogger(__name__)

MANIFEST_SCHEMA_VERSION = 1
TERMINAL_STATES = frozenset({"saved", "duplicate", "blocked", "invalid", "out_of_range"})


class CrawlManifestStore:
    """Store catalog metadata and its per-PDF queue in MongoDB."""

    def __init__(self, db=None):
        self.db = db if db is not None else get_db()
        self.manifests = self.db["crawl_manifests"]
        self.candidates = self.db["crawl_candidates"]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        self.manifests.create_index("manifest_key", unique=True)
        self.candidates.create_index(
            [("manifest_id", ASCENDING), ("pdf_url", ASCENDING)], unique=True
        )
        self.candidates.create_index(
            [("manifest_id", ASCENDING), ("state", ASCENDING), ("position", ASCENDING)]
        )

    @staticmethod
    def normalize_source_url(url: str) -> str:
        parsed = urlsplit(url.strip())
        path = parsed.path.rstrip("/") or "/"
        return urlunsplit(
            (parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, "")
        )

    @classmethod
    def manifest_key(
        cls,
        source_url: str,
        start_year: int | None,
        end_year: int | None,
        adapter_name: str,
        max_depth: int,
    ) -> str:
        identity = {
            "adapter": adapter_name.lower(),
            "end_year": end_year,
            "max_depth": max_depth,
            "schema": MANIFEST_SCHEMA_VERSION,
            "source_url": cls.normalize_source_url(source_url),
            "start_year": start_year,
        }
        encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def find_ready(
        self,
        source_url: str,
        start_year: int | None,
        end_year: int | None,
        adapter_name: str,
        max_depth: int,
    ) -> dict | None:
        key = self.manifest_key(
            source_url, start_year, end_year, adapter_name, max_depth
        )
        manifest = self.manifests.find_one(
            {
                "manifest_key": key,
                "state": "ready",
                "schema_version": MANIFEST_SCHEMA_VERSION,
            },
            {"_id": 0},
        )
        if manifest:
            self.manifests.update_one(
                {"manifest_key": key},
                {"$set": {"last_used_at": self._now()}},
            )
        return manifest

    def replace_ready(
        self,
        source_url: str,
        start_year: int | None,
        end_year: int | None,
        adapter_name: str,
        max_depth: int,
        candidates: Iterable[dict],
    ) -> dict:
        """Atomically publish a newly discovered ordered catalog.

        Candidate rows are intentionally separate documents: a large journal
        can exceed MongoDB's 16MB document limit if its full queue is embedded
        in one manifest document.
        """
        source_url = self.normalize_source_url(source_url)
        key = self.manifest_key(
            source_url, start_year, end_year, adapter_name, max_depth
        )
        now = self._now()
        existing = self.manifests.find_one({"manifest_key": key}) or {}
        manifest_id = existing.get("manifest_id") or str(uuid.uuid4())

        unique_candidates: list[dict] = []
        seen_urls: set[str] = set()
        for candidate in candidates:
            pdf_url = candidate.get("pdf_url")
            if not isinstance(pdf_url, str) or not pdf_url or pdf_url in seen_urls:
                continue
            seen_urls.add(pdf_url)
            unique_candidates.append(candidate)

        total = len(unique_candidates)
        base_document = {
            "manifest_id": manifest_id,
            "source_url": source_url,
            "start_year": start_year,
            "end_year": end_year,
            "adapter_name": adapter_name,
            "max_depth": max_depth,
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "state": "building",
            "candidate_total": total,
            "pending_count": total,
            "state_counts": {"pending": total},
            "updated_at": now,
            "last_used_at": now,
        }
        self.manifests.update_one(
            {"manifest_key": key},
            {"$set": base_document, "$setOnInsert": {"manifest_key": key, "created_at": now}},
            upsert=True,
        )

        self.candidates.delete_many({"manifest_id": manifest_id})
        for start in range(0, total, 1000):
            documents = []
            for position, candidate in enumerate(
                unique_candidates[start:start + 1000], start=start + 1
            ):
                documents.append(
                    {
                        "manifest_id": manifest_id,
                        "pdf_url": candidate["pdf_url"],
                        "article_url": candidate.get("article_url", ""),
                        "publication_year": candidate.get("publication_year"),
                        "publication_date": candidate.get("publication_date"),
                        "year_detection_status": candidate.get("year_detection_status", "unknown"),
                        "year_detection_source": candidate.get("year_detection_source", "manifest"),
                        "position": position,
                        "state": "pending",
                        "attempts": 0,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
            if documents:
                self.candidates.insert_many(documents, ordered=True)

        self.manifests.update_one(
            {"manifest_key": key},
            {"$set": {"state": "ready", "updated_at": self._now()}},
        )
        return self.manifests.find_one({"manifest_key": key}, {"_id": 0}) or {}

    def pending_candidates(self, manifest_id: str) -> list[dict]:
        return list(
            self.candidates.find(
                {"manifest_id": manifest_id, "state": "pending"}, {"_id": 0}
            ).sort("position", ASCENDING)
        )

    def mark_terminal(self, manifest_id: str, pdf_url: str, state: str) -> bool:
        if state not in TERMINAL_STATES:
            raise ValueError(f"Unsupported terminal manifest state: {state}")
        now = self._now()
        result = self.candidates.update_one(
            {"manifest_id": manifest_id, "pdf_url": pdf_url, "state": "pending"},
            {"$set": {"state": state, "updated_at": now, "completed_at": now}},
        )
        if result.modified_count:
            self.manifests.update_one(
                {"manifest_id": manifest_id},
                {
                    "$inc": {
                        "pending_count": -1,
                        "state_counts.pending": -1,
                        f"state_counts.{state}": 1,
                    },
                    "$set": {"updated_at": now},
                },
            )
            return True
        return False

    def mark_known_urls(
        self,
        manifest_id: str,
        urls: Iterable[str],
        state: str = "duplicate",
    ) -> int:
        """Settle already-persisted URLs before scheduling a new batch.

        This avoids walking hundreds of known records one by one when a
        catalog is first created for a corpus that already contains PDFs.
        URLs are chunked so the query remains safely below MongoDB's document
        size limit even for very large corpora.
        """
        if state not in TERMINAL_STATES:
            raise ValueError(f"Unsupported terminal manifest state: {state}")

        unique_urls = list(
            dict.fromkeys(url for url in urls if isinstance(url, str) and url)
        )
        if not unique_urls:
            return 0

        now = self._now()
        settled = 0
        for start in range(0, len(unique_urls), 500):
            batch = unique_urls[start:start + 500]
            result = self.candidates.update_many(
                {
                    "manifest_id": manifest_id,
                    "pdf_url": {"$in": batch},
                    "state": "pending",
                },
                {"$set": {"state": state, "updated_at": now, "completed_at": now}},
            )
            settled += result.modified_count

        if settled:
            self.manifests.update_one(
                {"manifest_id": manifest_id},
                {
                    "$inc": {
                        "pending_count": -settled,
                        "state_counts.pending": -settled,
                        f"state_counts.{state}": settled,
                    },
                    "$set": {"updated_at": now},
                },
            )
        return settled

    def record_retry(self, manifest_id: str, pdf_url: str, error: str = "") -> None:
        update: dict = {"$inc": {"attempts": 1}, "$set": {"updated_at": self._now()}}
        if error:
            update["$set"]["last_error"] = error[:500]
        self.candidates.update_one(
            {"manifest_id": manifest_id, "pdf_url": pdf_url, "state": "pending"}, update
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
