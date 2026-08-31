"""
infrastructure/scraper/adapters/ojs.py
Site adapter for Open Journal Systems (OJS) — the most common CMS
used by Vietnamese medical journals.

Handles:
- Archive page → Issue pages → Article pages → PDF galley links
- citation_title, citation_author, DC.Description meta tags
- OJS-specific URL patterns: /article/view/, /issue/view/, /issue/archive
"""

from __future__ import annotations

import logging
import random
import re
import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config.constants import MAX_PAGES_TO_CRAWL
from infrastructure.scraper.adapters.base import BaseSiteAdapter, ArticleInfo

logger = logging.getLogger(__name__)

class OJSSiteAdapter(BaseSiteAdapter):
    """Adapter cho Open Journal Systems (OJS)."""

    def __init__(self):
        self.article_years: dict[str, int | None] = {}
        # OJS issue pages normally already expose each galley's direct PDF
        # link. Keeping that relation avoids a second request to every article
        # page merely to rediscover the exact same download URL.
        self.article_pdf_urls: dict[str, list[str]] = {}
        self.issues_discovered = 0
        # A manifest is only safe to publish after the requested discovery
        # completed. This flag distinguishes a real empty range from an
        # archive/issue request that failed midway.
        self.discovery_complete = True

    @property
    def name(self) -> str:
        return "OJS"

    def discover_articles(
        self,
        url: str,
        soup: BeautifulSoup,
        fetch_page,
        status_callback=None,
        start_year: int | None = None,
        end_year: int | None = None,
        progress_callback=None,
        issue_workers: int = 1,
    ) -> list[str]:
        """
        OJS discovery flow:
        1. Nếu URL là /article/view/ID → trả về 1 article.
        2. Nếu URL là /issue/view/ID → crawl issue → articles.
        3. Nếu URL khác → tìm archive → issues → articles.
        """
        def log(msg, level="info"):
            if status_callback:
                status_callback(msg, level)

        def update_progress(
            phase: str, current: int = 0, total: int = 0, current_url: str = ""
        ) -> None:
            if progress_callback:
                progress_callback(phase, current, total, current_url)

        # Preserve the order published by the journal. The scraper must fully
        # discover the requested range before applying its save quota.
        issue_links: list[str] = []
        seen_issue_links: set[str] = set()
        article_links: list[str] = []
        seen_article_links: set[str] = set()
        self.article_years = {}
        self.article_pdf_urls = {}
        self.issues_discovered = 0
        self.discovery_complete = True

        # Chế độ 1: Single article
        if "/article/view/" in url:
            article_links.append(url)
            seen_article_links.add(url)
            log("📄 Chế độ quét nhanh: 1 bài báo cụ thể")

        # Chế độ 2: Single issue
        elif "/issue/view/" in url:
            issue_links.append(url)
            seen_issue_links.add(url)
            log("📖 Chế độ quét nhanh: 1 số báo cụ thể")

        # Chế độ 3: Full archive crawl
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

            log(f"📚 OJS Archive: {archive_url}")

            # Crawl archive pages → issue links
            # Do not assume a fixed number of archive pages. The Vietnam
            # Medical Journal currently exposes only 15 issues per page, so a
            # 19-page ceiling silently misses older years. Stop naturally as
            # soon as an archive page contributes no new issue URL, while a
            # high safety cap still protects against a broken paginator.
            for page_num in range(1, MAX_PAGES_TO_CRAWL + 1):
                page_url = f"{archive_url}/{page_num}" if page_num > 1 else archive_url
                update_progress("archive", page_num, 0, page_url)
                html, _ = fetch_page(page_url)
                if html is None:
                    # The first archive page must be readable. Later pages
                    # may simply not exist, which is the conventional end of
                    # OJS's /archive/<page> sequence.
                    if page_num == 1:
                        self.discovery_complete = False
                        log("Không thể đọc trang archive; chưa lưu danh mục tạm thời.", "warning")
                    break

                page_soup = BeautifulSoup(html, "lxml")
                new_issue_count = 0

                # Archive titles and headings are presentation data only.
                # A special issue can omit its publication year entirely, so
                # retain every issue URL and apply the year filter only after
                # reading the issue page's publication metadata below.
                for element in page_soup.find_all("a", href=True):
                    href = element.get("href", "")
                    if "/issue/view/" in href:
                        full_url = urljoin(page_url, href)
                        if full_url not in seen_issue_links:
                            issue_links.append(full_url)
                            seen_issue_links.add(full_url)
                            new_issue_count += 1

                # Some OJS instances return the first archive page for an
                # out-of-range suffix instead of a 404. Looking for new URLs
                # prevents an infinite loop in that case.
                if not new_issue_count:
                    break

                time.sleep(random.uniform(1, 2))
            else:
                self.discovery_complete = False
                log(
                    f"Archive vượt ngưỡng an toàn {MAX_PAGES_TO_CRAWL} trang; chưa lưu danh mục tạm thời.",
                    "warning",
                )

            log(f"📖 Tìm thấy {len(issue_links)} số/tập")
            update_progress("issues", 0, len(issue_links), archive_url)

        # Crawl issues → article links
        if not article_links and issue_links:
            def inspect_issue(issue_index: int, issue_url: str):
                html, _ = fetch_page(issue_url)
                if html is None:
                    return issue_index, issue_url, None, None

                issue_soup = BeautifulSoup(html, "lxml")
                return issue_index, issue_url, issue_soup, self._issue_year(issue_soup, issue_url)

            inspected_issues: list[tuple[int, str, BeautifulSoup | None, int | None]] = []
            worker_count = min(max(1, issue_workers), len(issue_links))
            if worker_count > 1:
                log(f"🔄 Kiểm tra metadata {len(issue_links)} số/tập với {worker_count} kết nối song song")
                with ThreadPoolExecutor(max_workers=worker_count) as executor:
                    futures = {
                        executor.submit(inspect_issue, issue_index, issue_url): (issue_index, issue_url)
                        for issue_index, issue_url in enumerate(issue_links, 1)
                    }
                    completed = 0
                    for future in as_completed(futures):
                        issue_index, issue_url = futures[future]
                        completed += 1
                        update_progress("issues", completed, len(issue_links), issue_url)
                        try:
                            inspected_issues.append(future.result())
                        except Exception as exc:
                            logger.debug("Could not inspect OJS issue %s: %s", issue_url, exc)
                            inspected_issues.append((issue_index, issue_url, None, None))
            else:
                for issue_index, issue_url in enumerate(issue_links, 1):
                    update_progress("issues", issue_index, len(issue_links), issue_url)
                    inspected_issues.append(inspect_issue(issue_index, issue_url))
                    if len(issue_links) > 1:
                        time.sleep(random.uniform(0.5, 1.5))

            # Futures complete out of order, but publication order determines
            # which PDFs are selected first when the save quota is reached.
            for _issue_index, issue_url, issue_soup, issue_year in sorted(inspected_issues):
                if issue_soup is None:
                    self.discovery_complete = False
                    log(
                        f"Không thể đọc metadata số báo: {issue_url}; chưa lưu danh mục tạm thời.",
                        "warning",
                    )
                    continue
                # The issue page metadata is authoritative. Do not infer the
                # publication year from archive headings, issue link text, or
                # the URL because those values may be absent or misleading.
                if issue_year is not None and not self._in_range(
                    issue_year, start_year, end_year
                ):
                    log(f"Bỏ qua số báo năm {issue_year} (ngoài khoảng năm)")
                    continue
                self.issues_discovered += 1
                for a in issue_soup.find_all("a", href=True):
                    href = a["href"]
                    # Accept both numeric and slug-based article IDs
                    if "/article/view/" in href and re.search(r"/article/view/[\w-]+$", href):
                        article_url = urljoin(issue_url, href)
                        if article_url not in seen_article_links:
                            article_links.append(article_url)
                            seen_article_links.add(article_url)
                            self.article_years[article_url] = issue_year

                    direct_pdf = self._direct_pdf_from_issue_link(issue_url, href)
                    if direct_pdf is not None:
                        article_url, pdf_url = direct_pdf
                        if article_url not in seen_article_links:
                            article_links.append(article_url)
                            seen_article_links.add(article_url)
                            self.article_years[article_url] = issue_year
                        self.article_pdf_urls.setdefault(article_url, []).append(pdf_url)

            self.article_pdf_urls = {
                article_url: list(dict.fromkeys(pdf_urls))
                for article_url, pdf_urls in self.article_pdf_urls.items()
            }


            if len(issue_links) == 1:
                log(f"📄 Tìm thấy {len(article_links)} bài báo trong số này")
            else:
                log(f"📄 Tìm thấy {len(article_links)} bài báo tổng cộng")

        return article_links

    @staticmethod
    def _direct_pdf_from_issue_link(
        issue_url: str, href: str
    ) -> tuple[str, str] | None:
        """Turn an OJS galley link on an issue page into an article/PDF pair.

        OJS links a galley as ``/article/view/<article>/<galley>`` or
        ``/article/download/<article>/<galley>``.  It belongs to the article
        named by the first segment and can be downloaded without opening its
        detail page.  A bare ``/article/view/<article>`` is deliberately not
        treated as a PDF.
        """
        match = re.search(
            r"(?P<article_path>.*?/article/(?:view|download)/(?P<article>[\w-]+))/(?P<galley>[\w-]+)(?:[?#].*)?$",
            href,
        )
        if not match:
            return None
        article_href = re.sub(
            r"/article/download/", "/article/view/", match.group("article_path")
        )
        article_url = urljoin(issue_url, article_href)
        pdf_href = re.sub(r"/article/view/", "/article/download/", href)
        return article_url, urljoin(issue_url, pdf_href)

    @staticmethod
    def _issue_year(soup: BeautifulSoup, issue_url: str) -> int | None:
        """Read a publication year only from structured page metadata.

        Issue headings, general visible page text, and URL slugs are not
        reliable publication data for OJS special issues. OJS installations
        can expose the same metadata in a ``.published``/``time`` block
        instead of a meta tag, so those explicit fields are supported too.
        """
        def year_from(value: str | None) -> int | None:
            if not value:
                return None
            match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", value)
            return int(match.group(1)) if match else None

        for tag in soup.find_all("meta"):
            key = (tag.get("name") or tag.get("property") or "").lower()
            if key in {"citation_publication_date", "citation_date", "dc.date", "date"}:
                if year := year_from(tag.get("content")):
                    return year

        for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                payload = json.loads(tag.string or tag.get_text())
            except (json.JSONDecodeError, TypeError):
                continue
            stack = payload if isinstance(payload, list) else [payload]
            while stack:
                item = stack.pop()
                if not isinstance(item, dict):
                    continue
                if year := year_from(item.get("datePublished")):
                    return year
                if isinstance(item.get("@graph"), list):
                    stack.extend(item["@graph"])

        for tag in soup.select("time[datetime], .published, .date-published, [class*='published'], [id*='published']"):
            if year := year_from(tag.get("datetime") or tag.get_text(" ", strip=True)):
                return year

        published_label = re.compile(r"date\s*published|published\s*date|ngày\s*xuất\s*bản", re.IGNORECASE)
        for label in soup.find_all(string=published_label):
            container = label.parent.find_parent(["div", "li", "p", "section", "article"])
            if container and (year := year_from(container.get_text(" ", strip=True))):
                return year
        return None

    @staticmethod
    def _in_range(year: int, start_year: int | None, end_year: int | None) -> bool:
        return (start_year is None or year >= start_year) and (end_year is None or year <= end_year)

    def find_pdf_urls(
        self,
        article_url: str,
        soup: BeautifulSoup,
    ) -> list[str]:
        """Tìm PDF URLs từ OJS article page."""
        pdf_links = []

        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True).lower()

            # OJS galley pattern: /article/view/ID/ID
            if re.search(r"/article/view/[\w-]+/[\w-]+", href):
                download_href = href.replace("/article/view/", "/article/download/")
                pdf_links.append(urljoin(article_url, download_href))
            # Direct .pdf link
            elif href.lower().endswith(".pdf"):
                pdf_links.append(urljoin(article_url, href))
            # Link text contains "PDF"
            elif "pdf" in text:
                pdf_links.append(urljoin(article_url, href))

        # citation_pdf_url meta tag
        pdf_meta = soup.find("meta", attrs={"name": "citation_pdf_url"})
        if pdf_meta and pdf_meta.get("content"):
            pdf_links.append(pdf_meta["content"])

        return list(dict.fromkeys(pdf_links))

    def extract_article_metadata(
        self,
        article_url: str,
        soup: BeautifulSoup,
    ) -> ArticleInfo:
        """Trích xuất metadata từ OJS article page HTML."""
        info = ArticleInfo(url=article_url)

        # Title: citation_title > DC.Title > h1
        info.title = (
            self._extract_meta_content(soup, "citation_title")
            or self._extract_meta_content(soup, "DC.Title")
        )
        if not info.title:
            h1 = soup.find("h1")
            if h1:
                info.title = h1.get_text(strip=True)

        # Authors: citation_author
        info.authors = self._extract_all_meta_content(soup, "citation_author")

        # Abstract: CSS selectors > DC.Description
        abstract_el = soup.select_one(
            ".item.abstract, section.abstract, .article-abstract, "
            ".abstract, .article-details-abstract"
        )
        if abstract_el:
            info.abstract = abstract_el.get_text(strip=True)
            import re as _re
            info.abstract = _re.sub(
                r"^(Tóm tắt|Abstract|ABSTRACT|TÓM TẮT)[\s:.\\-]*",
                "", info.abstract, flags=_re.IGNORECASE
            ).strip()
        else:
            info.abstract = self._extract_meta_content(soup, "DC.Description")

        return info
