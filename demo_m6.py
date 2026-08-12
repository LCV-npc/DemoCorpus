"""
Demo Milestone 6 -- Abstract Detection.
Pipeline: M2 -> M3 -> M4 -> M5 -> M6.

Chay: python demo_m6.py
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
from core.abstract_detection.service import AbstractDetectionService


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
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


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

    sep(f"DEMO MILESTONE 6: ABSTRACT DETECTION — {len(pdf_paths)} PDFs")

    extractor = PDFTextExtractor()
    analyzer = LayoutAnalyzer()
    title_svc = TitleDetectionService()
    author_svc = AuthorDetectionService()
    abstract_svc = AbstractDetectionService()

    results_summary = []

    for i, pdf_path in enumerate(pdf_paths, start=1):
        file_name = Path(pdf_path).name
        sep(f"[{i}/{len(pdf_paths)}] {file_name}")

        try:
            # Pipeline: M2 → M3 → M4 → M5 → M6
            doc_data = extractor.extract(pdf_path)
            layout_doc = analyzer.analyze(doc_data)
            title_result = title_svc.detect_title(layout_doc)
            author_result = author_svc.detect_authors(layout_doc, title_result)
            abstract_result = abstract_svc.detect_abstract(doc_data, layout_doc)

            # Display results
            print(f"  Title:   {title_result.title[:60]!r}" if title_result.title else "  Title:   (None)")
            print(f"  Authors: {', '.join(author_result.author_names[:3])}" if author_result.authors else "  Authors: (None)")

            print(f"\n  === ABSTRACT ===")
            if abstract_result.found:
                print(f"  Method:     {abstract_result.method}")
                print(f"  Confidence: {abstract_result.confidence:.4f}")
                print(f"  Length:     {abstract_result.length} chars")
                print(f"  Pages:      [{abstract_result.start_page}-{abstract_result.end_page}]")
                print(f"  Flags:      {abstract_result.flags}")
                # Preview: first 200 chars
                preview = abstract_result.text[:200]
                if len(abstract_result.text) > 200:
                    preview += "..."
                print(f"  Preview:    {preview!r}")
                print(f"\n  JSON:\n{json.dumps(abstract_result.to_dict(), indent=4, ensure_ascii=False)[:1000]}")
            else:
                print("  [X] Khong tim thay abstract")

            results_summary.append({
                "file": file_name,
                "method": abstract_result.method,
                "found": abstract_result.found,
                "length": abstract_result.length,
                "confidence": abstract_result.confidence,
                "flags": ", ".join(abstract_result.flags) if abstract_result.flags else "",
                "status": "OK" if abstract_result.found else "MISS",
            })

        except Exception as e:
            print(f"  [X] LOI: {e}")
            import traceback
            traceback.print_exc()
            results_summary.append({
                "file": file_name,
                "method": "error",
                "found": False,
                "length": 0,
                "confidence": 0.0,
                "flags": str(e)[:40],
                "status": "ERROR",
            })

    # -- Summary Table --
    sep("BANG KET QUA ABSTRACT DETECTION")
    header = (
        f"  {'PDF':<42s} {'Method':<10s} {'Found':<8s} "
        f"{'Length':>7s} {'Flags':<25s} {'Status':<10s}"
    )
    print(header)
    print(f"  {'-'*42} {'-'*10} {'-'*8} {'-'*7} {'-'*25} {'-'*10}")
    for r in results_summary:
        print(
            f"  {r['file']:<42s} {r['method']:<10s} "
            f"{'Yes' if r['found'] else 'No':<8s} "
            f"{r['length']:>7d} {r['flags']:<25s} {r['status']:<10s}"
        )

    # -- Statistics --
    found = sum(1 for r in results_summary if r["found"])
    total = len(results_summary)
    keyword_count = sum(1 for r in results_summary if r["method"] == "keyword")
    zone_count = sum(1 for r in results_summary if r["method"] == "zone")
    avg_length = sum(r["length"] for r in results_summary if r["found"]) / max(found, 1)
    avg_conf = sum(r["confidence"] for r in results_summary if r["found"]) / max(found, 1)

    print(f"\n  Abstract found:     {found}/{total} ({found/total*100:.1f}%)")
    print(f"  Keyword anchoring:  {keyword_count}")
    print(f"  Zone fallback:      {zone_count}")
    print(f"  Avg length:         {avg_length:.0f} chars")
    print(f"  Avg confidence:     {avg_conf:.4f}")


if __name__ == "__main__":
    main()
