"""
Demo Milestone 2 — Text Extraction.
Trích xuất text từ PDF và hiển thị cấu trúc dữ liệu.

Chạy: python demo_m2.py
"""
import sys
import json
from pathlib import Path

# Đảm bảo import đúng dù chạy từ đâu
_project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(_project_root))

from core.text_extraction.service import TextExtractionService


def find_sample_pdf() -> str:
    """Tìm file PDF mẫu trong thư mục data/scraped_pdfs."""
    scraped_dir = _project_root / "data" / "scraped_pdfs"
    if scraped_dir.exists():
        for pdf in scraped_dir.rglob("*.pdf"):
            return str(pdf)

    # Fallback: tìm trong thư mục cha
    parent_dir = _project_root.parent
    for pdf in parent_dir.glob("*.pdf"):
        return str(pdf)

    return ""


def main():
    pdf_path = find_sample_pdf()
    if not pdf_path:
        print("[LỖI] Không tìm thấy file PDF mẫu.")
        print(f"  Hãy đặt file PDF vào: {_project_root / 'data' / 'scraped_pdfs'}")
        return

    print(f"Đang phân tích file: {Path(pdf_path).name}")

    # Khởi tạo service và extract
    service = TextExtractionService()
    result = service.extract_document(pdf_path)
    data = result.to_dict()

    print("\n" + "=" * 60)
    print("THỐNG KÊ KẾT QUẢ TRÍCH XUẤT (Milestone 2):")
    print("=" * 60)
    print(f"  Số trang (Pages):      {data['page_count']}")
    print(f"  Tổng số block:         {data['total_blocks']}")
    print(f"  Tổng số span:          {data['total_spans']}")
    print(f"  File digital (không scan): {data['is_born_digital']}")
    print(f"  Thời gian xử lý:      {data['extraction_time_seconds']} giây")

    # In mẫu cấu trúc JSON
    print("\n" + "=" * 60)
    print("CẤU TRÚC JSON (Mẫu từ Trang 1, Block đầu tiên):")
    print("=" * 60)
    if data['pages'] and data['pages'][0]['blocks']:
        sample = {
            "page_number": data['pages'][0]['page_number'],
            "page_width": data['pages'][0]['width'],
            "page_height": data['pages'][0]['height'],
            "first_block": data['pages'][0]['blocks'][0],
        }
        print(json.dumps(sample, indent=2, ensure_ascii=False))

    # Lưu toàn bộ JSON ra file trong project
    out_file = _project_root / "data" / "sample_extraction.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n[✓] Đã lưu toàn bộ kết quả vào: {out_file}")


if __name__ == "__main__":
    main()
