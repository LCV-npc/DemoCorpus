"""
infrastructure/scraper/adapters/base.py
Abstract base class for site-specific crawling adapters.

Thiết kế Site Adapter pattern:
- Mỗi website/CMS có adapter riêng.
- Adapter chịu trách nhiệm: phát hiện articles, tìm PDF URLs, trích xuất metadata HTML.
- PDFScraper chỉ orchestrate: detect site → chọn adapter → gọi adapter methods.
- Thêm website mới = thêm 1 file adapter mới, không sửa core scraper.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class ArticleInfo:
    """Thông tin bài báo phát hiện từ trang web."""
    url: str = ""
    title: Optional[str] = None
    authors: list[str] = field(default_factory=list)
    abstract: Optional[str] = None
    pdf_url: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class BaseSiteAdapter(ABC):
    """
    Abstract base class cho site-specific adapters.

    Mỗi adapter triển khai 3 methods:
    1. discover_articles(): Tìm danh sách bài báo từ trang.
    2. find_pdf_url(): Tìm URL tải PDF cho 1 bài báo.
    3. extract_article_metadata(): Trích xuất metadata từ HTML.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Tên adapter (dùng cho logging)."""
        ...

    @abstractmethod
    def discover_articles(
        self,
        url: str,
        soup: BeautifulSoup,
        fetch_page,
        status_callback=None,
    ) -> list[str]:
        """
        Phát hiện tất cả article URLs từ trang đầu vào.

        Args:
            url: URL trang đầu vào (archive, issue, hoặc article).
            soup: Parsed HTML của trang.
            fetch_page: Callable(url) -> (html, final_url) — dùng để fetch thêm trang.
            status_callback: Optional callable(msg, level) cho logging.

        Returns:
            Danh sách article URLs.
        """
        ...

    @abstractmethod
    def find_pdf_urls(
        self,
        article_url: str,
        soup: BeautifulSoup,
    ) -> list[str]:
        """
        Tìm tất cả PDF URLs từ trang article.

        Args:
            article_url: URL trang bài báo.
            soup: Parsed HTML của trang bài báo.

        Returns:
            Danh sách PDF download URLs.
        """
        ...

    @abstractmethod
    def extract_article_metadata(
        self,
        article_url: str,
        soup: BeautifulSoup,
    ) -> ArticleInfo:
        """
        Trích xuất metadata (title, authors, abstract) từ HTML.

        Args:
            article_url: URL trang bài báo.
            soup: Parsed HTML.

        Returns:
            ArticleInfo với metadata đã trích xuất.
        """
        ...

    @staticmethod
    def _extract_meta_content(soup: BeautifulSoup, name: str) -> Optional[str]:
        """Helper: lấy content từ <meta name='...'> tag."""
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag["content"].strip()
        return None

    @staticmethod
    def _extract_all_meta_content(soup: BeautifulSoup, name: str) -> list[str]:
        """Helper: lấy tất cả content từ <meta name='...'> tags."""
        tags = soup.find_all("meta", attrs={"name": name})
        return [t["content"].strip() for t in tags if t.get("content")]
