"""
infrastructure/storage/file_storage.py
Quản lý lưu trữ file PDF: save, delete, exists.
"""

import os
import shutil
import logging
from pathlib import Path

from config.settings import settings

logger = logging.getLogger(__name__)


class FileStorage:
    """Quản lý lưu/xóa file PDF trong thư mục uploads."""

    def __init__(self, base_dir: str | None = None):
        self.base_dir = Path(base_dir or settings.UPLOAD_DIR)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"FileStorage initialized: {self.base_dir}")

    def save(self, file_bytes: bytes, paper_id: str) -> str:
        """
        Lưu bytes thành file PDF.

        Returns: absolute path đến file đã lưu.
        """
        file_path = self.base_dir / f"{paper_id}.pdf"
        file_path.write_bytes(file_bytes)
        logger.info(f"Saved {len(file_bytes)} bytes → {file_path}")
        return str(file_path.resolve())

    def save_from_path(self, src_path: str, paper_id: str) -> str:
        """
        Copy file từ src_path vào thư mục storage.

        Returns: absolute path đến file đã copy.
        """
        src = Path(src_path)
        if not src.exists():
            raise FileNotFoundError(f"Source file not found: {src_path}")

        dest_path = self.base_dir / f"{paper_id}.pdf"
        shutil.copy2(str(src), str(dest_path))
        logger.info(f"Copied {src_path} → {dest_path}")
        return str(dest_path.resolve())

    def delete(self, file_path: str) -> None:
        """Xóa file. Không raise error nếu file không tồn tại."""
        p = Path(file_path)
        if p.exists():
            p.unlink()
            logger.info(f"Deleted: {file_path}")
        else:
            logger.warning(f"File not found for deletion: {file_path}")

    def exists(self, paper_id: str) -> bool:
        """Kiểm tra file với paper_id đã tồn tại chưa."""
        file_path = self.base_dir / f"{paper_id}.pdf"
        return file_path.exists()

    def get_path(self, paper_id: str) -> str | None:
        """Trả về path nếu file tồn tại, None nếu không."""
        file_path = self.base_dir / f"{paper_id}.pdf"
        return str(file_path.resolve()) if file_path.exists() else None
