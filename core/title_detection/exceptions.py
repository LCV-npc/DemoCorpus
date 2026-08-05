"""
core/title_detection/exceptions.py
Custom exceptions cho module title detection.
"""


class TitleDetectionError(Exception):
    """Base exception cho tất cả lỗi trong title detection module."""

    def __init__(self, message: str, file_path: str = ""):
        self.file_path = file_path
        super().__init__(message)
