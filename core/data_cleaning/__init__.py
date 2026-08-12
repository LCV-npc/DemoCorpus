# core/data_cleaning package
"""
Module Data Cleaning & Normalization (Milestone 7).

Pipeline: Raw Metadata -> Character Cleaning -> Unicode Normalization
    -> Whitespace Normalization -> Hyphenation Repair
    -> Metadata-specific Cleaning -> Noise Detection
    -> CleaningResult

Input: title (str), authors (list[str]), abstract (str) tu M4/M5/M6.
Output: CleaningResult voi cleaned fields + noise analysis.
"""

from core.data_cleaning.models import (
    CleaningResult,
    NoiseResult,
    # Flag constants
    CHARS_SUBSTITUTED,
    CONTROL_CHARS_REMOVED,
    LIGATURES_EXPANDED,
    UNICODE_NORMALIZED,
    WHITESPACE_COLLAPSED,
    HYPHENATION_REPAIRED,
    TITLE_NEWLINES_REMOVED,
    TITLE_CLEANED,
    AUTHOR_EMAILS_REMOVED,
    AUTHOR_FOOTNOTES_REMOVED,
    AUTHOR_DUPLICATES_REMOVED,
    AUTHOR_ORCID_REMOVED,
    ABSTRACT_HEADER_REMOVED,
    ABSTRACT_FOOTER_REMOVED,
    ABSTRACT_CLEANED,
    HIGH_NON_ALPHA_RATIO,
    HIGH_WHITESPACE_RATIO,
    HIGH_DUPLICATE_LINES,
    HIGH_SYMBOL_RATIO,
    POSSIBLE_GARBLED_TEXT,
    TEXT_TOO_SHORT,
)
from core.data_cleaning.text_cleaner import TextCleaner
from core.data_cleaning.title_cleaner import TitleCleaner
from core.data_cleaning.author_cleaner import MetadataAuthorCleaner
from core.data_cleaning.abstract_cleaner import AbstractCleaner
from core.data_cleaning.noise_detector import NoiseDetector
from core.data_cleaning.service import DataCleaningService

__all__ = [
    # Models
    "CleaningResult",
    "NoiseResult",
    # Cleaners
    "TextCleaner",
    "TitleCleaner",
    "MetadataAuthorCleaner",
    "AbstractCleaner",
    "NoiseDetector",
    # Service
    "DataCleaningService",
]
