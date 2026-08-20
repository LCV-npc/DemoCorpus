"""
infrastructure/scraper/adapters/generic.py
Generic site adapter — fallback for non-OJS websites.

Handles:
- BFS crawl within same domain
- PDF detection via URL patterns, link text, meta tags
- Metadata extraction via citation_* and DC.* meta tags
"""

from __future__ import annotations

import logging
import random
import time
from urllib.parse import urljoin, urlparse, unquote

from bs4 import BeautifulSoup

from config.constants import MAX_PAGES_TO_CRAWL, MAX_ARTICLES
from infrastructure.scraper.adapters.base import BaseSiteAdapter, ArticleInfo

logger = logging.getLogger(__name__)


class GenericSiteAdapter(BaseSiteAdapter):
    """Fallback adapter: BFS crawl + PDF URL detection."""

    @property
    def name(self) -> str:
        return "Generic"

    def discover_articles(
        self,
        url: str,
        soup: BeautifulSoup,
        fetch_page,
        status_callback=None,
    ) -> list[str]:
        """
        Generic discovery: BFS crawl → find pages with PDF links.
        Returns article page URLs (pages containing PDF links).
        """
        def log(msg, level="info"):
            if status_callback:
                status_callback(msg, level)

        # For generic sites, the "articles" are just the pages
        # that contain PDF links. We return the initial URL
        # and let find_pdf_urls handle the BFS.
        log("🔍 Chế độ Generic: BFS crawl tìm PDF")
        return [url]

    def find_pdf_urls(
        self,
        article_url: str,
        soup: BeautifulSoup,
        fetch_page=None,
        max_depth: int = 2,
    ) -> list[str]:
        """
        BFS crawl from article_url to find all PDF links.

        Args:
            article_url: Starting URL.
            soup: Parsed HTML of starting page.
            fetch_page: Callable to fetch additional pages.
            max_depth: Maximum crawl depth.

        Returns:
            List of PDF URLs found.
        """
        pdf_links = []
        visited = {article_url}
        to_visit = [(article_url, soup, 0)]
        base_domain = urlparse(article_url).netloc

        while to_visit and len(visited) < MAX_PAGES_TO_CRAWL:
            current_url, current_soup, depth = to_visit.pop(0)

            # Collect PDF links from current page
            for a in current_soup.find_all("a", href=True):
                href = a["href"]
                full_url = urljoin(current_url, href)

                if self._is_pdf_url(full_url):
                    pdf_links.append(full_url)
                elif depth < max_depth and fetch_page is not None:
                    parsed = urlparse(full_url)
                    if parsed.netloc == base_domain and full_url not in visited:
                        visited.add(full_url)
                        html, _ = fetch_page(full_url)
                        if html:
                            child_soup = BeautifulSoup(html, "lxml")
                            to_visit.append((full_url, child_soup, depth + 1))
                            for child_a in child_soup.find_all("a", href=True):
                                child_href = child_a["href"]
                                child_full = urljoin(full_url, child_href)
                                if self._is_pdf_url(child_full):
                                    pdf_links.append(child_full)
                        time.sleep(random.uniform(0.5, 1.5))

            # citation_pdf_url meta tag
            pdf_meta = current_soup.find("meta", attrs={"name": "citation_pdf_url"})
            if pdf_meta and pdf_meta.get("content"):
                pdf_links.append(pdf_meta["content"])

        return list(dict.fromkeys(pdf_links))

    def extract_article_metadata(
        self,
        article_url: str,
        soup: BeautifulSoup,
    ) -> ArticleInfo:
        """Trích xuất metadata từ generic page via meta tags."""
        info = ArticleInfo(url=article_url)

        # Title: citation_title > DC.Title > og:title > h1
        info.title = (
            self._extract_meta_content(soup, "citation_title")
            or self._extract_meta_content(soup, "DC.Title")
        )
        if not info.title:
            og_title = soup.find("meta", attrs={"property": "og:title"})
            if og_title and og_title.get("content"):
                info.title = og_title["content"].strip()
        if not info.title:
            h1 = soup.find("h1")
            if h1:
                info.title = h1.get_text(strip=True)

        # Authors
        info.authors = self._extract_all_meta_content(soup, "citation_author")
        if not info.authors:
            info.authors = self._extract_all_meta_content(soup, "DC.Creator")

        # Abstract
        info.abstract = self._extract_meta_content(soup, "DC.Description")
        if not info.abstract:
            info.abstract = self._extract_meta_content(soup, "description")

        return info

    @staticmethod
    def _is_pdf_url(url: str) -> bool:
        """Check if URL points to a PDF."""
        parsed = urlparse(url.lower())
        path = unquote(parsed.path)
        return (
            path.endswith(".pdf")
            or "download/pdf" in path
            or "/pdf/" in path
        )
