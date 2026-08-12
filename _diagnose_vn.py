"""
Diagnostic script: kiem tra chi tiet Title, Author, Abstract detection
tren cac bai bao Viet Nam tu scraped_pdfs.

Tap trung vao:
1. Author detection: raw AUTHOR region text vs detected authors
2. Title detection: raw TITLE region text
3. Abstract detection: raw vs cleaned
4. Phat hien bai bao khac bi dinh o dau trang
"""

import sys
import logging
from pathlib import Path

_project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(_project_root))

logging.basicConfig(level=logging.WARNING)

from core.text_extraction.extractor import PDFTextExtractor
from core.layout_analysis.layout_analyzer import LayoutAnalyzer
from core.layout_analysis.layout_model import RegionType
from core.title_detection.service import TitleDetectionService
from core.author_detection.service import AuthorDetectionService
from core.abstract_detection.service import AbstractDetectionService


def main():
    scraped_dir = _project_root / "data" / "scraped_pdfs" / "tapchiyhocvietnam.vn"
    pdfs = sorted(scraped_dir.glob("*.pdf"))[:30]  # test 30 bai

    print(f"Testing {len(pdfs)} Vietnamese PDFs from tapchiyhocvietnam.vn\n")

    extractor = PDFTextExtractor()
    analyzer = LayoutAnalyzer()
    title_svc = TitleDetectionService()
    author_svc = AuthorDetectionService()
    abstract_svc = AbstractDetectionService()

    issues = []

    for i, pdf_path in enumerate(pdfs, 1):
        name = pdf_path.name
        print(f"\n{'='*90}")
        print(f"[{i}/{len(pdfs)}] {name}")
        print(f"{'='*90}")

        try:
            doc_data = extractor.extract(str(pdf_path))
            layout_doc = analyzer.analyze(doc_data)
            title_result = title_svc.detect_title(layout_doc)
            author_result = author_svc.detect_authors(layout_doc, title_result)
            abstract_result = abstract_svc.detect_abstract(doc_data, layout_doc)

            first_page = layout_doc.pages[0] if layout_doc.pages else None
            if not first_page:
                print("  [!] No pages")
                continue

            # --- LAYOUT REGIONS ---
            print(f"\n  LAYOUT REGIONS (page 0):")
            for region in first_page.regions:
                rtype = region.region_type.value
                text_preview = region.text.replace('\n', '\\n')[:100]
                print(f"    [{rtype:12s}] conf={region.confidence:.2f} | {text_preview!r}")

            # --- RAW AUTHOR REGION TEXT ---
            author_regions = first_page.get_regions(RegionType.AUTHOR)
            print(f"\n  RAW AUTHOR REGION TEXT ({len(author_regions)} regions):")
            if author_regions:
                for j, ar in enumerate(author_regions):
                    raw = ar.text
                    print(f"    Region {j}: confidence={ar.confidence:.2f}")
                    for line in raw.split('\n'):
                        if line.strip():
                            print(f"      | {line.strip()}")
            else:
                print("    (no AUTHOR regions found)")

            # --- RAW BLOCKS BETWEEN TITLE AND ABSTRACT ---
            title_regions = first_page.get_regions(RegionType.TITLE)
            abstract_regions = first_page.get_regions(RegionType.ABSTRACT)
            if title_regions:
                title_y_bottom = max(r.bbox[3] for r in title_regions)
                abstract_y_top = abstract_regions[0].bbox[1] if abstract_regions else first_page.height * 0.5
                print(f"\n  BLOCKS BETWEEN TITLE (y={title_y_bottom:.0f}) AND ABSTRACT (y={abstract_y_top:.0f}):")
                for region in first_page.regions:
                    for block in region.blocks:
                        by0 = block.bbox[1]
                        by1 = block.bbox[3]
                        if by0 >= title_y_bottom and by1 <= abstract_y_top:
                            text = block.text.strip().replace('\n', '\\n')
                            rtype = region.region_type.value
                            print(f"    y=[{by0:.0f}-{by1:.0f}] [{rtype:12s}] {text[:120]!r}")

            # --- DETECTED RESULTS ---
            print(f"\n  DETECTED TITLE: {title_result.title!r}" if title_result.title else "\n  DETECTED TITLE: None")
            print(f"  Title strategy: {title_result.strategy}, confidence: {title_result.confidence:.2f}")

            print(f"\n  DETECTED AUTHORS ({author_result.count}):")
            if author_result.authors:
                for a in author_result.authors:
                    print(f"    - {a.name}")
                print(f"  Strategy: {author_result.strategy}, confidence: {author_result.confidence:.2f}")
            else:
                print("    (none)")
                issues.append({
                    "file": name,
                    "issue": "NO_AUTHORS",
                    "raw_author_text": author_regions[0].text[:200] if author_regions else "no region",
                })

            print(f"\n  DETECTED ABSTRACT: {'YES' if abstract_result.found else 'NO'} | method={abstract_result.method} | len={abstract_result.length}")
            if abstract_result.found:
                print(f"    Preview: {abstract_result.text[:120]!r}")

            # --- CHECK FOR "STUCK" CONTENT FROM OTHER PAPER ---
            # Look at blocks in top 5% of page
            header_y = first_page.height * 0.05
            header_blocks = []
            for region in first_page.regions:
                for block in region.blocks:
                    if block.bbox[1] < header_y:
                        header_blocks.append(block)
            if header_blocks:
                print(f"\n  HEADER ZONE (top 5%):")
                for block in header_blocks:
                    text = block.text.strip().replace('\n', '\\n')[:120]
                    print(f"    {text!r}")

        except Exception as e:
            print(f"  [ERROR] {e}")
            import traceback
            traceback.print_exc()

    # --- ISSUE SUMMARY ---
    print(f"\n{'='*90}")
    print(f"ISSUE SUMMARY: {len(issues)} PDFs with problems")
    print(f"{'='*90}")
    no_author = [x for x in issues if x["issue"] == "NO_AUTHORS"]
    print(f"\n  No authors detected: {len(no_author)}/{len(pdfs)}")
    for x in no_author:
        print(f"    - {x['file']}: raw_author_text={x['raw_author_text'][:100]!r}")


if __name__ == "__main__":
    main()
