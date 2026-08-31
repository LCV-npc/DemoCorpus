"""Publication-date extraction with deterministic, explainable fallbacks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class PublicationDate:
    year: int | None
    value: str | None
    status: str
    source: str


class PublicationDateExtractor:
    """Extract a publication year without treating a URL as authoritative."""

    META_FIELDS = (
        "citation_publication_date", "citation_date", "citation_online_date",
        "dc.date", "dc.date.issued", "article:published_time", "date",
        "publication_date",
    )

    def __init__(self, current_year: int | None = None):
        self.current_year = current_year or datetime.now().year

    def extract(
        self,
        soup: BeautifulSoup,
        url: str = "",
        inherited_year: int | None = None,
    ) -> PublicationDate:
        for field in self.META_FIELDS:
            value = self._meta_value(soup, field)
            year = self._year(value)
            if year:
                return PublicationDate(year, value, "detected", f"meta:{field}")

        for value in self._json_ld_dates(soup):
            year = self._year(value)
            if year:
                return PublicationDate(year, value, "detected", "json-ld:datePublished")

        for value in self._visible_publication_dates(soup):
            year = self._year(value)
            if year:
                return PublicationDate(year, value, "detected", "published-label")

        if self._valid_year(inherited_year):
            return PublicationDate(inherited_year, str(inherited_year), "detected", "issue-or-archive")

        url_year = self._year(url)
        if url_year:
            return PublicationDate(url_year, str(url_year), "heuristic", "url")

        return PublicationDate(None, None, "unknown", "none")

    def _valid_year(self, value: Any) -> bool:
        return isinstance(value, int) and 1900 <= value <= self.current_year + 1

    def _year(self, value: Any) -> int | None:
        if not isinstance(value, str):
            return None
        match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", value)
        if not match:
            return None
        year = int(match.group(1))
        return year if self._valid_year(year) else None

    @staticmethod
    def _meta_value(soup: BeautifulSoup, field: str) -> str | None:
        field = field.lower()
        for tag in soup.find_all("meta"):
            key = (tag.get("name") or tag.get("property") or "").lower()
            if key == field and tag.get("content"):
                return tag["content"].strip()
        return None

    @staticmethod
    def _json_ld_dates(soup: BeautifulSoup) -> list[str]:
        values: list[str] = []
        for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                payload = json.loads(tag.string or tag.get_text())
            except (json.JSONDecodeError, TypeError):
                continue
            stack = payload if isinstance(payload, list) else [payload]
            while stack:
                item = stack.pop()
                if isinstance(item, dict):
                    date = item.get("datePublished")
                    if isinstance(date, str):
                        values.append(date)
                    graph = item.get("@graph")
                    if isinstance(graph, list):
                        stack.extend(graph)
        return values

    @staticmethod
    def _visible_publication_dates(soup: BeautifulSoup) -> list[str]:
        """Read dates from explicit publication fields only.

        A whole-page text scan is deliberately unsafe: medical articles often
        contain many years in citations, study periods, and their title.  Only
        semantic date elements or text adjacent to a Published/Ngày xuất bản
        label may be treated as publication metadata.
        """
        values: list[str] = []
        for tag in soup.select(
            "time[datetime], .published, .date-published, "
            "[class*='published'], [id*='published']"
        ):
            value = tag.get("datetime") or tag.get_text(" ", strip=True)
            if value:
                values.append(value)

        label_pattern = re.compile(
            r"date\s*published|published\s*date|ngày\s*xuất\s*bản",
            re.IGNORECASE,
        )
        for label in soup.find_all(string=label_pattern):
            parent = label.parent
            ancestors = [parent, *parent.parents] if parent else []
            for container in ancestors:
                if not getattr(container, "get_text", None):
                    continue
                value = container.get_text(" ", strip=True)
                if value:
                    values.append(value)
                # The nearest meaningful ancestor contains the label and its
                # value; do not expand into the entire article body.
                if container.name in {"div", "li", "p", "section", "article"}:
                    break
        return values
