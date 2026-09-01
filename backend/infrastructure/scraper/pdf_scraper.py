"""
infrastructure/scraper/pdf_scraper.py
Web crawler: nhận URL bất kỳ → tìm tất cả PDF y khoa → tải về và tổ chức lưu trữ.

Hỗ trợ:
- OJS (Open Journal Systems) — nhận diện qua URL pattern
- Tạp chí có link PDF trực tiếp
- Generic website — crawl tất cả link PDF

Medical filter: chỉ tải PDF từ trang có nội dung y khoa.
"""

import hashlib
import logging
import os
import random
import re
import time
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator
from urllib.parse import urljoin, urlparse, unquote
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.constants import (
    MEDICAL_KEYWORDS_ALL,
    MEDICAL_KEYWORD_THRESHOLD,
    DEFAULT_RATE_LIMIT_MIN,
    DEFAULT_RATE_LIMIT_MAX,
    MAX_PAGES_TO_CRAWL,
    MAX_PDFS,
    ROBOTS_TXT_ENABLED,
    REQUEST_TIMEOUT,
    USER_AGENT,
    MAX_FILE_SIZE_BYTES,
    PDF_MAGIC_BYTES,
)
from config.settings import settings
from core.abstract_detection.language import select_preferred_abstract
from core.data_cleaning.text_cleaner import TextCleaner
from infrastructure.scraper.url_safety import validate_public_http_url
from infrastructure.scraper.site_detector import SiteDetector
from infrastructure.scraper.publication_date import PublicationDate, PublicationDateExtractor
from infrastructure.scraper.scraped_pdf_path import ScrapedPDFPathBuilder

logger = logging.getLogger(__name__)


class ScrapeStatus:
    """Thread-safe trạng thái scraping."""

    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        with self._lock:
            self.running = False
            self.should_stop = False
            self.total_found = 0
            self.downloaded = 0
            self.skipped = 0
            self.duplicates = 0
            self.errors = 0
            self.current_url = ""
            self.error_message = ""
            self.done = False
            self.job_phase = "idle"
            self.current_year: int | None = None
            self.discovery_phase = "idle"
            self.discovery_current = 0
            self.discovery_total = 0
            self.catalog_total = 0
            self.catalog_pending = 0
            self.batch_total = 0
            self.batch_processed = 0
            self.manifest_reused = False
            self.years: dict[str, dict[str, int]] = {}
            self.log_messages: list[dict] = []
            self.pdf_records: list[dict] = []

    def try_start(self) -> bool:
        """Atomically reserve the single in-process scraper slot."""
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.should_stop = False
            self.total_found = self.downloaded = self.skipped = 0
            self.duplicates = self.errors = 0
            self.current_url = self.error_message = ""
            self.done = False
            self.job_phase = "discovery"
            self.current_year = None
            self.discovery_phase = "archive"
            self.discovery_current = 0
            self.discovery_total = 0
            self.catalog_total = 0
            self.catalog_pending = 0
            self.batch_total = 0
            self.batch_processed = 0
            self.manifest_reused = False
            self.years = {}
            self.log_messages = []
            self.pdf_records = []
            return True

    def request_stop(self) -> bool:
        with self._lock:
            if not self.running:
                return False
            self.should_stop = True
            return True

    def complete(self) -> None:
        with self._lock:
            self.running = False
            self.done = True
            self.job_phase = "completed"

    def set_job_phase(self, phase: str) -> None:
        """Expose the current high-level phase without changing counters."""
        with self._lock:
            self.job_phase = phase

    def add_pdf_record(self, record: dict) -> None:
        """Add one result to the current crawl session safely."""
        with self._lock:
            self.pdf_records.append(record)

    def set_discovery_progress(
        self,
        phase: str,
        current: int = 0,
        total: int = 0,
        current_url: str = "",
    ) -> None:
        """Expose deterministic discovery progress before PDFs are counted."""
        with self._lock:
            self.discovery_phase = phase
            self.discovery_current = max(0, current)
            self.discovery_total = max(0, total)
            if current_url:
                self.current_url = current_url

    def set_catalog_progress(
        self, total: int, pending: int, batch_total: int, reused: bool
    ) -> None:
        """Set the durable catalog state used by resumable crawl batches."""
        with self._lock:
            self.catalog_total = max(0, total)
            self.catalog_pending = max(0, pending)
            self.batch_total = max(0, batch_total)
            self.batch_processed = 0
            self.manifest_reused = reused

    def mark_catalog_terminal(self, count: int = 1) -> None:
        """Reflect permanently handled catalog items in the live UI."""
        with self._lock:
            self.catalog_pending = max(0, self.catalog_pending - max(0, count))

    def mark_batch_processed(self, count: int = 1) -> None:
        """Advance the visible progress for the current download batch."""
        with self._lock:
            self.batch_processed = max(0, self.batch_processed + max(0, count))

    def snapshot_pdf_records(self) -> list[dict]:
        """Return a stable copy of results downloaded by the current crawl only."""
        with self._lock:
            return [record.copy() for record in self.pdf_records]

    def log(self, msg: str, level: str = "info"):
        with self._lock:
            entry = {
                "time": datetime.now().strftime("%H:%M:%S"),
                "message": msg,
                "level": level,
            }
            self.log_messages.append(entry)
            # Giữ tối đa 500 logs
            if len(self.log_messages) > 500:
                self.log_messages = self.log_messages[-500:]
        if level == "error":
            logger.error(msg)
        else:
            logger.info(msg)

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "should_stop": self.should_stop,
                "total_found": self.total_found,
                "downloaded": self.downloaded,
                "skipped": self.skipped,
                "duplicates": self.duplicates,
                "errors": self.errors,
                "current_url": self.current_url,
                "error_message": self.error_message,
                "done": self.done,
                "job_phase": self.job_phase,
                "current_year": self.current_year,
                "discovery_phase": self.discovery_phase,
                "discovery_current": self.discovery_current,
                "discovery_total": self.discovery_total,
                "catalog_total": self.catalog_total,
                "catalog_pending": self.catalog_pending,
                "batch_total": self.batch_total,
                "batch_processed": self.batch_processed,
                "manifest_reused": self.manifest_reused,
                "years": {year: dict(stats) for year, stats in self.years.items()},
                "log_messages": list(self.log_messages[-100:]),
                "pdf_records": list(self.pdf_records[-50:]),
            }


