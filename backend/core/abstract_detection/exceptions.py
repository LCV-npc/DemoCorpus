"""
core/abstract_detection/exceptions.py
Custom exceptions cho module abstract detection.
"""


class AbstractDetectionError(Exception):
    """Base exception cho tất cả lỗi trong abstract detection module."""

    def __init__(self, message: str, file_path: str = ""):
        self.file_path = file_path
        super().__init__(message)
