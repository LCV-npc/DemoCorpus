"""Locate deterministic real-PDF fixtures from the local scraped corpus."""

from __future__ import annotations

from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parent.parent
SCRAPED_PDFS_DIR = BACKEND_ROOT / "data" / "scraped_pdfs"
PREFERRED_SAMPLE_FILENAME = "pdf_be1d0508.pdf"


def find_scraped_pdf(preferred_filename: str = PREFERRED_SAMPLE_FILENAME) -> Path | None:
    """Return a stable text-rich corpus PDF, with a deterministic fallback."""
    if not SCRAPED_PDFS_DIR.exists():
        return None

    preferred = sorted(SCRAPED_PDFS_DIR.rglob(preferred_filename))
    if preferred:
        return preferred[0].resolve()

    candidates = sorted(
        (
            path
            for path in SCRAPED_PDFS_DIR.rglob("*.pdf")
            if path.is_file() and path.stat().st_size >= 32 * 1024
        ),
        key=lambda path: (path.stat().st_size, str(path).casefold()),
    )
    return candidates[0].resolve() if candidates else None


SCRAPED_SAMPLE_PDF = find_scraped_pdf()
