"""
core/data_cleaning/author_cleaner.py
MetadataAuthorCleaner -- chuan hoa danh sach author names.

Reuses logic tu core/author_detection/cleaner.py (M5)
va them cac buoc normalization bo sung.

Pipeline cho moi author name:
1. Remove email addresses
2. Remove ORCID patterns
3. Remove footnote markers (superscript digits, *, dagger, etc.)
4. Remove bracket content (affiliations)
5. Unicode normalization (NFC)
6. Whitespace normalization
7. Deduplicate (case-insensitive)

KHONG thay doi ten nguoi.
"""

from __future__ import annotations

import re
import logging

from core.data_cleaning.text_cleaner import TextCleaner
from core.data_cleaning.models import (
    AUTHOR_EMAILS_REMOVED,
    AUTHOR_FOOTNOTES_REMOVED,
    AUTHOR_DUPLICATES_REMOVED,
    AUTHOR_ORCID_REMOVED,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Regex patterns (reuse tu M5 cleaner, nhung o day dung cho
# post-detection cleaning, khong phai detection-time cleaning)
# ─────────────────────────────────────────────

# Email pattern
_EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
)

# ORCID pattern
_ORCID_PATTERN = re.compile(
    r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]",
)

# Footnote markers: superscript digits, *, dagger, etc.
_FOOTNOTE_PATTERN = re.compile(
    r"[¹²³⁴⁵⁶⁷⁸⁹⁰ᵃᵇᶜᵈᵉ*†‡§¶‖#\uE000-\uF8FF]+",
)

# Trailing regular digits after name: "John Doe1,2"
_TRAILING_DIGITS = re.compile(
    r"(?<=\w)\s*[0-9]+(?:\s*[,;]\s*[0-9]+)*\s*$",
)

_INLINE_AFFILIATION_BOUNDARY = re.compile(
    r"(?<=[A-Za-z\u00C0-\u024F\u1E00-\u1EFF])\s*"
    r"[0-9]{1,2}(?:\s*[,;]\s*[0-9]{1,2})*\s*"
    r"(?=[A-Z\u00C0-\u024F\u1E00-\u1EFF])"
)
_LEADING_AFFILIATION_DIGITS = re.compile(
    r"^\s*[0-9]{1,2}(?:\s*[,;]\s*[0-9]{1,2})*\s+"
)

# Leading/trailing noise chars
_NOISE_CHARS = re.compile(r"^[\s,;·&*†‡§¶‖#\-]+|[\s,;·&*†‡§¶‖#\-]+$")


class MetadataAuthorCleaner:
    """
    Post-detection author name cleaner.

    Nhan danh sach author names da extract tu M5,
    ap dung normalization them.
    """

    @staticmethod
    def clean_all(authors: list[str]) -> tuple[list[str], list[str]]:
        """
        Clean danh sach author names.

        Args:
            authors: Danh sach ten tac gia tu M5 AuthorResult.

        Returns:
            (cleaned_authors, changes) -- danh sach da clean va changes.
        """
        if not authors:
            return [], []

        changes: list[str] = []
        cleaned_names: list[str] = []

        for name in authors:
            # M5 can return adjacent author spans in one item when an
            # affiliation marker was their only visual separator.
            candidates = _INLINE_AFFILIATION_BOUNDARY.sub("|", name).split("|")
            for candidate in candidates:
                cleaned = MetadataAuthorCleaner._clean_single(candidate, changes)
                if cleaned:
                    cleaned_names.append(cleaned)

        # Deduplicate (case-insensitive, preserve first occurrence)
        seen_lower: set[str] = set()
        deduped: list[str] = []
        for name in cleaned_names:
            key = name.lower().strip()
            if key not in seen_lower:
                seen_lower.add(key)
                deduped.append(name)
            else:
                if AUTHOR_DUPLICATES_REMOVED not in changes:
                    changes.append(AUTHOR_DUPLICATES_REMOVED)

        return deduped, changes

    @staticmethod
    def _clean_single(name: str, changes: list[str]) -> str:
        """
        Clean mot ten tac gia.

        Args:
            name: Ten tac gia raw.
            changes: List de append changes (mutate in-place).

        Returns:
            Ten da clean, hoac "" neu khong hop le.
        """
        if not name or not name.strip():
            return ""

        result = name

        # Step 1: Remove emails
        cleaned = _EMAIL_PATTERN.sub("", result)
        if cleaned != result:
            if AUTHOR_EMAILS_REMOVED not in changes:
                changes.append(AUTHOR_EMAILS_REMOVED)
        result = cleaned

        # Step 2: Remove ORCID
        cleaned = _ORCID_PATTERN.sub("", result)
        if cleaned != result:
            if AUTHOR_ORCID_REMOVED not in changes:
                changes.append(AUTHOR_ORCID_REMOVED)
        result = cleaned

        # Step 3: Remove footnote markers
        cleaned = _FOOTNOTE_PATTERN.sub("", result)
        if cleaned != result:
            if AUTHOR_FOOTNOTES_REMOVED not in changes:
                changes.append(AUTHOR_FOOTNOTES_REMOVED)
        result = cleaned

        # Remove a detached leading affiliation marker ("2 Nguyễn Văn A").
        result = _LEADING_AFFILIATION_DIGITS.sub("", result)

        # Step 4: Remove trailing digits
        result = _TRAILING_DIGITS.sub("", result)

        # Step 5: Remove leading/trailing noise
        result = _NOISE_CHARS.sub("", result)

        # Step 6: Unicode normalization
        result = TextCleaner.normalize_unicode(result)

        # Step 7: Whitespace normalization
        result = TextCleaner.normalize_whitespace(result, preserve_paragraphs=False)

        return result.strip()
