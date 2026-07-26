# core/layout_analysis package
"""
Module layout analysis — phân tích bố cục trang PDF.
Column detection, reading order reconstruction, region classification.

Input: DocumentData từ core/text_extraction
Output: LayoutDocument với regions annotated
"""

from core.layout_analysis.layout_model import (
    RegionType,
    Region,
    ColumnInfo,
    LayoutPage,
    LayoutDocument,
)
from core.layout_analysis.layout_analyzer import LayoutAnalyzer
from core.layout_analysis.column_detector import ColumnDetector
from core.layout_analysis.reading_order import ReadingOrderReconstructor
from core.layout_analysis.region_detector import RegionDetector

__all__ = [
    # Models
    "RegionType",
    "Region",
    "ColumnInfo",
    "LayoutPage",
    "LayoutDocument",
    # Core classes
    "LayoutAnalyzer",
    "ColumnDetector",
    "ReadingOrderReconstructor",
    "RegionDetector",
]
