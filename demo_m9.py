"""
Demo Milestone 9 -- LLM Enhancement.
Pipeline: M2 -> M3 -> M4 -> M5 -> M6 -> M7 -> M8 -> M9.

Uses StubLLM for demonstration (no real LLM/API configured).
Clearly labels results as "StubLLM simulation".

Run: python demo_m9.py
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
from core.validators.llm_validator import LLMValidator
from infrastructure.nlp.llm_loader import StubLLM, load_llm


def find_sample_pdfs() -> list[str]:
    """Find all sample PDFs."""
    pdf_paths: list[str] = []
    parent_dir = _project_root.parent
    for pdf in parent_dir.glob("*.pdf"):
        pdf_paths.append(str(pdf))
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
    print("\n" + "=" * 110)
    print(title)
    print("=" * 110)


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

    # ── Determine LLM backend ──
    llm = load_llm()
    llm_provider = "real"
    if llm is None:
        print("[INFO] No real LLM configured. Using StubLLM for simulation.")
        print("[INFO] Results marked as 'StubLLM simulation' — NOT real LLM results.\n")
        llm = StubLLM('{"is_valid": true, "confidence": 0.85, "reason": "stub validation (simulated)"}')
        llm_provider = "StubLLM"

    sep(f"DEMO MILESTONE 9: LLM ENHANCEMENT -- {len(pdf_paths)} PDFs  [provider: {llm_provider}]")

    extractor = PDFTextExtractor()
    analyzer = LayoutAnalyzer()
    title_svc = TitleDetectionService()
    author_svc = AuthorDetectionService()
    abstract_svc = AbstractDetectionService()
    cleaning_svc = DataCleaningService()
    validation_engine = ValidationEngine()
    llm_validator = LLMValidator(llm_model=llm)

    results = []

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

            # M8: Rule-based Validation
            rule_report = validation_engine.validate(cleaning_result=cleaning_result)

            # Extract first page text for LLM context
            context = ""
            if doc_data.pages:
                page_texts = []
                for block in doc_data.pages[0].blocks:
                    page_texts.append(block.text)
                context = " ".join(page_texts)[:500]

            # M9: LLM Enhancement
            enhanced_report = llm_validator.enhance(
                rule_report,
                title=cleaning_result.title,
                authors=cleaning_result.authors,
                abstract=cleaning_result.abstract,
                context=context,
            )

            # Display
            print(f"  Title:   {repr(cleaning_result.title)[:70]}" if cleaning_result.title else "  Title:   None")
            print(f"  Authors: {cleaning_result.authors[:3]}")

            # Per-field comparison
            for field_name, rule_fv, llm_fv in [
                ("Title", rule_report.title, enhanced_report.title),
                ("Authors", rule_report.authors, enhanced_report.authors),
                ("Abstract", rule_report.abstract, enhanced_report.abstract),
            ]:
                llm_called = "YES" if llm_fv.llm_called else "no"
                llm_score_str = f"{llm_fv.llm_score:.4f}" if llm_fv.llm_score is not None else "N/A"
                final_score = llm_fv.score

                print(
                    f"  {field_name:<10s} | Rule: {rule_fv.score:.4f} | "
                    f"LLM Called: {llm_called:<3s} | LLM Score: {llm_score_str:>6s} | "
                    f"Final: {final_score:.4f}"
                )

            print(f"\n  Overall:  Rule={rule_report.overall_score:.4f}  "
                  f"→  Enhanced={enhanced_report.overall_score:.4f}  "
                  f"Status={'PASSED' if enhanced_report.passed else 'FAILED'}  "
                  f"LLM Enhanced: {enhanced_report.llm_enhanced}")

            results.append({
                "file": file_name,
                "title_rule": rule_report.title.score,
                "title_llm": enhanced_report.title.llm_score,
                "title_final": enhanced_report.title.score,
                "title_llm_called": enhanced_report.title.llm_called,
                "author_rule": rule_report.authors.score,
                "author_llm": enhanced_report.authors.llm_score,
                "author_final": enhanced_report.authors.score,
                "author_llm_called": enhanced_report.authors.llm_called,
                "abstract_rule": rule_report.abstract.score,
                "abstract_llm": enhanced_report.abstract.llm_score,
                "abstract_final": enhanced_report.abstract.score,
                "abstract_llm_called": enhanced_report.abstract.llm_called,
                "overall_rule": rule_report.overall_score,
                "overall_enhanced": enhanced_report.overall_score,
                "passed": enhanced_report.passed,
                "llm_enhanced": enhanced_report.llm_enhanced,
                "status": "PASSED" if enhanced_report.passed else "FAILED",
            })

        except Exception as e:
            print(f"  [X] ERROR: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                "file": file_name,
                "title_rule": 0, "title_llm": None, "title_final": 0, "title_llm_called": False,
                "author_rule": 0, "author_llm": None, "author_final": 0, "author_llm_called": False,
                "abstract_rule": 0, "abstract_llm": None, "abstract_final": 0, "abstract_llm_called": False,
                "overall_rule": 0, "overall_enhanced": 0,
                "passed": False, "llm_enhanced": False, "status": "ERROR",
            })

    # ── Summary Table ──
    sep("VALIDATION SUMMARY: Rule-based vs Rule+LLM")
    if llm_provider == "StubLLM":
        print("  *** NOTE: LLM results are SIMULATED (StubLLM). Not real LLM. ***\n")

    header = (
        f"  {'PDF':<42s} {'T-Rule':>7s} {'T-LLM':>7s} {'T-Final':>7s} "
        f"{'A-Rule':>7s} {'A-Final':>7s} "
        f"{'Ab-Rule':>7s} {'Ab-Final':>7s} "
        f"{'Overall':>7s} {'Status':<8s}"
    )
    print(header)
    print(f"  {'-'*42} " + " ".join([f"{'-'*7}"] * 8) + f" {'-'*8}")
    for r in results:
        t_llm = f"{r['title_llm']:.4f}" if r['title_llm'] is not None else "  skip"
        print(
            f"  {r['file']:<42s} {r['title_rule']:>7.4f} {t_llm:>7s} {r['title_final']:>7.4f} "
            f"{r['author_rule']:>7.4f} {r['author_final']:>7.4f} "
            f"{r['abstract_rule']:>7.4f} {r['abstract_final']:>7.4f} "
            f"{r['overall_enhanced']:>7.4f} {r['status']:<8s}"
        )

    # ── Statistics ──
    valid = [r for r in results if r["status"] != "ERROR"]
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    llm_enhanced_count = sum(1 for r in results if r["llm_enhanced"])
    llm_calls = sum(
        (1 if r["title_llm_called"] else 0) +
        (1 if r["author_llm_called"] else 0) +
        (1 if r["abstract_llm_called"] else 0)
        for r in results
    )

    print(f"\n  Total PDFs:         {total}")
    print(f"  Passed:             {passed}/{total}")
    print(f"  LLM Enhanced:       {llm_enhanced_count}/{total} PDFs")
    print(f"  LLM Calls Total:    {llm_calls} (across {total * 3} field checks)")

    if valid:
        avg_rule = sum(r["overall_rule"] for r in valid) / len(valid)
        avg_enhanced = sum(r["overall_enhanced"] for r in valid) / len(valid)
        print(f"\n  Avg Overall (Rule):     {avg_rule:.4f}")
        print(f"  Avg Overall (Enhanced): {avg_enhanced:.4f}")
        print(f"  Delta:                  {avg_enhanced - avg_rule:+.4f}")

    # ── Comparison Table: Rule-based only vs Rule+LLM ──
    sep("COMPARISON: Rule-based Only vs Rule+LLM")
    if llm_provider == "StubLLM":
        print("  *** StubLLM simulation — for architecture demo only ***\n")

    if valid:
        rule_title_pass = sum(1 for r in valid if r["title_rule"] >= 0.6)
        enh_title_pass = sum(1 for r in valid if r["title_final"] >= 0.6)
        rule_author_pass = sum(1 for r in valid if r["author_rule"] >= 0.6)
        enh_author_pass = sum(1 for r in valid if r["author_final"] >= 0.6)
        rule_abstract_pass = sum(1 for r in valid if r["abstract_rule"] >= 0.6)
        enh_abstract_pass = sum(1 for r in valid if r["abstract_final"] >= 0.6)
        rule_pass = sum(1 for r in valid if r["overall_rule"] >= 0.6)
        enh_pass = sum(1 for r in valid if r["overall_enhanced"] >= 0.6)
        borderline = sum(1 for r in valid if r["llm_enhanced"])

        print(f"  {'Metric':<25s} {'Rule-based':>12s} {'Rule+LLM':>12s}")
        print(f"  {'-'*25} {'-'*12} {'-'*12}")
        print(f"  {'Valid title':<25s} {rule_title_pass:>12d} {enh_title_pass:>12d}")
        print(f"  {'Valid authors':<25s} {rule_author_pass:>12d} {enh_author_pass:>12d}")
        print(f"  {'Valid abstract':<25s} {rule_abstract_pass:>12d} {enh_abstract_pass:>12d}")
        print(f"  {'Overall passed':<25s} {rule_pass:>12d} {enh_pass:>12d}")
        print(f"  {'Borderline (LLM used)':<25s} {borderline:>12d} {'':>12s}")

    # ── Export ──
    output_path = _project_root / "llm_enhancement_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n  Results exported to: {output_path}")


if __name__ == "__main__":
    main()
