"""
Demo Milestone 3 — Layout Analysis.
Hiển thị từng bước: Column Detection → Reading Order → Region Detection.

Chạy: python demo_m3.py
"""
import sys
from pathlib import Path

# Đảm bảo import đúng dù chạy từ đâu
_project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(_project_root))

from core.text_extraction.extractor import PDFTextExtractor
from core.layout_analysis.column_detector import ColumnDetector
from core.layout_analysis.reading_order import ReadingOrderReconstructor
from core.layout_analysis.region_detector import RegionDetector
from core.layout_analysis.layout_analyzer import LayoutAnalyzer
from core.layout_analysis.layout_model import RegionType
from core.layout_analysis import heuristics as h


def find_sample_pdf() -> str:
    """Tìm file PDF mẫu trong thư mục data/scraped_pdfs."""
    scraped_dir = _project_root / "data" / "scraped_pdfs"
    if scraped_dir.exists():
        for pdf in scraped_dir.rglob("*.pdf"):
            return str(pdf)

    parent_dir = _project_root.parent
    for pdf in parent_dir.glob("*.pdf"):
        return str(pdf)

    return ""


def print_separator(title: str):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def main():
    pdf_path = find_sample_pdf()
    if not pdf_path:
        print("[LỖI] Không tìm thấy file PDF mẫu.")
        print(f"  Hãy đặt file PDF vào: {_project_root / 'data' / 'scraped_pdfs'}")
        return

    # =====================================================
    # BƯỚC 1: Extract text từ PDF (Milestone 2)
    # =====================================================
    extractor = PDFTextExtractor()
    doc = extractor.extract(pdf_path)

    print_separator("BƯỚC 1: TEXT EXTRACTION (Milestone 2)")
    print(f"  File: {Path(pdf_path).name}")
    print(f"  Số trang: {doc.page_count}")
    print(f"  Tổng blocks: {doc.total_blocks}")

    # =====================================================
    # BƯỚC 2: Phân tích trang đầu tiên CHI TIẾT
    # =====================================================
    page = doc.pages[0]

    print_separator(f"BƯỚC 2: CHI TIẾT TRANG 0 ({page.width:.0f} x {page.height:.0f} pts, {len(page.blocks)} blocks)")

    print("\n--- Tất cả blocks trên trang 0 ---")
    for b in page.blocks:
        if b.block_type != 0:
            continue
        font_size = h.dominant_font_size(b)
        font_flags = h.dominant_font_flags(b)
        bold = h.is_bold(font_flags)
        centered = h.is_centered(b, page.width)
        full_w = h.is_full_width(b, page.width)
        rel_y = h.relative_y(b, page.height)

        text_preview = b.text.replace('\n', ' ')[:60]

        print(f"  Block {b.block_number:2d}: "
              f"y={b.bbox[1]:6.1f} "
              f"font={font_size:4.1f} "
              f"{'BOLD' if bold else '    '} "
              f"{'CENTER' if centered else '      '} "
              f"{'FULL-W' if full_w else '      '} "
              f"rel_y={rel_y:.2f} "
              f"| {text_preview!r}")

    # =====================================================
    # BƯỚC 3: Column Detection
    # =====================================================
    col_detector = ColumnDetector()
    col_info = col_detector.detect(page.blocks, page.width)

    print_separator("BƯỚC 3: COLUMN DETECTION")
    
    # Thêm dòng debug cho Column Detection
    narrow_blocks = [b for b in page.blocks if not h.is_full_width(b, page.width) and b.block_type == 0]
    left_blocks = [b for b in narrow_blocks if h.block_center_x(b) < page.width / 2 - 15.0]
    right_blocks = [b for b in narrow_blocks if h.block_center_x(b) > page.width / 2 + 15.0]
    
    debug_msg = f"  [DEBUG] Narrow blocks: {len(narrow_blocks)}, Left: {len(left_blocks)}, Right: {len(right_blocks)}"
    if len(left_blocks) > 0 and len(right_blocks) > 0:
        left_max_x1 = max(b.bbox[2] for b in left_blocks)
        right_min_x0 = min(b.bbox[0] for b in right_blocks)
        gap = right_min_x0 - left_max_x1
        debug_msg += f", left_x1: {left_max_x1:.1f}, right_x0: {right_min_x0:.1f}, gap: {gap:.1f}"
    print(debug_msg)

    print(f"  Kết quả: {col_info.column_count} cột ({col_info.layout_type})")
    if col_info.column_count == 2:
        print(f"  Cột trái kết thúc tại x = {col_info.gap_start:.1f}")
        print(f"  Cột phải bắt đầu tại  x = {col_info.gap_end:.1f}")
        print(f"  Khoảng cách gap = {col_info.gap_end - col_info.gap_start:.1f} pts")

    # =====================================================
    # BƯỚC 4: Reading Order
    # =====================================================
    ro = ReadingOrderReconstructor()
    ordered = ro.reconstruct(page.blocks, col_info, page.width)

    print_separator("BƯỚC 4: READING ORDER (thứ tự đọc)")
    print(f"  {len(ordered)} text blocks đã sắp xếp:\n")

    page_center = page.width / 2
    for i, b in enumerate(ordered):
        text_preview = b.text.replace('\n', ' ')[:50]
        col_label = ""
        if col_info.column_count == 2:
            cx = h.block_center_x(b)
            crosses_gap = (b.bbox[0] <= col_info.gap_start and
                           b.bbox[2] >= col_info.gap_end)
            if h.is_full_width(b, page.width) or crosses_gap:
                col_label = "[FULL-WIDTH]"
            elif cx < page_center:
                col_label = "[CỘT TRÁI] "
            else:
                col_label = "[CỘT PHẢI] "
        print(f"  {i+1:2d}. {col_label} Block{b.block_number:2d} "
              f"y={b.bbox[1]:6.1f} | {text_preview!r}")

    # =====================================================
    # BƯỚC 5: Region Detection
    # =====================================================
    print_separator("BƯỚC 5: REGION DETECTION (phân loại vùng)")

    # Hiển thị structural markers
    print("\n--- Tìm các dấu mốc (structural markers) ---")
    found_markers = False
    for b in ordered:
        text = b.text.strip()
        markers = []
        if h.matches_abstract_start(text):
            markers.append("Abstract/TÓM TẮT")
        if h.matches_keyword_start(text):
            markers.append("Keywords/Từ khóa")
        if h.matches_reference_start(text):
            markers.append("References/TLTK")
        if h.matches_header_footer(text):
            markers.append("Header/Footer")
        for m in markers:
            found_markers = True
            print(f"  >> {m:20s} tại y={b.bbox[1]:.1f}: {text[:40]!r}")
    if not found_markers:
        print("  (Không tìm thấy structural markers)")

    # Chạy region detection
    region_detector = RegionDetector()
    regions = region_detector.detect(page, col_info, ordered)

    print(f"\n--- Kết quả: {len(regions)} regions ---")
    for r in regions:
        text_clean = r.text.replace('\n', ' ')[:50]
        print(f"  Region {r.reading_order_index}: "
              f"[{r.region_type.value:12s}] "
              f"conf={r.confidence:.2f} "
              f"blocks={len(r.blocks):2d} "
              f"y=({r.bbox[1]:.0f}→{r.bbox[3]:.0f}) "
              f"| {text_clean!r}")

    # =====================================================
    # BƯỚC 6: Full pipeline — tất cả trang
    # =====================================================
    analyzer = LayoutAnalyzer()
    layout = analyzer.analyze(doc)

    print_separator("BƯỚC 6: TỔNG HỢP TOÀN BỘ DOCUMENT")
    print(f"  Tổng regions: {layout.total_regions}")
    print(f"  Thời gian:    {layout.analysis_time_seconds:.3f}s")

    for p in layout.pages:
        region_summary = {}
        for r in p.regions:
            rt = r.region_type.value
            region_summary[rt] = region_summary.get(rt, 0) + 1
        print(f"\n  Trang {p.page_number}: {p.layout_type:14s} | {region_summary}")

    # Thống kê theo loại region
    print("\n--- Thống kê theo loại region ---")
    for rt in RegionType:
        found = layout.get_regions(rt)
        if found:
            total_text = sum(len(r.text) for r in found)
            pages_on = sorted({r.page_number for r in found})
            print(f"  {rt.value:12s}: {len(found):2d} regions, "
                  f"~{total_text:5d} chars, "
                  f"trang {pages_on}")


if __name__ == "__main__":
    main()
