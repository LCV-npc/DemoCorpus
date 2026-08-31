"""
core/data_cleaning/title_cleaner.py
TitleCleaner -- chuan hoa title bai bao khoa hoc.

Chi lam:
- Collapse whitespace va newlines
- Loai bo control characters
- Loai bo ky tu dac biet dau/cuoi
- Character substitution (ligatures, smart quotes)
- Unicode normalization (NFC)

KHONG lam:
- Thay doi noi dung title
- Paraphrase
- Dich
- Capitalize lai
"""

from __future__ import annotations

import re
import logging

from core.data_cleaning.text_cleaner import TextCleaner
from core.data_cleaning.models import TITLE_CLEANED, TITLE_NEWLINES_REMOVED

logger = logging.getLogger(__name__)

# Leading/trailing noise: doi, page numbers, symbols
_LEADING_NOISE = re.compile(
    r"^[\s\d\.\,\;\:\-\*\#\(\)\[\]]+(?=[A-Z\u00C0-\u024F])"
)

# Trailing noise: standalone page numbers or trailing symbols (only after whitespace)
_TRAILING_NOISE = re.compile(
    r"\s+[\.\,\;\:\*\#]+$"
)


class TitleCleaner:
    """
    Chuan hoa title bai bao khoa hoc.

    Stateless. An toan cho Vietnamese + English titles.
    """

    @staticmethod
    def clean(title: str | None) -> tuple[str | None, list[str]]:
        """
        Clean title text.

        Args:
            title: Raw title text. None -> None.

        Returns:
            (cleaned_title, changes) -- title da clean va danh sach thay doi.
        """
        if title is None:
            return None, []

        if not title.strip():
            return None, []

        changes: list[str] = []

        # Step 1: Full text cleaning (no paragraph preservation)
        cleaned, text_changes = TextCleaner.full_clean(
            title, preserve_paragraphs=False
        )
        changes.extend(text_changes)

        # Step 2: Collapse all newlines -> space (title khong co newline)
        if "\n" in cleaned:
            cleaned = cleaned.replace("\n", " ")
            changes.append(TITLE_NEWLINES_REMOVED)

        # Step 3: Collapse multiple spaces -> single
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        # Step 4: Remove leading noise (page numbers, symbols before title)
        stripped = _LEADING_NOISE.sub("", cleaned)
        if stripped != cleaned:
            changes.append("leading_noise_removed")
            cleaned = stripped

        # Step 5: Remove trailing noise
        stripped = _TRAILING_NOISE.sub("", cleaned).strip()
        if stripped != cleaned and stripped:
            changes.append("trailing_noise_removed")
            cleaned = stripped

        if changes:
            changes.append(TITLE_CLEANED)

        # Final validation
        if not cleaned.strip():
            return None, changes

        return cleaned.strip(), changes
