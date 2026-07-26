"""
core/layout_analysis/reading_order.py
ReadingOrderReconstructor — xây dựng thứ tự đọc đúng cho blocks.

Thuật toán:
- 1 cột: sort theo y0 (top → bottom)
- 2 cột:
  1. Phân blocks thành FULL-WIDTH, LEFT-COL, RIGHT-COL
  2. Tìm các "separator" (full-width blocks) chia trang thành bands
  3. Trong mỗi band: emit LEFT blocks (sorted y0) rồi RIGHT blocks (sorted y0)
  4. Full-width blocks emit theo vị trí y0 tự nhiên
  → Đảm bảo: đọc trái ↓ rồi phải ↓, KHÔNG đọc lẫn
"""

from __future__ import annotations

import logging

from core.text_extraction.models import BlockData
from core.layout_analysis.layout_model import ColumnInfo
from core.layout_analysis.heuristics import block_center_x, is_full_width

logger = logging.getLogger(__name__)


class ReadingOrderReconstructor:
    """Tái tạo thứ tự đọc đúng cho blocks dựa trên column info."""

    def reconstruct(
        self,
        blocks: list[BlockData],
        column_info: ColumnInfo,
        page_width: float,
    ) -> list[BlockData]:
        """
        Sắp xếp blocks theo thứ tự đọc tự nhiên.

        Args:
            blocks: Danh sách BlockData chưa sắp xếp.
            column_info: Thông tin cột từ ColumnDetector.
            page_width: Chiều rộng trang.

        Returns:
            List BlockData đã sắp xếp theo reading order.
        """
        # Chỉ xử lý text blocks
        text_blocks = [b for b in blocks if b.block_type == 0]

        if not text_blocks:
            return []

        if column_info.column_count == 1:
            return self._order_single_column(text_blocks)
        else:
            return self._order_two_column(text_blocks, column_info, page_width)

    def _order_single_column(self, blocks: list[BlockData]) -> list[BlockData]:
        """1 cột: sort theo y0 đơn giản."""
        return sorted(blocks, key=lambda b: b.bbox[1])

    def _order_two_column(
        self,
        blocks: list[BlockData],
        column_info: ColumnInfo,
        page_width: float,
    ) -> list[BlockData]:
        """
        2 cột: phân thành bands bởi full-width blocks,
        trong mỗi band đọc left → right.
        """
        page_center = page_width / 2

        # Phân loại blocks
        full_width: list[BlockData] = []
        left_col: list[BlockData] = []
        right_col: list[BlockData] = []

        for block in blocks:
            # Block is a separator if it's explicitly full width or if it crosses the column gap
            crosses_gap = (
                block.bbox[0] <= column_info.gap_start and 
                block.bbox[2] >= column_info.gap_end
            )
            if is_full_width(block, page_width) or crosses_gap:
                full_width.append(block)
            elif block_center_x(block) < page_center:
                left_col.append(block)
            else:
                right_col.append(block)

        # Sort mỗi nhóm theo y0
        full_width.sort(key=lambda b: b.bbox[1])
        left_col.sort(key=lambda b: b.bbox[1])
        right_col.sort(key=lambda b: b.bbox[1])

        # Nếu không có full-width separators → left all rồi right all
        if not full_width:
            return left_col + right_col

        # Xây dựng bands chia bởi full-width blocks
        # Mỗi band = (y_start, y_end) giữa 2 full-width blocks
        result: list[BlockData] = []

        # Thêm sentinel ở đầu và cuối
        separator_ys = (
            [0.0]
            + [b.bbox[1] for b in full_width]
            + [float("inf")]
        )

        for i in range(len(separator_ys) - 1):
            band_start = separator_ys[i]
            band_end = separator_ys[i + 1]

            # Emit full-width block tại band_start (nếu có)
            for fw in full_width:
                if fw.bbox[1] == band_start and band_start > 0:
                    result.append(fw)

            # Collect left/right blocks trong band này
            band_left = [
                b for b in left_col
                if band_start <= b.bbox[1] < band_end
            ]
            band_right = [
                b for b in right_col
                if band_start <= b.bbox[1] < band_end
            ]

            # Emit: left ↓ rồi right ↓
            result.extend(band_left)
            result.extend(band_right)

        # Catch any full-width blocks at the very start (band_start == 0)
        # that weren't emitted
        emitted_ids = {id(b) for b in result}
        for fw in full_width:
            if id(fw) not in emitted_ids:
                # Insert at correct position based on y0
                inserted = False
                for idx, existing in enumerate(result):
                    if fw.bbox[1] < existing.bbox[1]:
                        result.insert(idx, fw)
                        inserted = True
                        break
                if not inserted:
                    result.append(fw)

        return result
