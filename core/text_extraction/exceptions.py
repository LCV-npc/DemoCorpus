"""
core/text_extraction/exceptions.py
Custom exceptions cho module text extraction.
"""


class PDFExtractionError(Exception):
    """Base exception cho tất cả lỗi trong text extraction module."""

    def __init__(self, message: str, file_path: str = ""):
        self.file_path = file_path
        super().__init__(message)


class PDFCorruptedError(PDFExtractionError):
    """PDF bị lỗi cấu trúc — không thể mở hoặc parse."""

    def __init__(self, file_path: str = "", detail: str = ""):
        message = f"Corrupted PDF file: {file_path}"
        if detail:
            message += f" ({detail})"
        super().__init__(message, file_path=file_path)


class PDFEncryptedError(PDFExtractionError):
    """PDF được mã hóa hoặc yêu cầu password."""

    def __init__(self, file_path: str = ""):
        message = f"Encrypted PDF file (password required): {file_path}"
        super().__init__(message, file_path=file_path)


class PDFEmptyError(PDFExtractionError):
    """PDF không có trang nào (page_count == 0)."""

    def __init__(self, file_path: str = ""):
        message = f"Empty PDF file (0 pages): {file_path}"
        super().__init__(message, file_path=file_path)
