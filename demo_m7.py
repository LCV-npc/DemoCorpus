"""
Demo Milestone 7 -- Data Cleaning & Normalization.
Pipeline: M2 -> M3 -> M4 -> M5 -> M6 -> M7.

Chay: python demo_m7.py
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
from core.data_cleaning.service import DataCleaningService


def find_sample_pdfs() -> list[str]:
    """Tim tat ca PDF mau."""
    pdf_paths: list[str] = []
    parent_dir = _project_root.parent
    for pdf in parent_dir.glob("*.pdf"):
        pdf_paths.append(str(pdf))
    # Limit scraped PDFs
    scraped_dir = _project_root / "data" / "scraped_pdfs"
    if scraped_dir.exists():
        count = 0
        for pdf in scraped_dir.rglob("*.pdf"):
            if count >= 5:
                break
            pdf_paths.append(str(pdf))
            count += 1
    return pdf_paths


def sep(title: str):
    print("\n" + "=" * 90)
    print(title)
    print("=" * 90)


def show_before_after(label: str, before, after):
    """Show before/after comparison."""
    if before == after:
        return
    b_str = repr(before)[:80] if before else "None"
    a_str = repr(after)[:80] if after else "None"
    print(f"    [{label}]")
    print(f"      BEFORE: {b_str}")
    print(f"      AFTER:  {a_str}")


def main():
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    pdf_paths = find_sample_pdfs()
    if not pdf_paths:
        print("[ERROR] No PDF files found.")
        return

    sep(f"DEMO MILESTONE 7: DATA CLEANING -- {len(pdf_paths)} PDFs")

    extractor = PDFTextExtractor()
    analyzer = LayoutAnalyzer()
    title_svc = TitleDetectionService()
    author_svc = AuthorDetectionService()
    abstract_svc = AbstractDetectionService()
    cleaning_svc = DataCleaningService()

    results_summary = []

    for i, pdf_path in enumerate(pdf_paths, start=1):
        file_name = Path(pdf_path).name
        sep(f"[{i}/{len(pdf_paths)}] {file_name}")

        try:
            # Pipeline: M2 -> M3 -> M4 -> M5 -> M6
            doc_data = extractor.extract(pdf_path)
            layout_doc = analyzer.analyze(doc_data)
            title_result = title_svc.detect_title(layout_doc)
            author_result = author_svc.detect_authors(layout_doc, title_result)
            abstract_result = abstract_svc.detect_abstract(doc_data, layout_doc)

            # Raw data from M4/M5/M6
            raw_title = title_result.title
            raw_authors = author_result.author_names
            raw_abstract = abstract_result.text

            # M7: Cleaning
            cleaning_result = cleaning_svc.clean(
                title=raw_title,
                authors=raw_authors,
                abstract=raw_abstract,
            )

            # Display
            print(f"  --- RAW (M4/M5/M6) ---")
            print(f"  Title:    {repr(raw_title)[:70]}" if raw_title else "  Title:    None")
            print(f"  Authors:  {raw_authors[:3]}")
            print(f"  Abstract: {repr(raw_abstract)[:70]}..." if raw_abstract else "  Abstract: None")

            print(f"\n  --- CLEANED (M7) ---")
            print(f"  Title:    {repr(cleaning_result.title)[:70]}" if cleaning_result.title else "  Title:    None")
            print(f"  Authors:  {cleaning_result.authors[:3]}")
            print(f"  Abstract: {repr(cleaning_result.abstract)[:70]}..." if cleaning_result.abstract else "  Abstract: None")

            print(f"\n  --- CHANGES ---")
            if cleaning_result.changes_made:
                for c in cleaning_result.changes_made[:8]:
                    print(f"    - {c}")
            else:
                print("    (no changes)")

            print(f"\n  --- BEFORE/AFTER ---")
            show_before_after("TITLE", raw_title, cleaning_result.title)
            if raw_authors != cleaning_result.authors:
                show_before_after("AUTHORS", raw_authors[:2], cleaning_result.authors[:2])
            if raw_abstract != cleaning_result.abstract:
                show_before_after("ABSTRACT", raw_abstract, cleaning_result.abstract)

            print(f"\n  --- NOISE ---")
            print(f"    Title noise:    score={cleaning_result.title_noise.noise_score:.4f} noisy={cleaning_result.title_noise.is_noisy} flags={cleaning_result.title_noise.flags}")
            print(f"    Author noise:   score={cleaning_result.author_noise.noise_score:.4f} noisy={cleaning_result.author_noise.is_noisy} flags={cleaning_result.author_noise.flags}")
            print(f"    Abstract noise: score={cleaning_result.abstract_noise.noise_score:.4f} noisy={cleaning_result.abstract_noise.is_noisy} flags={cleaning_result.abstract_noise.flags}")
            print(f"    Overall noise:  {cleaning_result.overall_noise_score:.4f}")

            results_summary.append({
                "file": file_name,
                "title_changed": raw_title != cleaning_result.title,
                "authors_changed": raw_authors != cleaning_result.authors,
                "abstract_changed": raw_abstract != cleaning_result.abstract,
                "changes": len(cleaning_result.changes_made),
                "noise": cleaning_result.overall_noise_score,
                "has_noise": cleaning_result.has_noise,
                "status": "OK",
            })

        except Exception as e:
            print(f"  [X] ERROR: {e}")
            import traceback
            traceback.print_exc()
            results_summary.append({
                "file": file_name,
                "title_changed": False,
                "authors_changed": False,
                "abstract_changed": False,
                "changes": 0,
                "noise": 0.0,
                "has_noise": False,
                "status": "ERROR",
            })

    # -- Summary Table --
    sep("SUMMARY TABLE")
    header = (
        f"  {'PDF':<45s} {'Title':<8s} {'Auth':<8s} "
        f"{'Abst':<8s} {'Changes':>8s} {'Noise':>8s} {'Status':<8s}"
    )
    print(header)
    print(f"  {'-'*45} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    for r in results_summary:
        t_ch = "YES" if r["title_changed"] else "-"
        a_ch = "YES" if r["authors_changed"] else "-"
        ab_ch = "YES" if r["abstract_changed"] else "-"
        print(
            f"  {r['file']:<45s} {t_ch:<8s} {a_ch:<8s} "
            f"{ab_ch:<8s} {r['changes']:>8d} {r['noise']:>8.4f} {r['status']:<8s}"
        )

    # -- Stats --
    total = len(results_summary)
    t_changed = sum(1 for r in results_summary if r["title_changed"])
    a_changed = sum(1 for r in results_summary if r["authors_changed"])
    ab_changed = sum(1 for r in results_summary if r["abstract_changed"])
    noisy = sum(1 for r in results_summary if r["has_noise"])
    avg_noise = sum(r["noise"] for r in results_summary) / max(total, 1)
    avg_changes = sum(r["changes"] for r in results_summary) / max(total, 1)

    print(f"\n  Total PDFs:         {total}")
    print(f"  Titles changed:     {t_changed}/{total}")
    print(f"  Authors changed:    {a_changed}/{total}")
    print(f"  Abstracts changed:  {ab_changed}/{total}")
    print(f"  Noisy detected:     {noisy}/{total}")
    print(f"  Avg noise score:    {avg_noise:.4f}")
    print(f"  Avg changes/PDF:    {avg_changes:.1f}")


if __name__ == "__main__":
    main()
