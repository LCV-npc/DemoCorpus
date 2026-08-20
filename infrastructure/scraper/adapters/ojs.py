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
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config.constants import MAX_ARTICLES
from infrastructure.scraper.adapters.base import BaseSiteAdapter, ArticleInfo

logger = logging.getLogger(__name__)


class OJSSiteAdapter(BaseSiteAdapter):
    """Adapter cho Open Journal Systems (OJS)."""

    @property
    def name(self) -> str:
        return "OJS"

    def discover_articles(
        self,
        url: str,
        soup: BeautifulSoup,
        fetch_page,
        status_callback=None,
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

        issue_links = set()
        article_links = set()

        # Chế độ 1: Single article
        if "/article/view/" in url:
            article_links.add(url)
            log("📄 Chế độ quét nhanh: 1 bài báo cụ thể")

        # Chế độ 2: Single issue
        elif "/issue/view/" in url:
            issue_links.add(url)
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
            for page_num in range(1, 20):
                page_url = f"{archive_url}/{page_num}" if page_num > 1 else archive_url
                html, _ = fetch_page(page_url)
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

            log(f"📖 Tìm thấy {len(issue_links)} số/tập")

        # Crawl issues → article links
        if not article_links and issue_links:
            for issue_url in issue_links:
                html, _ = fetch_page(issue_url)
                if html is None:
                    continue

                issue_soup = BeautifulSoup(html, "lxml")
                for a in issue_soup.find_all("a", href=True):
                    href = a["href"]
                    # Accept both numeric and slug-based article IDs
                    if "/article/view/" in href and re.search(r"/article/view/[\w-]+$", href):
                        article_links.add(urljoin(issue_url, href))

                # Enforce MAX_ARTICLES
                if len(article_links) >= MAX_ARTICLES:
                    log(f"⚠️ Đạt giới hạn {MAX_ARTICLES} bài báo", "warning")
                    break

                if len(issue_links) > 1:
                    time.sleep(random.uniform(0.5, 1.5))

            if len(issue_links) == 1:
                log(f"📄 Tìm thấy {len(article_links)} bài báo trong số này")
            else:
                log(f"📄 Tìm thấy {len(article_links)} bài báo tổng cộng")

        return list(article_links)

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
