"""
Demo Milestone 5 — Author Detection.
Pipeline: M2 → M3 → M4 → M5.

Chạy: python demo_m5.py
"""

import sys
import json
import logging
from pathlib import Path

_project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(_project_root))

from core.text_extraction.extractor import PDFTextExtractor
from core.layout_analysis.layout_analyzer import LayoutAnalyzer
from core.title_detection.service import TitleDetectionService
from core.author_detection.service import AuthorDetectionService


def find_sample_pdfs() -> list[str]:
    """Tìm tất cả PDF mẫu."""
    pdf_paths: list[str] = []
    parent_dir = _project_root.parent
    for pdf in parent_dir.glob("*.pdf"):
        pdf_paths.append(str(pdf))
    scraped_dir = _project_root / "data" / "scraped_pdfs"
    if scraped_dir.exists():
        for pdf in scraped_dir.rglob("*.pdf"):
            pdf_paths.append(str(pdf))
    return pdf_paths


def sep(title: str):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    pdf_paths = find_sample_pdfs()
    if not pdf_paths:
        print("[LỖI] Không tìm thấy PDF mẫu.")
        return

    sep(f"DEMO MILESTONE 5: AUTHOR DETECTION — {len(pdf_paths)} PDFs")

    extractor = PDFTextExtractor()
    analyzer = LayoutAnalyzer()
    title_svc = TitleDetectionService()
    author_svc = AuthorDetectionService()

    results_summary = []

    for i, pdf_path in enumerate(pdf_paths, start=1):
        file_name = Path(pdf_path).name
        sep(f"[{i}/{len(pdf_paths)}] {file_name}")

        try:
            doc_data = extractor.extract(pdf_path)
            layout_doc = analyzer.analyze(doc_data)
            title_result = title_svc.detect_title(layout_doc)
            author_result = author_svc.detect_authors(layout_doc, title_result)

            print(f"  Title: {title_result.title[:60]!r}" if title_result.title else "  Title: (None)")
            print(f"\n  ═══ AUTHORS ═══")
            if author_result.authors:
                print(f"  Count:      {author_result.count}")
                print(f"  Confidence: {author_result.confidence:.4f}")
                print(f"  Strategy:   {author_result.strategy}")
                for j, a in enumerate(author_result.authors, 1):
                    print(f"  [{j}] {a.name}"
                          + (f" <{a.email}>" if a.email else "")
                          + (f" @ {a.affiliation[:40]}" if a.affiliation else ""))
                print(f"\n  JSON: {json.dumps(author_result.to_dict(), indent=4, ensure_ascii=False)}")
            else:
                print("  ✗ Không tìm thấy tác giả")

            results_summary.append({
                "file": file_name,
                "count": author_result.count,
                "confidence": author_result.confidence,
                "strategy": author_result.strategy,
                "names": ", ".join(author_result.author_names[:3]),
            })

        except Exception as e:
            print(f"  ✗ LỖI: {e}")
            results_summary.append({
                "file": file_name, "count": 0,
                "confidence": 0.0, "strategy": "error", "names": str(e)[:40],
            })

    sep("TỔNG KẾT")
    print(f"  {'File':<35s} {'#':>3s} {'Conf':>7s} {'Strategy':<12s} {'Authors':<50s}")
    print(f"  {'─'*35} {'─'*3} {'─'*7} {'─'*12} {'─'*50}")
    for r in results_summary:
        print(f"  {r['file']:<35s} {r['count']:>3d} "
              f"{r['confidence']:>7.4f} {r['strategy']:<12s} {r['names']:<50s}")

    found = sum(1 for r in results_summary if r["count"] > 0)
    total = len(results_summary)
    avg_count = sum(r["count"] for r in results_summary) / max(total, 1)
    avg_conf = sum(r["confidence"] for r in results_summary if r["confidence"] > 0) / max(found, 1)
    print(f"\n  Tìm thấy authors: {found}/{total} ({found/total*100:.1f}%)")
    print(f"  Số tác giả TB:    {avg_count:.1f}")
    print(f"  Confidence TB:    {avg_conf:.4f}")


if __name__ == "__main__":
    main()