# Global scrape status
scrape_status = ScrapeStatus()


class PDFScraper:
    """
    Web crawler tìm và tải PDF y khoa từ URL bất kỳ.

    Flow:
    1. Nhận URL → phân tích trang
    2. Kiểm tra nội dung có phải y khoa không
    3. Tìm tất cả link PDF
    4. Tải từng PDF với rate limiting
    5. Lưu vào thư mục tổ chức
    6. Track trong MongoDB
    """

    def __init__(self, output_dir: str | None = None):
        self.output_dir = Path(output_dir or settings.SCRAPE_DIR)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._session = self._create_session()
        self._downloaded_hashes: set[str] = set()
        self._stored_pdf_urls: set[str] = set()
        self._robots_cache: dict[str, RobotFileParser] = {}
        self._date_extractor = PublicationDateExtractor()
        self._path_builder = ScrapedPDFPathBuilder(self.output_dir)
        self._pdf_article_urls: dict[str, str] = {}
        self._pdf_publications: dict[str, PublicationDate] = {}
        self._start_year: int | None = None
        self._end_year: int | None = None
        self._manifest_store = None
        self._active_manifest_id = ""
        self._last_download_outcome = "retry"
        self._discovery_complete = True

    def _create_session(self) -> requests.Session:
        """Tạo requests session với retry và headers."""
        session = requests.Session()
        session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        retry = Retry(
            total=3,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET"],
        )
        session.mount("http://", HTTPAdapter(max_retries=retry))
        session.mount("https://", HTTPAdapter(max_retries=retry))
        return session

    def _load_stored_hashes(self) -> set[str]:
        """Build a hash index from PDFs already present in the corpus.

        The database is normally the fast duplicate index, but a stop/restart
        can leave valid files on disk before their database records are saved.
        Indexing the storage folder makes those files duplicate-safe too.
        """
        hashes: set[str] = set()
        try:
            for pdf_file in self.output_dir.rglob("*.pdf"):
                if not pdf_file.is_file():
                    continue
                digest = hashlib.sha256()
                with pdf_file.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(64 * 1024), b""):
                        digest.update(chunk)
                hashes.add(digest.hexdigest())
        except OSError as exc:
            logger.warning("Could not index existing scraped PDFs: %s", exc)
        return hashes

    @staticmethod
    def _load_stored_pdf_urls() -> set[str]:
        """Load saved crawl URLs for zero-download duplicate skips."""
        try:
            from infrastructure.database.repositories.paper_repository import PaperRepository

            repo = PaperRepository()
            records = repo.papers.find(
                {"source": "scrape"},
                {"_id": 0, "source_url": 1, "pdf_url": 1},
            )
            return {
                value
                for record in records
                for value in (record.get("source_url"), record.get("pdf_url"))
                if isinstance(value, str) and value
            }
        except Exception as exc:
            logger.debug("Could not index stored crawl URLs: %s", exc)
            return set()

    def _get_manifest_store(self):
        """Return the optional durable queue store without breaking local use."""
        try:
            from infrastructure.scraper.crawl_manifest import CrawlManifestStore

            return CrawlManifestStore()
        except Exception as exc:
            logger.debug("Crawl manifest persistence is unavailable: %s", exc)
            return None

    def _manifest_candidates(self, pdf_links: list[str]) -> list[dict]:
        """Serialize fully validated PDF candidates for durable resumption."""
        candidates = []
        for pdf_url in pdf_links:
            publication = self._pdf_publications.get(pdf_url)
            candidates.append(
                {
                    "pdf_url": pdf_url,
                    "article_url": self._pdf_article_urls.get(pdf_url, ""),
                    "publication_year": publication.year if publication else None,
                    "publication_date": publication.value if publication else None,
                    "year_detection_status": publication.status if publication else "unknown",
                    "year_detection_source": publication.source if publication else "manifest",
                }
            )
        return candidates

    def _hydrate_manifest_candidates(self, candidates: list[dict]) -> list[str]:
        """Restore candidate URLs and publication metadata from MongoDB."""
        links: list[str] = []
        self._pdf_article_urls = {}
        self._pdf_publications = {}
        for candidate in candidates:
            pdf_url = candidate.get("pdf_url")
            if not isinstance(pdf_url, str) or not pdf_url:
                continue
            year = candidate.get("publication_year")
            if not isinstance(year, int):
                year = None
            self._pdf_article_urls[pdf_url] = str(candidate.get("article_url") or "")
            self._pdf_publications[pdf_url] = PublicationDate(
                year,
                candidate.get("publication_date"),
                str(candidate.get("year_detection_status") or "unknown"),
                str(candidate.get("year_detection_source") or "manifest"),
            )
            links.append(pdf_url)
        return links

    def _set_manifest_catalog(self, manifest: dict, pending_count: int, reused: bool) -> None:
        total = int(manifest.get("candidate_total") or 0)
        scrape_status.set_catalog_progress(
            total=total,
            pending=pending_count,
            batch_total=min(MAX_PDFS, pending_count),
            reused=reused,
        )

    def _mark_manifest_terminal(self, pdf_url: str, state: str) -> None:
        """Persist a terminal queue state when its outcome is durable."""
        if not self._manifest_store or not self._active_manifest_id:
            return
        try:
            if self._manifest_store.mark_terminal(self._active_manifest_id, pdf_url, state):
                scrape_status.mark_catalog_terminal()
        except Exception as exc:
            logger.debug("Could not update crawl manifest candidate: %s", exc)

    def _record_manifest_retry(self, pdf_url: str, error: str = "") -> None:
        """Keep a transient failure pending for a later batch retry."""
        if not self._manifest_store or not self._active_manifest_id:
            return
        try:
            self._manifest_store.record_retry(self._active_manifest_id, pdf_url, error)
        except Exception as exc:
            logger.debug("Could not record manifest retry: %s", exc)

    def _settle_manifest_known_urls(self) -> int:
        """Remove Mongo-persisted URLs from a manifest before downloading."""
        if not self._manifest_store or not self._active_manifest_id:
            return 0
        mark_known_urls = getattr(self._manifest_store, "mark_known_urls", None)
        if not callable(mark_known_urls):
            return 0
        try:
            count = mark_known_urls(self._active_manifest_id, self._stored_pdf_urls)
        except Exception as exc:
            logger.debug("Could not settle known manifest URLs: %s", exc)
            return 0
        if count:
            scrape_status.duplicates += count
            scrape_status.skipped += count
            scrape_status.mark_catalog_terminal(count)
            scrape_status.log(
                f"♻️ Bỏ qua {count} PDF đã có trong kho trước khi lập lô tải mới"
            )
        return count

    def finalize_manifest_records(
        self,
        records: list[dict],
        persisted_urls: set[str],
        duplicate_urls: set[str] | None = None,
    ) -> None:
        """Finalize only records whose outcome is durable in MongoDB.

        Files saved on disk stay pending until the router has either inserted
        their metadata record or proven that their content already exists in
        MongoDB. A transient database error therefore remains retryable.
        """
        duplicate_urls = duplicate_urls or set()
        for record in records:
            pdf_url = record.get("pdf_url")
            if isinstance(pdf_url, str) and pdf_url in persisted_urls:
                self._mark_manifest_terminal(pdf_url, "saved")
            elif isinstance(pdf_url, str) and pdf_url in duplicate_urls:
                self._mark_manifest_terminal(pdf_url, "duplicate")

    # ─────────────────────────────────────────────
    # Main scraping entry point
    # ─────────────────────────────────────────────

    def scrape(
        self,
        url: str,
        max_depth: int = 2,
        start_year: int | None = None,
        end_year: int | None = None,
        status_started: bool = False,
        complete_status: bool = True,
    ) -> None:
        """
        Bắt đầu scraping từ URL.

        Args:
            url: URL trang web bất kỳ
            max_depth: Độ sâu crawl tối đa
        """
        global scrape_status
        if not status_started and not scrape_status.try_start():
            raise RuntimeError("A scrape job is already running")
        # The storage corpus is authoritative even if an earlier crawl was
        # interrupted before its lightweight MongoDB records were persisted.
        # Seed hash deduplication from disk for every job, including after an
        # application restart.
        self._downloaded_hashes = self._load_stored_hashes()
        self._stored_pdf_urls = self._load_stored_pdf_urls()
        self._start_year = start_year
        self._end_year = end_year
        self._pdf_article_urls = {}
        self._pdf_publications = {}
        self._manifest_store = None
        self._active_manifest_id = ""
        self._last_download_outcome = "retry"
        self._discovery_complete = True
        scrape_status.log(f"🚀 Bắt đầu quét: {url}")

        try:
            # Step 1: Fetch trang chính
            scrape_status.current_url = url
            html, page_url = self._fetch_page(url)
            if html is None:
                scrape_status.log("❌ Không thể truy cập URL", "error")
                return

            soup = BeautifulSoup(html, "lxml")

            # Step 2: Kiểm tra nội dung y khoa
            if not self._is_medical_content(soup, url):
                scrape_status.log(
                    "⚠️ Trang này không chứa đủ nội dung y khoa. "
                    "Vẫn tiếp tục tìm PDF nhưng sẽ filter từng file.",
                    "warning"
                )

            # Step 3: Phát hiện loại trang
            adapter = SiteDetector.detect(url, soup)
            site_type = adapter.name.lower()
            manifest_depth = 0 if site_type == "ojs" else max_depth
            scrape_status.log(f"📋 Loại trang: {site_type}")

            # Step 4: Use an existing OJS catalog when it matches exactly the
            # same source and year range.  This makes every later 500-file
            # batch resume immediately instead of rediscovering thousands of
            # article URLs.
            pdf_links: list[str] = []
            manifest: dict | None = None
            if site_type == "ojs":
                self._manifest_store = self._get_manifest_store()
                if self._manifest_store is not None:
                    try:
                        manifest = self._manifest_store.find_ready(
                            url, start_year, end_year, adapter.name, manifest_depth
                        )
                    except Exception as exc:
                        logger.debug("Could not load crawl manifest: %s", exc)

            if manifest:
                self._active_manifest_id = str(manifest.get("manifest_id") or "")
                self._settle_manifest_known_urls()
                pending_candidates = self._manifest_store.pending_candidates(
                    self._active_manifest_id
                )
                pdf_links = self._hydrate_manifest_candidates(pending_candidates)
                self._set_manifest_catalog(manifest, len(pdf_links), reused=True)
                scrape_status.total_found = int(manifest.get("candidate_total") or len(pdf_links))
                scrape_status.log(
                    f"♻️ Dùng danh mục đã lập chỉ mục: {scrape_status.total_found} PDF, "
                    f"còn {len(pdf_links)} mục chưa xử lý"
                )
            else:
                pdf_links = self._discover_with_adapter(adapter, url, soup, max_depth)
                if scrape_status.should_stop:
                    scrape_status.log(
                        "🛑 Đã dừng khi lập chỉ mục; danh mục chưa hoàn tất nên không được lưu.",
                        "warning",
                    )
                    return
                if site_type == "ojs" and not self._discovery_complete:
                    scrape_status.log(
                        "⚠️ Chưa thể xác minh đầy đủ danh mục nguồn; không tải hoặc lưu danh mục thiếu. Vui lòng chạy lại khi website phản hồi ổn định.",
                        "warning",
                    )
                    return

                # Deduplicate links while preserving the order published by
                # the journal.
                pdf_links = list(dict.fromkeys(pdf_links))
                if site_type == "ojs" and self._manifest_store is not None:
                    try:
                        manifest = self._manifest_store.replace_ready(
                            url,
                            start_year,
                            end_year,
                            adapter.name,
                            manifest_depth,
                            self._manifest_candidates(pdf_links),
                        )
                        self._active_manifest_id = str(manifest.get("manifest_id") or "")
                        self._settle_manifest_known_urls()
                        pending_candidates = self._manifest_store.pending_candidates(
                            self._active_manifest_id
                        )
                        pdf_links = self._hydrate_manifest_candidates(pending_candidates)
                        self._set_manifest_catalog(manifest, len(pdf_links), reused=False)
                        scrape_status.log(
                            f"💾 Đã lập chỉ mục bền vững {len(pdf_links)} PDF; "
                            "các lượt sau sẽ tiếp tục mà không quét lại archive."
                        )
                    except Exception as exc:
                        logger.warning("Could not persist crawl manifest: %s", exc)
                        self._manifest_store = None
                        self._active_manifest_id = ""

                scrape_status.total_found = int(
                    manifest.get("candidate_total") if manifest else len(pdf_links)
                )
                scrape_status.log(
                    f"🔍 Đã xác định đầy đủ {scrape_status.total_found} link PDF trong phạm vi năm"
                )

            if not pdf_links:
                if manifest:
                    scrape_status.log("✅ Danh mục này không còn PDF nào cần tải.")
                else:
                    scrape_status.log("ℹ️ Không tìm thấy PDF nào trên trang này.")
                return

            # Step 5: Tải từng PDF
            scrape_status.set_job_phase("downloading")
            for i, pdf_url in enumerate(pdf_links, 1):
                if scrape_status.should_stop:
                    scrape_status.log("🛑 Đã dừng theo yêu cầu.")
                    break

                # The quota applies to new files saved in this run, not to
                # discovery. Keep walking the complete list so known URLs are
                # skipped and a later unseen PDF can fill a slot.
                if scrape_status.downloaded >= MAX_PDFS:
                    scrape_status.set_job_phase("quota_reached")
                    scrape_status.log(
                        f"⚠️ Đã lưu {MAX_PDFS} PDF mới; dừng lượt tải, "
                        "danh sách còn lại sẽ được tiếp tục ở lượt quét sau.",
                        "warning",
                    )
                    break

                if pdf_url in self._stored_pdf_urls:
                    scrape_status.duplicates += 1
                    scrape_status.skipped += 1
                    scrape_status.log(f"🔄 Trùng lặp (URL đã lưu): {pdf_url[:80]}")
                    self._mark_manifest_terminal(pdf_url, "duplicate")
                    scrape_status.mark_batch_processed()
                    continue

                # Robots.txt check
                if not self._check_robots_txt(pdf_url):
                    scrape_status.skipped += 1
                    scrape_status.log(f"🤖 Bỏ qua (robots.txt): {pdf_url[:80]}")
                    self._mark_manifest_terminal(pdf_url, "blocked")
                    scrape_status.mark_batch_processed()
                    continue

                scrape_status.current_url = pdf_url
                scrape_status.log(f"📥 [{i}/{len(pdf_links)}] Đang tải: {pdf_url[:100]}")

                try:
                    result = self._download_and_save_pdf(
                        pdf_url,
                        self._pdf_article_urls.get(pdf_url, url),
                        self._pdf_publications.get(pdf_url),
                    )
                    if result:
                        scrape_status.downloaded += 1
                        self._stored_pdf_urls.add(pdf_url)
                        scrape_status.add_pdf_record(result)
                        year = str(result.get("publication_year") or "unknown")
                        stats = scrape_status.years.setdefault(year, {"articles": 0, "pdfs": 0})
                        stats["articles"] += 1
                        stats["pdfs"] += 1
                        scrape_status.log(
                            f"✅ Đã lưu: {result['filename']}",
                        )
                    else:
                        scrape_status.skipped += 1
                        outcome = self._last_download_outcome
                        if outcome in {"duplicate", "out_of_range", "invalid"}:
                            self._mark_manifest_terminal(pdf_url, outcome)
                        else:
                            self._record_manifest_retry(pdf_url)
                    scrape_status.mark_batch_processed()

                    # Stop immediately after the final successful download.
                    # Waiting for another loop iteration previously added one
                    # unnecessary rate-limit delay and made the UI look as if
                    # the crawler continued past its quota.
                    if scrape_status.downloaded >= MAX_PDFS:
                        scrape_status.set_job_phase("quota_reached")
                        scrape_status.log(
                            f"⚠️ Đã lưu đủ giới hạn {MAX_PDFS} PDF mới; "
                            "chuyển sang hoàn tất bản ghi và dừng lượt tải.",
                            "warning",
                        )
                        break
                except Exception as e:
                    scrape_status.errors += 1
                    scrape_status.log(f"❌ Lỗi tải {pdf_url}: {e}", "error")
                    self._record_manifest_retry(pdf_url, str(e))
                    scrape_status.mark_batch_processed()

                # Rate limiting
                time.sleep(random.uniform(DEFAULT_RATE_LIMIT_MIN, DEFAULT_RATE_LIMIT_MAX))

        except Exception as e:
            scrape_status.error_message = str(e)
            scrape_status.log(f"❌ Lỗi nghiêm trọng: {e}", "error")
        finally:
            summary = (
                f"Tải: {scrape_status.downloaded}, "
                f"Bỏ qua: {scrape_status.skipped}, "
                f"Trùng: {scrape_status.duplicates}, "
                f"Lỗi: {scrape_status.errors}"
            )
            if complete_status:
                scrape_status.complete()
                scrape_status.log(f"🏁 Hoàn tất! {summary}")
            else:
                scrape_status.log(f"💾 Đã tải xong, đang đồng bộ database. {summary}")

    # ─────────────────────────────────────────────
    # Medical content detection
    # ─────────────────────────────────────────────

    def _is_medical_content(self, soup: BeautifulSoup, url: str) -> bool:
        """
        Kiểm tra trang có nội dung y khoa không.
        Dựa trên: URL, meta tags, page text.
        """
        text_to_check = []

        # URL
        text_to_check.append(url.lower())

        # Meta tags
        for meta in soup.find_all("meta", attrs={"name": True}):
            name = meta.get("name", "").lower()
            content = meta.get("content", "")
            if name in ("description", "keywords", "citation_journal_title",
                        "DC.Title", "DC.Subject"):
                text_to_check.append(content.lower())

        # Title
        title_tag = soup.find("title")
        if title_tag:
            text_to_check.append(title_tag.get_text().lower())

        # Page text (first 5000 chars)
        body = soup.find("body")
        if body:
            page_text = body.get_text(separator=" ", strip=True)[:5000].lower()
            text_to_check.append(page_text)

        combined = " ".join(text_to_check)

        # Count medical keyword matches
        match_count = sum(
            1 for kw in MEDICAL_KEYWORDS_ALL
            if kw in combined
        )

        is_medical = match_count >= MEDICAL_KEYWORD_THRESHOLD
        scrape_status.log(
            f"🏥 Medical check: {match_count} keywords matched "
            f"(threshold={MEDICAL_KEYWORD_THRESHOLD}) → "
            f"{'Y khoa ✓' if is_medical else 'Không phải y khoa ✗'}"
        )
        return is_medical

    def _is_medical_pdf_context(self, link_tag, soup: BeautifulSoup) -> bool:
        """
        Kiểm tra context xung quanh link PDF có liên quan y khoa không.
        Dùng cho trường hợp trang chung (không hoàn toàn y khoa).
        """
        # Lấy text xung quanh link
        context_parts = []

        # Link text
        if link_tag.string:
            context_parts.append(link_tag.get_text().lower())

        # Parent element text
        parent = link_tag.parent
        if parent:
            context_parts.append(parent.get_text(separator=" ", strip=True)[:500].lower())

        # Sibling elements
        for sibling in link_tag.find_previous_siblings(limit=2):
            context_parts.append(sibling.get_text(separator=" ", strip=True)[:200].lower())

        combined = " ".join(context_parts)
        match_count = sum(1 for kw in MEDICAL_KEYWORDS_ALL if kw in combined)
        return match_count >= 1

    # ─────────────────────────────────────────────
    # Site type detection
    # ─────────────────────────────────────────────

    def _detect_site_type(self, url: str, soup: BeautifulSoup) -> str:
        """Phát hiện loại trang: 'ojs' hoặc 'generic'."""
        # Check OJS markers
        ojs_markers = [
            soup.find("meta", attrs={"name": "generator", "content": re.compile(r"OJS", re.I)}),
            "/issue/view/" in url,
            "/article/view/" in url,
            "/issue/archive" in url,
            soup.find("a", href=re.compile(r"/issue/view/")),
            soup.find("a", href=re.compile(r"/issue/archive")),
        ]
        if any(ojs_markers):
            return "ojs"
        return "generic"

    # ─────────────────────────────────────────────
    # PDF Discovery — OJS
    # ─────────────────────────────────────────────

    def _discover_with_adapter(self, adapter, url: str, soup: BeautifulSoup, max_depth: int) -> list[str]:
        """Use the selected CMS adapter for all article/PDF discovery."""
        if adapter.name == "Generic":
            return adapter.find_pdf_urls(
                url, soup, fetch_page=self._fetch_page, max_depth=max_depth
            )

        links: list[str] = []
        # A requests.Session is not shared across discovery worker threads.
        # Each metadata request gets a short-lived session while PDF downloads
        # remain sequential and use the main session/rate limiter.
        discovery_fetch_page = (
            self._fetch_page_isolated
            if adapter.name == "OJS" and settings.CRAWL_DISCOVERY_WORKERS > 1
            else self._fetch_page
        )
        article_urls = adapter.discover_articles(
            url,
            soup,
            discovery_fetch_page,
            scrape_status.log,
            start_year=self._start_year,
            end_year=self._end_year,
            progress_callback=scrape_status.set_discovery_progress,
            issue_workers=settings.CRAWL_DISCOVERY_WORKERS,
        )
        self._discovery_complete = bool(
            getattr(adapter, "discovery_complete", True)
        )
        scrape_status.log(f"Discovered {len(article_urls)} articles after year filtering")
        direct_pdf_by_article = getattr(adapter, "article_pdf_urls", {})
        for index, article_url in enumerate(article_urls, 1):
            if scrape_status.should_stop:
                break
            scrape_status.current_url = article_url
            scrape_status.set_discovery_progress(
                "articles", index, len(article_urls), article_url
            )
            if index == 1 or index % 10 == 0:
                scrape_status.log(f"Inspecting article {index}/{len(article_urls)}")
            inherited_year = getattr(adapter, "article_years", {}).get(article_url)
            direct_pdf_urls = direct_pdf_by_article.get(article_url, [])
            if direct_pdf_urls and inherited_year is not None:
                # The issue page supplied both a direct galley URL and its
                # structured publication date.  Opening every article page
                # again would only repeat the same work.
                publication = PublicationDate(
                    inherited_year,
                    str(inherited_year),
                    "detected",
                    "issue-metadata",
                )
                article_pdf_urls = direct_pdf_urls
            else:
                article_html, _ = self._fetch_page(article_url)
                if not article_html:
                    self._discovery_complete = False
                    scrape_status.log(
                        f"Không thể đọc metadata bài báo: {article_url}; danh mục sẽ không được lưu.",
                        "warning",
                    )
                    continue
                article_soup = BeautifulSoup(article_html, "lxml")
                publication = self._date_extractor.extract(
                    article_soup, article_url, inherited_year=inherited_year
                )
                article_pdf_urls = adapter.find_pdf_urls(article_url, article_soup)
            if not self._should_store_year(publication):
                continue
            for pdf_url in article_pdf_urls:
                self._pdf_article_urls[pdf_url] = article_url
                self._pdf_publications[pdf_url] = publication
            links.extend(article_pdf_urls)
        return links

    def _discover_pdfs_ojs(self, url: str, soup: BeautifulSoup) -> list[str]:
        """
        Tìm PDF trên trang OJS.
        Flow: Archive → Issues → Articles → PDF galley links
        """
        pdf_links = []
        issue_links = set()
        article_links = set()

        # Nhận diện chế độ quét dựa vào URL đầu vào
        if "/article/view/" in url:
            article_links.add(url)
            scrape_status.log("📄 Chế độ quét nhanh: 1 bài báo cụ thể")
        elif "/issue/view/" in url:
            issue_links.add(url)
            scrape_status.log("📖 Chế độ quét nhanh: 1 số báo cụ thể")
        else:
            base_url = re.sub(r"/(article|issue)/.*", "", url).rstrip("/")

            # Tìm archive URL
            archive_url = f"{base_url}/issue/archive"
            for a in soup.find_all("a", href=True):
                href = a["href"]
                text = a.get_text(strip=True).lower()
                if any(w in text for w in ("lưu trữ", "archives", "archive")):
                    archive_url = urljoin(url, href)
                    break
                if "/issue/archive" in href:
                    archive_url = urljoin(url, href)
                    break

            scrape_status.log(f"📚 OJS Archive: {archive_url}")

            # Crawl archive pages → thu thập issue links
            for page_num in range(1, 20):
                if scrape_status.should_stop:
                    break

                page_url = f"{archive_url}/{page_num}" if page_num > 1 else archive_url
                html, _ = self._fetch_page(page_url)
                if html is None:
                    break

                page_soup = BeautifulSoup(html, "lxml")
                found_any = False

                for a in page_soup.find_all("a", href=True):
                    href = a["href"]
                    if "/issue/view/" in href:
                        full_url = urljoin(page_url, href)
                        if full_url not in issue_links:
                            issue_links.add(full_url)
                            found_any = True

                if not found_any:
                    break

                time.sleep(random.uniform(1, 2))

            scrape_status.log(f"📖 Tìm thấy {len(issue_links)} số/tập")

        # Crawl mỗi issue → tìm article links (nếu chưa có)
        if not article_links and issue_links:
            for issue_url in issue_links:
                if scrape_status.should_stop:
                    break

                html, _ = self._fetch_page(issue_url)
                if html is None:
                    continue

                issue_soup = BeautifulSoup(html, "lxml")
                for a in issue_soup.find_all("a", href=True):
                    href = a["href"]
                    if "/article/view/" in href and re.search(r"/article/view/\d+$", href):
                        article_links.add(urljoin(issue_url, href))

                if len(issue_links) > 1:
                    time.sleep(random.uniform(0.5, 1.5))

            if len(issue_links) == 1:
                scrape_status.log(f"📄 Tìm thấy {len(article_links)} bài báo trong số này")
            else:
                scrape_status.log(f"📄 Tìm thấy {len(article_links)} bài báo tổng cộng")

        # Từ mỗi article → tìm PDF galley link
        for article_url in article_links:
            if scrape_status.should_stop:
                break

            html, _ = self._fetch_page(article_url)
            if html is None:
                continue

            art_soup = BeautifulSoup(html, "lxml")

            # OJS PDF galley links
            for a in art_soup.find_all("a", href=True):
                href = a["href"]
                text = a.get_text(strip=True).lower()

                # Galley link pattern: /article/view/ID/ID
                if re.search(r"/article/view/\d+/\d+", href):
                    # Convert HTML viewer link to raw PDF download link
                    download_href = href.replace("/article/view/", "/article/download/")
                    pdf_links.append(urljoin(article_url, download_href))
                # Direct PDF link
                elif href.lower().endswith(".pdf"):
                    pdf_links.append(urljoin(article_url, href))
                # Link text chứa "PDF"
                elif "pdf" in text:
                    pdf_links.append(urljoin(article_url, href))

            # Meta tag citation_pdf_url
            pdf_meta = art_soup.find("meta", attrs={"name": "citation_pdf_url"})
            if pdf_meta and pdf_meta.get("content"):
                pdf_links.append(pdf_meta["content"])

            time.sleep(random.uniform(0.5, 1.0))

        return pdf_links

    # ─────────────────────────────────────────────
    # PDF Discovery — Generic
    # ─────────────────────────────────────────────

    def _discover_pdfs_generic(
        self, url: str, soup: BeautifulSoup, max_depth: int = 2
    ) -> list[str]:
        """
        Tìm PDF trên trang web bất kỳ.
        Crawl theo BFS, tìm tất cả link .pdf và citation_pdf_url.
        """
        pdf_links = []
        visited = {url}
        to_visit = [(url, soup, 0)]  # (url, soup, depth)
        base_domain = urlparse(url).netloc

        while to_visit and len(visited) < MAX_PAGES_TO_CRAWL:
            if scrape_status.should_stop:
                break

            current_url, current_soup, depth = to_visit.pop(0)

            # Thu thập PDF links từ trang hiện tại
            for a in current_soup.find_all("a", href=True):
                href = a["href"]
                full_url = urljoin(current_url, href)

                # Direct PDF link
                if self._is_pdf_url(full_url):
                    pdf_links.append(full_url)
                # Link trong cùng domain → có thể crawl tiếp
                elif depth < max_depth:
                    parsed = urlparse(full_url)
                    if parsed.netloc == base_domain and full_url not in visited:
                        visited.add(full_url)
                        # Fetch and add to queue
                        html, _ = self._fetch_page(full_url)
                        if html:
                            child_soup = BeautifulSoup(html, "lxml")
                            to_visit.append((full_url, child_soup, depth + 1))
                            # Tìm PDF trong child page
                            for child_a in child_soup.find_all("a", href=True):
                                child_href = child_a["href"]
                                child_full = urljoin(full_url, child_href)
                                if self._is_pdf_url(child_full):
                                    pdf_links.append(child_full)
                        time.sleep(random.uniform(0.5, 1.5))

            # Meta tag citation_pdf_url
            pdf_meta = current_soup.find("meta", attrs={"name": "citation_pdf_url"})
            if pdf_meta and pdf_meta.get("content"):
                pdf_links.append(pdf_meta["content"])

        return pdf_links

    # ─────────────────────────────────────────────
    # Download & Save PDF
    # ─────────────────────────────────────────────

    def _publication_date_for(self, source_url: str) -> PublicationDate:
        """Fetch article metadata before download so out-of-range PDFs are skipped."""
        html, _ = self._fetch_page(source_url)
        if not html:
            return PublicationDate(None, None, "unknown", "unavailable")
        return self._date_extractor.extract(BeautifulSoup(html, "lxml"), source_url)

    def _should_store_year(self, publication: PublicationDate) -> bool:
        if publication.year is None:
            return settings.UNKNOWN_YEAR_POLICY == "store"
        if self._start_year is not None and publication.year < self._start_year:
            return False
        if self._end_year is not None and publication.year > self._end_year:
            return False
        return True

    def _download_and_save_pdf(
        self,
        pdf_url: str,
        source_url: str,
        known_publication: PublicationDate | None = None,
    ) -> dict | None:
        """
        Tải PDF và lưu vào thư mục tổ chức.

        Returns:
            dict với thông tin file đã lưu, hoặc None nếu skip.
        """
        self._last_download_outcome = "retry"
        try:
            publication = known_publication or self._publication_date_for(source_url)
            scrape_status.current_year = publication.year
            if not self._should_store_year(publication):
                self._last_download_outcome = "out_of_range"
                scrape_status.log(
                    f"Skipping PDF outside year policy: {publication.year or 'unknown'}",
                )
                return None

            # Stream download
            response = self._safe_get(
                pdf_url,
                stream=True,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            content = self._read_limited_response(response)

            # Check content type
            content_type = response.headers.get("Content-Type", "").lower()
            if "pdf" not in content_type and not pdf_url.lower().endswith(".pdf"):
                # Thử kiểm tra content bằng magic bytes
                first_chunk = content[:1024]
                if not first_chunk.startswith(PDF_MAGIC_BYTES):
                    self._last_download_outcome = "invalid"
                    scrape_status.log(f"⏭️ Bỏ qua (không phải PDF): {pdf_url[:80]}")
                    return None
                # Là PDF, đọc tiếp
                content = content
            else:
                content = content

            # Check file size
            if len(content) > MAX_FILE_SIZE_BYTES:
                self._last_download_outcome = "invalid"
                scrape_status.log(f"⏭️ Bỏ qua (quá lớn: {len(content)/(1024*1024):.1f}MB): {pdf_url[:80]}")
                return None

            # Check magic bytes
            if not content[:4].startswith(PDF_MAGIC_BYTES):
                self._last_download_outcome = "invalid"
                scrape_status.log(f"⏭️ Bỏ qua (không phải PDF): {pdf_url[:80]}")
                return None

            # Check minimum size (likely empty/corrupt if < 1KB)
            if len(content) < 1024:
                self._last_download_outcome = "invalid"
                scrape_status.log(f"⏭️ Bỏ qua (file quá nhỏ): {pdf_url[:80]}")
                return None

            # SHA-256 hash
            sha256 = hashlib.sha256(content).hexdigest()

            # Duplicate check (in-memory)
            if sha256 in self._downloaded_hashes:
                self._last_download_outcome = "duplicate"
                scrape_status.duplicates += 1
                scrape_status.log(f"🔄 Trùng lặp (cache): {pdf_url[:80]}")
                return None

            # Duplicate check (MongoDB - Database)
            try:
                from infrastructure.database.repositories.paper_repository import PaperRepository
                repo = PaperRepository()
                if repo.get_by_hash(sha256):
                    self._downloaded_hashes.add(sha256) # Lưu vào bộ nhớ tạm
                    self._last_download_outcome = "duplicate"
                    scrape_status.duplicates += 1
                    scrape_status.log(f"🔄 Trùng lặp (database): {pdf_url[:80]}")
                    return None
            except Exception:
                pass  # Bỏ qua nếu MongoDB chưa bật

            # Keep the crawl stage deliberately lightweight.  Reading an article
            # page here to collect citation tags adds one HTTP request per PDF and
            # produces source metadata that can disagree with the PDF itself.
            # The full PDF pipeline is the single source of truth for title,
            # authors and abstract, and is run later through /scrape/extract.
            #
            # A stable internal id, hash and location are still persisted now so
            # duplicate detection and resumable crawl manifests remain reliable.
            paper_id = str(uuid.uuid4())[:8]
            filename = f"pdf_{paper_id}.pdf"

            # Organize through the single path builder: domain/year/filename.
            domain = urlparse(source_url).netloc.replace("www.", "")
            file_path = self._path_builder.build_path(
                source_url, publication.year, filename
            )

            # Save file
            file_path.write_bytes(content)
            self._downloaded_hashes.add(sha256)
            self._last_download_outcome = "saved"

            record = {
                "paper_id": paper_id,
                "source": "scrape",
                "source_url": pdf_url,
                "source_journal_url": source_url,
                "source_journal_domain": domain,
                "article_url": source_url,
                "pdf_url": pdf_url,
                "publication_year": publication.year,
                "publication_date": publication.value,
                "year_detection_status": publication.status,
                "year_detection_source": publication.source,
                "pdf_path": str(file_path.resolve()),
                "file_path": str(file_path.resolve()),
                "file_hash_sha256": sha256,
                "filename": filename,
                "file_size_bytes": len(content),
                "extracted": {
                    "title": "",
                    "authors": [],
                    "abstract": "",
                },
                "confidence": {"overall": 0.0},
                "processing": {
                    "steps_completed": ["scrape"],
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                "review": {
                    "is_reviewed": False,
                    "reviewer_notes": "",
                },
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            }

            return record

        except requests.exceptions.RequestException as e:
            scrape_status.log(f"⚠️ Network error: {e}", "warning")
            return None

    def extract_source_metadata(self, article_url: str) -> dict:
        """Read structured citation metadata when the user requests extraction.

        This is intentionally not used by the crawl/download path.  Citation
        tags from an article landing page are valuable evidence, but fetching
        them for every candidate makes collection unnecessarily slow.  During
        explicit metadata extraction they provide a reliable second candidate
        to compare with the PDF layout pipeline.
        """
        if not article_url:
            return {}

        html, resolved_url = self._fetch_page(article_url)
        if not html:
            return {}

        soup = BeautifulSoup(html, "lxml")

        def _meta_values(*names: str) -> list[str]:
            expected = {name.casefold() for name in names}
            values: list[str] = []
            for tag in soup.find_all("meta"):
                key = str(tag.get("name") or tag.get("property") or "").casefold()
                value = TextCleaner.decode_html_entities(
                    str(tag.get("content") or "").strip()
                )
                if key in expected and value and value not in values:
                    values.append(value)
            return values

        title_values = _meta_values("citation_title", "dc.title")
        author_values = _meta_values("citation_author", "dc.creator")
        abstract_values = _meta_values(
            "citation_abstract", "dc.description", "description"
        )

        title = title_values[0] if title_values else ""
        abstract_nodes = soup.select(
                ".item.abstract, section.abstract, .article-abstract, "
                ".abstract, .article-details-abstract"
        )
        for abstract_node in abstract_nodes:
            node_text = abstract_node.get_text(" ", strip=True)
            if node_text:
                abstract_values.append(node_text)

        abstract = select_preferred_abstract(abstract_values)

        def _normalize(value: str) -> str:
            cleaned, _ = TextCleaner.full_clean(value, preserve_paragraphs=False)
            return cleaned

        metadata = {
            "title": _normalize(title),
            "authors": [_normalize(author) for author in author_values if _normalize(author)],
            "abstract": _normalize(abstract),
            "source_url": resolved_url,
        }
        if not any((metadata["title"], metadata["authors"], metadata["abstract"])):
            return {}
        return metadata

    # ─────────────────────────────────────────────
    # Robots.txt compliance
    # ─────────────────────────────────────────────

    def _check_robots_txt(self, url: str) -> bool:
        """
        Check if URL is allowed by robots.txt.
        Caches parser per domain. Returns True if allowed or if check fails.
        """
        if not ROBOTS_TXT_ENABLED:
            return True

        try:
            parsed = urlparse(url)
            domain = f"{parsed.scheme}://{parsed.netloc}"

            if domain not in self._robots_cache:
                rp = RobotFileParser()
                robots_url = f"{domain}/robots.txt"
                rp.set_url(robots_url)
                try:
                    rp.read()
                except Exception:
                    # If robots.txt can't be fetched, allow by default
                    logger.debug(f"Could not fetch robots.txt for {domain}")
                    self._robots_cache[domain] = None
                    return True
                self._robots_cache[domain] = rp

            rp = self._robots_cache[domain]
            if rp is None:
                return True

            return rp.can_fetch(USER_AGENT, url)
        except Exception:
            return True  # Allow on error

    # ─────────────────────────────────────────────
    # Utility methods
    # ─────────────────────────────────────────────

    def _fetch_page(self, url: str) -> tuple[str | None, str]:
        """Fetch HTML từ URL. Trả về (html, final_url) hoặc (None, url)."""
        return self._fetch_page_with_session(url, self._session)

    def _fetch_page_isolated(self, url: str) -> tuple[str | None, str]:
        """Fetch one discovery page with a session owned by its worker."""
        session = self._create_session()
        try:
            return self._fetch_page_with_session(url, session)
        finally:
            session.close()

    def _fetch_page_with_session(
        self, url: str, session: requests.Session
    ) -> tuple[str | None, str]:
        response: requests.Response | None = None
        try:
            response = self._safe_get(url, session=session, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or "utf-8"
            return response.text, response.url
        except Exception as e:
            logger.debug(f"Failed to fetch {url}: {e}")
            return None, url
        finally:
            if response is not None:
                response.close()

    def _safe_get(
        self, url: str, *, session: requests.Session | None = None, **kwargs
    ) -> requests.Response:
        """Request only public HTTP(S) endpoints and validated redirects."""
        target = validate_public_http_url(url)
        active_session = session or self._session
        for _ in range(5):
            response = active_session.get(target, allow_redirects=False, **kwargs)
            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("Location")
                if not location:
                    raise requests.RequestException("Redirect response has no Location header")
                target = validate_public_http_url(urljoin(target, location))
                response.close()
                continue
            return response
        raise requests.TooManyRedirects("Too many redirects while scraping")

    @staticmethod
    def _read_limited_response(response: requests.Response) -> bytes:
        """Read a response incrementally instead of buffering an unbounded body."""
        declared_size = int(response.headers.get("Content-Length", "0") or 0)
        if declared_size > MAX_FILE_SIZE_BYTES:
            response.close()
            raise requests.RequestException("Response exceeds configured PDF size limit")

        content = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            content.extend(chunk)
            if len(content) > MAX_FILE_SIZE_BYTES:
                response.close()
                raise requests.RequestException("Response exceeds configured PDF size limit")
        return bytes(content)

    @staticmethod
    def _is_pdf_url(url: str) -> bool:
        """Kiểm tra URL có phải link PDF không."""
        parsed = urlparse(url.lower())
        path = unquote(parsed.path)
        return (
            path.endswith(".pdf")
            or "download/pdf" in path
            or "/pdf/" in path
        )

    @staticmethod
    def _sha256(data: bytes) -> str:
        """Tính SHA-256."""
        return hashlib.sha256(data).hexdigest()
