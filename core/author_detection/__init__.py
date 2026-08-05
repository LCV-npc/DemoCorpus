# core/author_detection package
"""
Module author detection — phát hiện tác giả bài báo khoa học.
3-tier pipeline: Heuristic → NER (optional) → Pattern fallback.

Input: LayoutDocument (M3) + TitleResult (M4)
Output: AuthorResult với danh sách AuthorInfo
"""

from core.author_detection.models import AuthorInfo, AuthorResult
from core.author_detection.cleaner import AuthorCleaner
from core.author_detection.ner_engine import NEREngine, StubNEREngine
from core.author_detection.detector import AuthorDetector
from core.author_detection.service import AuthorDetectionService, AuthorDetectionError

__all__ = [
    # Models
    "AuthorInfo",
    "AuthorResult",
    # Core classes
    "AuthorCleaner",
    "NEREngine",
    "StubNEREngine",
    "AuthorDetector",
    "AuthorDetectionService",
    # Exceptions
    "AuthorDetectionError",
]
