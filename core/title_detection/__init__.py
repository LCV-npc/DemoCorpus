# core/title_detection package
"""
Module title detection — phát hiện tiêu đề bài báo khoa học.
3-strategy pipeline: Zone-based → Font-based → First-line fallback.

Input: LayoutDocument từ core/layout_analysis
Output: TitleResult với title, confidence, bbox, page
"""

from core.title_detection.models import TitleCandidate, TitleResult
from core.title_detection.exceptions import TitleDetectionError
from core.title_detection.rules import is_plausible_title, is_noise
from core.title_detection.scorer import TitleScorer
from core.title_detection.detector import TitleDetector
from core.title_detection.service import TitleDetectionService

__all__ = [
    # Models
    "TitleCandidate",
    "TitleResult",
    # Exceptions
    "TitleDetectionError",
    # Rules
    "is_plausible_title",
    "is_noise",
    # Core classes
    "TitleScorer",
    "TitleDetector",
    "TitleDetectionService",
]
