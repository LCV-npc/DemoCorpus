"""Centralized, safe path construction for crawled PDF files."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse


class ScrapedPDFPathBuilder:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def build_path(self, source_url: str, publication_year: int | None, filename: str) -> Path:
        domain = self._domain(source_url)
        year = str(publication_year) if publication_year else "unknown"
        safe_name = self._filename(filename)
        path = self.root / domain / year / safe_name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _domain(source_url: str) -> str:
        host = urlparse(source_url).hostname or "unknown-site"
        return re.sub(r"[^A-Za-z0-9.-]+", "-", host.lower().removeprefix("www.")).strip(".-") or "unknown-site"

    @staticmethod
    def _filename(filename: str) -> str:
        stem = Path(filename).stem
        stem = re.sub(r"[\\/*?:\"<>|\x00-\x1f]+", "-", stem)
        stem = re.sub(r"\s+", "-", stem).strip(".-")[:96] or "paper"
        return f"{stem}.pdf"
