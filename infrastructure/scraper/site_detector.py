"""
infrastructure/scraper/site_detector.py
Phát hiện loại trang web (OJS, Generic) và trả về adapter phù hợp.

Flow:
1. Check meta generator tag → "OJS" → OJSSiteAdapter
2. Check URL patterns → /article/view/, /issue/view/ → OJSSiteAdapter
3. Check page structure → archive links → OJSSiteAdapter
4. Fallback → GenericSiteAdapter
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from infrastructure.scraper.adapters.base import BaseSiteAdapter
from infrastructure.scraper.adapters.ojs import OJSSiteAdapter
from infrastructure.scraper.adapters.generic import GenericSiteAdapter

logger = logging.getLogger(__name__)

# Singleton instances
_ojs_adapter = OJSSiteAdapter()
_generic_adapter = GenericSiteAdapter()


class SiteDetector:
    """
    Phát hiện loại trang web và trả về adapter phù hợp.

    Usage:
        detector = SiteDetector()
        adapter = detector.detect(url, soup)
        articles = adapter.discover_articles(url, soup, fetch_page)
    """

    @staticmethod
    def detect(url: str, soup: BeautifulSoup) -> BaseSiteAdapter:
        """
        Phát hiện loại trang và trả về adapter.

        Args:
            url: URL trang web.
            soup: Parsed HTML.

        Returns:
            BaseSiteAdapter phù hợp.
        """
        # Check 1: OJS meta generator
        generator = soup.find("meta", attrs={
            "name": "generator",
            "content": re.compile(r"OJS", re.I)
        })
        if generator:
            logger.info(f"SiteDetector: OJS detected via meta generator")
            return _ojs_adapter

        # Check 2: OJS URL patterns
        ojs_url_patterns = [
            "/issue/view/",
            "/article/view/",
            "/issue/archive",
        ]
        if any(pattern in url for pattern in ojs_url_patterns):
            logger.info(f"SiteDetector: OJS detected via URL pattern")
            return _ojs_adapter

        # Check 3: OJS page structure (archive links)
        ojs_link_patterns = [
            soup.find("a", href=re.compile(r"/issue/view/")),
            soup.find("a", href=re.compile(r"/issue/archive")),
        ]
        if any(ojs_link_patterns):
            logger.info(f"SiteDetector: OJS detected via page structure")
            return _ojs_adapter

        # Fallback: Generic
        logger.info(f"SiteDetector: No specific CMS detected, using Generic adapter")
        return _generic_adapter
