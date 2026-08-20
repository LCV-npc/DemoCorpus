"""
Demo Milestone 8 -- Validation & Scoring.
Pipeline: M2 -> M3 -> M4 -> M5 -> M6 -> M7 -> M8.

Chay: python demo_m8.py
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
from core.validators.validation_engine import ValidationEngine


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
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


def format_issues(issues: list[str], max_show: int = 3) -> str:
    """Format issues list for display."""
    if not issues:
        return "none"
    shown = issues[:max_show]
    result = "; ".join(shown)
    if len(issues) > max_show:
        result += f" (+{len(issues) - max_show} more)"
    return result


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

    sep(f"DEMO MILESTONE 8: VALIDATION & SCORING -- {len(pdf_paths)} PDFs")

    extractor = PDFTextExtractor()
    analyzer = LayoutAnalyzer()
    title_svc = TitleDetectionService()
    author_svc = AuthorDetectionService()
    abstract_svc = AbstractDetectionService()
    cleaning_svc = DataCleaningService()
    validation_engine = ValidationEngine()

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

            # M7: Cleaning
            cleaning_result = cleaning_svc.clean(
                title=title_result.title,
                authors=author_result.author_names,
                abstract=abstract_result.text,
            )

            # M8: Validation & Scoring
            report = validation_engine.validate(cleaning_result=cleaning_result)

            # Display cleaned data
            print(f"  --- CLEANED DATA (M7) ---")
            print(f"  Title:    {repr(cleaning_result.title)[:70]}" if cleaning_result.title else "  Title:    None")
            print(f"  Authors:  {cleaning_result.authors[:3]}")
            print(f"  Abstract: {repr(cleaning_result.abstract)[:70]}..." if cleaning_result.abstract else "  Abstract: None")

            # Display validation results
            print(f"\n  --- VALIDATION (M8) ---")
            print(f"  Title Score:    {report.title.score:.4f}  passed={report.title.passed}")
            if report.title.issues:
                print(f"    Issues:   {format_issues(report.title.issues)}")
            if report.title.warnings:
                print(f"    Warnings: {format_issues(report.title.warnings)}")

            print(f"  Author Score:   {report.authors.score:.4f}  passed={report.authors.passed}")
            if report.authors.issues:
                print(f"    Issues:   {format_issues(report.authors.issues)}")
            if report.authors.warnings:
                print(f"    Warnings: {format_issues(report.authors.warnings)}")

            print(f"  Abstract Score: {report.abstract.score:.4f}  passed={report.abstract.passed}")
            if report.abstract.issues:
                print(f"    Issues:   {format_issues(report.abstract.issues)}")
            if report.abstract.warnings:
                print(f"    Warnings: {format_issues(report.abstract.warnings)}")

            print(f"\n  Overall Score:  {report.overall_score:.4f}")
            print(f"  Status:         {'PASSED' if report.passed else 'FAILED'}")

            # Display extraction confidence vs validation score
            print(f"\n  --- CONFIDENCE vs VALIDATION ---")
            print(f"  Title Extraction Confidence:  {title_result.confidence:.4f}")
            print(f"  Title Validation Score:       {report.title.score:.4f}")
            print(f"  Author Extraction Confidence: {author_result.confidence:.4f}")
            print(f"  Author Validation Score:      {report.authors.score:.4f}")
            print(f"  Abstract Extraction Confidence: {abstract_result.confidence:.4f}")
            print(f"  Abstract Validation Score:      {report.abstract.score:.4f}")

            results_summary.append({
                "file": file_name,
                "title_score": report.title.score,
                "author_score": report.authors.score,
                "abstract_score": report.abstract.score,
                "overall": report.overall_score,
                "passed": report.passed,
                "title_issues": len(report.title.issues),
                "author_issues": len(report.authors.issues),
                "abstract_issues": len(report.abstract.issues),
                "status": "PASSED" if report.passed else "FAILED",
            })

        except Exception as e:
            print(f"  [X] ERROR: {e}")
            import traceback
            traceback.print_exc()
            results_summary.append({
                "file": file_name,
                "title_score": 0.0,
                "author_score": 0.0,
                "abstract_score": 0.0,
                "overall": 0.0,
                "passed": False,
                "title_issues": -1,
                "author_issues": -1,
                "abstract_issues": -1,
                "status": "ERROR",
            })

    # ── Summary Table ──
    sep("VALIDATION SUMMARY TABLE")
    header = (
        f"  {'PDF':<45s} {'Title':>8s} {'Author':>8s} "
        f"{'Abstract':>8s} {'Overall':>8s} {'Status':<8s}"
    )
    print(header)
    print(f"  {'-'*45} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    for r in results_summary:
        print(
            f"  {r['file']:<45s} {r['title_score']:>8.4f} {r['author_score']:>8.4f} "
            f"{r['abstract_score']:>8.4f} {r['overall']:>8.4f} {r['status']:<8s}"
        )

    # ── Statistics ──
    total = len(results_summary)
    passed_count = sum(1 for r in results_summary if r["passed"])
    failed_count = sum(1 for r in results_summary if not r["passed"] and r["status"] != "ERROR")
    error_count = sum(1 for r in results_summary if r["status"] == "ERROR")

    valid_results = [r for r in results_summary if r["status"] != "ERROR"]
    avg_title = sum(r["title_score"] for r in valid_results) / max(len(valid_results), 1)
    avg_author = sum(r["author_score"] for r in valid_results) / max(len(valid_results), 1)
    avg_abstract = sum(r["abstract_score"] for r in valid_results) / max(len(valid_results), 1)
    avg_overall = sum(r["overall"] for r in valid_results) / max(len(valid_results), 1)

    print(f"\n  Total PDFs:       {total}")
    print(f"  Passed:           {passed_count}/{total}")
    print(f"  Failed:           {failed_count}/{total}")
    print(f"  Errors:           {error_count}/{total}")
    print(f"\n  Avg Title Score:    {avg_title:.4f}")
    print(f"  Avg Author Score:   {avg_author:.4f}")
    print(f"  Avg Abstract Score: {avg_abstract:.4f}")
    print(f"  Avg Overall Score:  {avg_overall:.4f}")

    # ── Export JSON ──
    print(f"\n  Exporting detailed results to validation_results.json...")
    output_path = _project_root / "validation_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results_summary, f, indent=2, ensure_ascii=False)
    print(f"  Saved to: {output_path}")


if __name__ == "__main__":
    main()
