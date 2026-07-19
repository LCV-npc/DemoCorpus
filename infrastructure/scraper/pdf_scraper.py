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
    REQUEST_TIMEOUT,
    USER_AGENT,
    MAX_FILE_SIZE_BYTES,
    PDF_MAGIC_BYTES,
)
from config.settings import settings

logger = logging.getLogger(__name__)


class ScrapeStatus:
    """Thread-safe trạng thái scraping."""

    def __init__(self):
        self.reset()
        self._lock = threading.Lock()

    def reset(self):
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
        self.log_messages: list[dict] = []
        self.pdf_records: list[dict] = []

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

    # ─────────────────────────────────────────────
    # Main scraping entry point
    # ─────────────────────────────────────────────

    def scrape(self, url: str, max_depth: int = 2) -> None:
        """
        Bắt đầu scraping từ URL.

        Args:
            url: URL trang web bất kỳ
            max_depth: Độ sâu crawl tối đa
        """
        global scrape_status
        scrape_status.reset()
        scrape_status.running = True
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
            site_type = self._detect_site_type(url, soup)
            scrape_status.log(f"📋 Loại trang: {site_type}")

            # Step 4: Thu thập link PDF
            pdf_links = []
            if site_type == "ojs":
                pdf_links = self._discover_pdfs_ojs(url, soup)
            else:
                pdf_links = self._discover_pdfs_generic(url, soup, max_depth)

            # Deduplicate links
            pdf_links = list(dict.fromkeys(pdf_links))
            scrape_status.total_found = len(pdf_links)
            scrape_status.log(f"🔍 Tìm thấy {len(pdf_links)} link PDF")

            if not pdf_links:
                scrape_status.log("ℹ️ Không tìm thấy PDF nào trên trang này.")
                return

            # Step 5: Tải từng PDF
            for i, pdf_url in enumerate(pdf_links, 1):
                if scrape_status.should_stop:
                    scrape_status.log("🛑 Đã dừng theo yêu cầu.")
                    break

                scrape_status.current_url = pdf_url
                scrape_status.log(f"📥 [{i}/{len(pdf_links)}] Đang tải: {pdf_url[:100]}")

                try:
                    result = self._download_and_save_pdf(pdf_url, url)
                    if result:
                        scrape_status.downloaded += 1
                        scrape_status.pdf_records.append(result)
                        scrape_status.log(
                            f"✅ Đã lưu: {result['filename']}",
                        )
                    else:
                        scrape_status.skipped += 1
                except Exception as e:
                    scrape_status.errors += 1
                    scrape_status.log(f"❌ Lỗi tải {pdf_url}: {e}", "error")

                # Rate limiting
                time.sleep(random.uniform(DEFAULT_RATE_LIMIT_MIN, DEFAULT_RATE_LIMIT_MAX))

        except Exception as e:
            scrape_status.error_message = str(e)
            scrape_status.log(f"❌ Lỗi nghiêm trọng: {e}", "error")
        finally:
            scrape_status.running = False
            scrape_status.done = True
            scrape_status.log(
                f"🏁 Hoàn tất! Tải: {scrape_status.downloaded}, "
                f"Bỏ qua: {scrape_status.skipped}, "
                f"Trùng: {scrape_status.duplicates}, "
                f"Lỗi: {scrape_status.errors}"
            )

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

    def _download_and_save_pdf(self, pdf_url: str, source_url: str) -> dict | None:
        """
        Tải PDF và lưu vào thư mục tổ chức.

        Returns:
            dict với thông tin file đã lưu, hoặc None nếu skip.
        """
        try:
            # Stream download
            response = self._session.get(
                pdf_url,
                stream=True,
                timeout=REQUEST_TIMEOUT,
                verify=False,
            )
            response.raise_for_status()

            # Check content type
            content_type = response.headers.get("Content-Type", "").lower()
            if "pdf" not in content_type and not pdf_url.lower().endswith(".pdf"):
                # Thử kiểm tra content bằng magic bytes
                first_chunk = next(response.iter_content(1024), b"")
                if not first_chunk.startswith(PDF_MAGIC_BYTES):
                    scrape_status.log(f"⏭️ Bỏ qua (không phải PDF): {pdf_url[:80]}")
                    return None
                # Là PDF, đọc tiếp
                content = first_chunk + response.content
            else:
                content = response.content

            # Check file size
            if len(content) > MAX_FILE_SIZE_BYTES:
                scrape_status.log(f"⏭️ Bỏ qua (quá lớn: {len(content)/(1024*1024):.1f}MB): {pdf_url[:80]}")
                return None

            # Check magic bytes
            if not content[:4].startswith(PDF_MAGIC_BYTES):
                scrape_status.log(f"⏭️ Bỏ qua (không phải PDF): {pdf_url[:80]}")
                return None

            # Check minimum size (likely empty/corrupt if < 1KB)
            if len(content) < 1024:
                scrape_status.log(f"⏭️ Bỏ qua (file quá nhỏ): {pdf_url[:80]}")
                return None

            # SHA-256 hash
            sha256 = hashlib.sha256(content).hexdigest()

            # Duplicate check (in-memory)
            if sha256 in self._downloaded_hashes:
                scrape_status.duplicates += 1
                scrape_status.log(f"🔄 Trùng lặp (cache): {pdf_url[:80]}")
                return None

            # Duplicate check (MongoDB - Database)
            try:
                from infrastructure.database.repositories.paper_repository import PaperRepository
                repo = PaperRepository()
                if repo.get_by_hash(sha256):
                    self._downloaded_hashes.add(sha256) # Lưu vào bộ nhớ tạm
                    scrape_status.duplicates += 1
                    scrape_status.log(f"🔄 Trùng lặp (database): {pdf_url[:80]}")
                    return None
            except Exception:
                pass  # Bỏ qua nếu MongoDB chưa bật

            self._downloaded_hashes.add(sha256)

            # Extract metadata from PDF page (if came from article page)
            title, authors, abstract = self._extract_meta_from_source(pdf_url, source_url)

            # Generate filename
            paper_id = str(uuid.uuid4())[:8]
            safe_title = self._clean_filename(title) if title else paper_id
            filename = f"{safe_title}_{paper_id}.pdf"

            # Organize: source_domain/filename
            domain = urlparse(source_url).netloc.replace("www.", "")
            save_dir = self.output_dir / domain
            save_dir.mkdir(parents=True, exist_ok=True)
            file_path = save_dir / filename

            # Save file
            file_path.write_bytes(content)

            record = {
                "paper_id": paper_id,
                "source": "scrape",
                "source_url": pdf_url,
                "source_journal_url": source_url,
                "source_journal_domain": domain,
                "file_path": str(file_path.resolve()),
                "file_hash_sha256": sha256,
                "filename": filename,
                "file_size_bytes": len(content),
                "extracted": {
                    "title": title,
                    "authors": authors if authors else [],
                    "abstract": abstract,
                },
                "confidence": {"overall": 0.0},
                "processing": {
                    "steps_completed": ["scrape", "precheck"],
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

    def _extract_meta_from_source(self, pdf_url: str, source_url: str):
        """
        Thử trích xuất metadata từ article page (nếu là OJS).
        Dùng meta tags: citation_title, citation_author, DC.Description.
        """
        title = None
        authors = []
        abstract = None

        # Tìm article page từ PDF URL
        # OJS pattern: /article/view/ID/ID → article page là /article/view/ID
        article_url = None
        if "/article/view/" in pdf_url:
            match = re.match(r"(.*?/article/view/\d+)", pdf_url)
            if match:
                article_url = match.group(1)

        target_url = article_url or source_url

        try:
            html, _ = self._fetch_page(target_url)
            if html is None:
                return title, authors, abstract

            soup = BeautifulSoup(html, "lxml")

            # Title
            meta_title = (
                soup.find("meta", attrs={"name": "citation_title"})
                or soup.find("meta", attrs={"name": "DC.Title"})
            )
            if meta_title and meta_title.get("content"):
                title = meta_title["content"].strip()
            elif soup.find("h1"):
                title = soup.find("h1").get_text(strip=True)

            # Authors
            meta_authors = soup.find_all("meta", attrs={"name": "citation_author"})
            if meta_authors:
                authors = [a.get("content", "").strip() for a in meta_authors if a.get("content")]

            # Abstract
            abstract_el = soup.select_one(
                ".item.abstract, section.abstract, .article-abstract, "
                ".abstract, .article-details-abstract"
            )
            if abstract_el:
                abstract = abstract_el.get_text(strip=True)
                # Clean prefix
                abstract = re.sub(
                    r"^(Tóm tắt|Abstract|ABSTRACT|TÓM TẮT)[\s:.\-]*",
                    "", abstract, flags=re.IGNORECASE
                ).strip()
            else:
                meta_abstract = soup.find("meta", attrs={"name": "DC.Description"})
                if meta_abstract and meta_abstract.get("content"):
                    abstract = meta_abstract["content"].strip()

        except Exception as e:
            logger.debug(f"Could not extract meta from {target_url}: {e}")

        return title, authors, abstract

    # ─────────────────────────────────────────────
    # Utility methods
    # ─────────────────────────────────────────────

    def _fetch_page(self, url: str) -> tuple[str | None, str]:
        """Fetch HTML từ URL. Trả về (html, final_url) hoặc (None, url)."""
        try:
            response = self._session.get(url, timeout=REQUEST_TIMEOUT, verify=False)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or "utf-8"
            return response.text, response.url
        except Exception as e:
            logger.debug(f"Failed to fetch {url}: {e}")
            return None, url

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
    def _clean_filename(name: str) -> str:
        """Tạo filename an toàn từ title."""
        # Remove special chars
        name = re.sub(r'[\t\n\r\f\v]+', ' ', name)
        name = re.sub(r'[\\/*?:"<>|]', '', name)
        name = re.sub(r'\s+', '_', name)
        return name[:100].strip('_')

    @staticmethod
    def _sha256(data: bytes) -> str:
        """Tính SHA-256."""
        return hashlib.sha256(data).hexdigest()
