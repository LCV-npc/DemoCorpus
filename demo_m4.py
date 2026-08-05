"""
Demo Milestone 4 — Title Detection.
Hiển thị kết quả title detection trên tất cả PDF mẫu.

Chạy: python demo_m4.py

Pipeline:
1. Text Extraction (M2) → DocumentData
2. Layout Analysis (M3) → LayoutDocument
3. Title Detection (M4) → TitleResult
"""

import sys
import logging
from pathlib import Path

# Đảm bảo import đúng dù chạy từ đâu
_project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(_project_root))

from core.text_extraction.extractor import PDFTextExtractor
from core.layout_analysis.layout_analyzer import LayoutAnalyzer
from core.title_detection.detector import TitleDetector
from core.title_detection.service import TitleDetectionService


def find_sample_pdfs() -> list[str]:
    """Tìm tất cả PDF mẫu."""
    pdf_paths: list[str] = []

    # Tìm trong thư mục cha (nơi chứa các PDF mẫu)
    parent_dir = _project_root.parent
    for pdf in parent_dir.glob("*.pdf"):
        pdf_paths.append(str(pdf))

    # Tìm trong data/scraped_pdfs
    scraped_dir = _project_root / "data" / "scraped_pdfs"
    if scraped_dir.exists():
        for pdf in scraped_dir.rglob("*.pdf"):
            pdf_paths.append(str(pdf))

    return pdf_paths


def print_separator(title: str):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def main():
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    pdf_paths = find_sample_pdfs()
    if not pdf_paths:
        print("[LỖI] Không tìm thấy file PDF mẫu.")
        return

    print_separator(f"DEMO MILESTONE 4: TITLE DETECTION — {len(pdf_paths)} PDFs")

    # Khởi tạo pipeline
    extractor = PDFTextExtractor()
    analyzer = LayoutAnalyzer()
    service = TitleDetectionService()

    results_summary = []

    for i, pdf_path in enumerate(pdf_paths, start=1):
        file_name = Path(pdf_path).name

        print_separator(f"[{i}/{len(pdf_paths)}] {file_name}")

        try:
            # Bước 1: Text Extraction
            doc_data = extractor.extract(pdf_path)
            print(f"  ✓ Text Extraction: {doc_data.page_count} pages, "
                  f"{doc_data.total_blocks} blocks")

            # Bước 2: Layout Analysis
            layout_doc = analyzer.analyze(doc_data)
            print(f"  ✓ Layout Analysis: {layout_doc.total_regions} regions, "
                  f"{layout_doc.analysis_time_seconds:.3f}s")

            # Hiển thị TITLE regions từ Layout Analysis
            from core.layout_analysis.layout_model import RegionType
            title_regions = layout_doc.get_regions(RegionType.TITLE, page_number=0)
            if title_regions:
                print(f"  ► TITLE regions trên trang 0: {len(title_regions)}")
                for r in title_regions:
                    text_preview = r.text.replace('\n', ' ')[:60]
                    print(f"    - bbox={r.bbox} conf={r.confidence:.2f} "
                          f"| {text_preview!r}")
            else:
                print("  ► Không có TITLE region → sẽ dùng fallback")

            # Bước 3: Title Detection
            result = service.detect_title(layout_doc)

            # Hiển thị kết quả
            print(f"\n  ═══ KẾT QUẢ TITLE DETECTION ═══")
            if result.title:
                print(f"  Title:      {result.title!r}")
                print(f"  Confidence: {result.confidence:.4f}")
                print(f"  Strategy:   {result.strategy}")
                print(f"  Raw Score:  {result.raw_score:.2f}")
                print(f"  BBox:       {result.bbox}")
                print(f"  Page:       {result.page}")

                # Hiển thị dạng JSON
                print(f"\n  JSON Output:")
                import json
                print(f"  {json.dumps(result.to_dict(), indent=4, ensure_ascii=False)}")

                results_summary.append({
                    "file": file_name,
                    "title": result.title[:50],
                    "confidence": result.confidence,
                    "strategy": result.strategy,
                })
            else:
                print("  ✗ Không tìm thấy title")
                results_summary.append({
                    "file": file_name,
                    "title": "(None)",
                    "confidence": 0.0,
                    "strategy": "none",
                })

        except Exception as e:
            print(f"  ✗ LỖI: {e}")
            results_summary.append({
                "file": file_name,
                "title": f"ERROR: {e}",
                "confidence": 0.0,
                "strategy": "error",
            })

    # Tổng kết
    print_separator("TỔNG KẾT")
    print(f"  {'File':<40s} {'Confidence':>10s} {'Strategy':<12s} {'Title':<50s}")
    print(f"  {'─' * 40} {'─' * 10} {'─' * 12} {'─' * 50}")
    for r in results_summary:
        print(f"  {r['file']:<40s} "
              f"{r['confidence']:>10.4f} "
              f"{r['strategy']:<12s} "
              f"{r['title']:<50s}")

    # Thống kê
    found = sum(1 for r in results_summary if r["strategy"] != "none" and r["strategy"] != "error")
    total = len(results_summary)
    avg_conf = sum(r["confidence"] for r in results_summary if r["confidence"] > 0) / max(found, 1)
    print(f"\n  Tìm thấy title: {found}/{total}")
    print(f"  Confidence TB:  {avg_conf:.4f}")


if __name__ == "__main__":
    main()
