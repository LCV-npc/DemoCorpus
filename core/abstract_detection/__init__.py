# core/abstract_detection package
"""
Module abstract detection — phát hiện abstract/tóm tắt bài báo khoa học.
2-strategy pipeline: Keyword Anchoring → Layout Zone Fallback.

Input: DocumentData (M2) + LayoutDocument (M3)
Output: AbstractResult với text, confidence, method, flags
"""

from core.abstract_detection.models import (
    AbstractResult,
    ABSTRACT_MAY_BE_LIST,
    ABSTRACT_TOO_SHORT,
    ABSTRACT_TOO_LONG,
    ABSTRACT_STARTS_WITH_KEYWORD,
)
from core.abstract_detection.exceptions import AbstractDetectionError
from core.abstract_detection.detector import AbstractDetector
from core.abstract_detection.service import AbstractDetectionService

__all__ = [
    # Models
    "AbstractResult",
    # Flag constants
    "ABSTRACT_MAY_BE_LIST",
    "ABSTRACT_TOO_SHORT",
    "ABSTRACT_TOO_LONG",
    "ABSTRACT_STARTS_WITH_KEYWORD",
    # Exceptions
    "AbstractDetectionError",
    # Core classes
    "AbstractDetector",
    "AbstractDetectionService",
]
