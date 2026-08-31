"""
core/data_cleaning/abstract_cleaner.py
AbstractCleaner -- chuan hoa abstract text bai bao khoa hoc.

Pipeline:
1. Remove stuck header/footer fragments
2. Full text cleaning (character + unicode + whitespace + hyphenation)
3. Join PDF layout line breaks into one readable paragraph

KHONG:
- Paraphrase
- Tom tat lai
- Dich noi dung
- Xoa abstract chi vi nghi ngo
"""

from __future__ import annotations

import re
import logging

from core.data_cleaning.text_cleaner import TextCleaner
from core.data_cleaning.models import (
    ABSTRACT_HEADER_REMOVED,
    ABSTRACT_FOOTER_REMOVED,
    ABSTRACT_CLEANED,
)
from config.constants import HEADER_FOOTER_PATTERNS

logger = logging.getLogger(__name__)

# Pattern cho header/footer bi dinh vao abstract
# (doi:, page numbers, vol., ISSN, received/accepted dates)
_STUCK_HEADER_PATTERNS = [
    # doi at start
    re.compile(r"^doi\s*:\s*10\.\d{4,}[^\n]*\n?", re.IGNORECASE),
    # Page number at start (standalone digit line)
    re.compile(r"^\s*\d{1,4}\s*\n"),
    # Volume/issue at start
    re.compile(r"^vol\.?\s*\d+[^\n]*\n?", re.IGNORECASE),
    # Journal name + volume at start (very generic, only if followed by newline)
    re.compile(r"^[A-Z][a-z]+\s+(Journal|Review|Letters)\s+[^\n]*\n", re.IGNORECASE),
]

_STUCK_FOOTER_PATTERNS = [
    # Page number at end
    re.compile(r"\n\s*\d{1,4}\s*$"),
    # doi at end
    re.compile(r"\n?doi\s*:\s*10\.\d{4,}[^\n]*$", re.IGNORECASE),
    # Copyright at end
    re.compile(r"\n?©\s*\d{4}[^\n]*$"),
    # ISSN at end
    re.compile(r"\n?ISSN\s*[\d\-]+[^\n]*$", re.IGNORECASE),
]


class AbstractCleaner:
    """
    Chuan hoa abstract text bai bao khoa hoc.

    Join line breaks introduced by the PDF layout into normal prose.
    Loai bo header/footer bi dinh.
    """

    @staticmethod
    def clean(abstract: str | None) -> tuple[str | None, list[str]]:
        """
        Clean abstract text.

        Args:
            abstract: Raw abstract text. None -> None.

        Returns:
            (cleaned_abstract, changes) -- abstract da clean va changes.
        """
        if abstract is None:
            return None, []

        if not abstract.strip():
            return None, []

        changes: list[str] = []
        result = abstract

        # Step 1: Remove stuck headers
        for pattern in _STUCK_HEADER_PATTERNS:
            cleaned = pattern.sub("", result, count=1)
            if cleaned != result:
                if ABSTRACT_HEADER_REMOVED not in changes:
                    changes.append(ABSTRACT_HEADER_REMOVED)
                result = cleaned

        # Step 2: Remove stuck footers
        for pattern in _STUCK_FOOTER_PATTERNS:
            cleaned = pattern.sub("", result)
            if cleaned != result:
                if ABSTRACT_FOOTER_REMOVED not in changes:
                    changes.append(ABSTRACT_FOOTER_REMOVED)
                result = cleaned

        # Step 3: PDF extraction emits one newline per visual line. Store
        # abstract metadata as continuous prose instead of layout fragments.
        cleaned, text_changes = TextCleaner.full_clean(
            result, preserve_paragraphs=False
        )
        changes.extend(text_changes)
        result = cleaned

        if changes:
            changes.append(ABSTRACT_CLEANED)

        # Final validation
        if not result.strip():
            return None, changes

        return result.strip(), changes
