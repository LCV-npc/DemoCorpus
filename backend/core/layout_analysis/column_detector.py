"""
core/layout_analysis/column_detector.py
ColumnDetector — phát hiện cấu trúc 1-cột hoặc 2-cột.

Thuật toán:
1. Lọc ra narrow blocks (width < 60% page width)
2. Phân loại blocks thành LEFT / RIGHT dựa trên center_x so với page center
3. Nếu cả 2 bên đều có ≥ 2 blocks và tồn tại gap giữa → 2 cột
4. Ngược lại → 1 cột
"""

from __future__ import annotations

import logging

from core.text_extraction.models import BlockData
from core.layout_analysis.layout_model import ColumnInfo
from core.layout_analysis.heuristics import (
    block_center_x,
    block_width,
    is_full_width,
)

logger = logging.getLogger(__name__)

# Khoảng gap tối thiểu giữa 2 cột (points)
MIN_COLUMN_GAP = 5.0

# Số blocks tối thiểu mỗi bên để xác nhận 2 cột
MIN_BLOCKS_PER_COLUMN = 2


class ColumnDetector:
    """Phát hiện cấu trúc cột của một trang PDF."""

    def detect(self, blocks: list[BlockData], page_width: float) -> ColumnInfo:
        """
        Phát hiện cấu trúc cột từ danh sách blocks.

        Args:
            blocks: Danh sách BlockData của một trang.
            page_width: Chiều rộng trang (points).

        Returns:
            ColumnInfo với column_count và boundaries.
        """
        if not blocks or page_width <= 0:
            return ColumnInfo(column_count=1)

        # Bước 1: Lọc text blocks, bỏ image blocks
        text_blocks = [b for b in blocks if b.block_type == 0]
        if not text_blocks:
            return ColumnInfo(column_count=1)

        # Bước 2: Lọc narrow blocks (loại bỏ full-width blocks)
        narrow_blocks = [
            b for b in text_blocks if not is_full_width(b, page_width)
        ]
        if len(narrow_blocks) < MIN_BLOCKS_PER_COLUMN * 2:
            return ColumnInfo(column_count=1)

        # Bước 3: Phân loại LEFT / RIGHT
        page_center = page_width / 2
        left_blocks: list[BlockData] = []
        right_blocks: list[BlockData] = []

        for block in narrow_blocks:
            col = self._classify_block_column(block, page_center)
            if col == "left":
                left_blocks.append(block)
            elif col == "right":
                right_blocks.append(block)

        # Bước 4: Kiểm tra đủ blocks mỗi bên
        if (
            len(left_blocks) < MIN_BLOCKS_PER_COLUMN
            or len(right_blocks) < MIN_BLOCKS_PER_COLUMN
        ):
            return ColumnInfo(column_count=1)

        # Bước 5: Tính boundaries và gap
        left_max_x1 = max(b.bbox[2] for b in left_blocks)
        right_min_x0 = min(b.bbox[0] for b in right_blocks)
        gap = right_min_x0 - left_max_x1

        if gap < MIN_COLUMN_GAP:
            return ColumnInfo(column_count=1)

        # 2 cột xác nhận
        left_min_x0 = min(b.bbox[0] for b in left_blocks)
        right_max_x1 = max(b.bbox[2] for b in right_blocks)

        return ColumnInfo(
            column_count=2,
            left_boundary=round(left_min_x0, 2),
            right_boundary=round(right_max_x1, 2),
            gap_start=round(left_max_x1, 2),
            gap_end=round(right_min_x0, 2),
        )

    @staticmethod
    def _classify_block_column(block: BlockData, page_center: float) -> str:
        """
        Phân loại block thuộc cột nào.

        Returns: "left", "right", hoặc "center" (nếu block nằm giữa).
        """
        center = block_center_x(block)
        # Margin nhỏ quanh page center
        margin = page_center * 0.05

        if center < page_center - margin:
            return "left"
        elif center > page_center + margin:
            return "right"
        else:
            return "center"
