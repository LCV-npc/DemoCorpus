"""
tests/test_storage.py
Unit tests cho FileStorage: save, save_from_path, delete, exists.
Milestone 1 — Storage tests.
"""

import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from infrastructure.storage.file_storage import FileStorage


@pytest.fixture
def tmp_storage(tmp_path):
    """Tạo FileStorage với thư mục tạm."""
    storage = FileStorage(base_dir=str(tmp_path / "test_uploads"))
    return storage


@pytest.fixture
def sample_pdf_bytes():
    """Fake PDF bytes (magic bytes + padding)."""
    return b"%PDF-1.4 fake content for testing " + b"x" * 1024


class TestFileStorage:
    """Tests cho FileStorage class."""

    def test_storage_save_and_exists(self, tmp_storage, sample_pdf_bytes):
        """save() lưu file và exists() trả về True."""
        path = tmp_storage.save(sample_pdf_bytes, "paper-001")

        assert os.path.exists(path)
        assert tmp_storage.exists("paper-001") is True

        # Verify content
        with open(path, "rb") as f:
            content = f.read()
        assert content == sample_pdf_bytes

    def test_storage_exists_false(self, tmp_storage):
        """exists() trả về False khi file chưa tồn tại."""
        assert tmp_storage.exists("non-existent") is False

    def test_storage_delete(self, tmp_storage, sample_pdf_bytes):
        """delete() xóa file thành công."""
        path = tmp_storage.save(sample_pdf_bytes, "paper-del")
        assert os.path.exists(path)

        tmp_storage.delete(path)
        assert not os.path.exists(path)
        assert tmp_storage.exists("paper-del") is False

    def test_storage_delete_nonexistent(self, tmp_storage):
        """delete() không raise error khi file không tồn tại."""
        # Should not raise
        tmp_storage.delete("/nonexistent/path.pdf")

    def test_storage_save_from_path(self, tmp_storage, tmp_path, sample_pdf_bytes):
        """save_from_path() copy file từ src_path vào storage."""
        # Tạo file nguồn
        src_file = tmp_path / "source.pdf"
        src_file.write_bytes(sample_pdf_bytes)

        path = tmp_storage.save_from_path(str(src_file), "paper-copy")

        assert os.path.exists(path)
        assert tmp_storage.exists("paper-copy") is True

        # Verify content matches source
        with open(path, "rb") as f:
            content = f.read()
        assert content == sample_pdf_bytes

    def test_storage_save_from_path_not_found(self, tmp_storage):
        """save_from_path() raise FileNotFoundError khi src không tồn tại."""
        with pytest.raises(FileNotFoundError):
            tmp_storage.save_from_path("/nonexistent/file.pdf", "paper-err")

    def test_storage_get_path(self, tmp_storage, sample_pdf_bytes):
        """get_path() trả về path nếu file tồn tại, None nếu không."""
        # File chưa tồn tại
        assert tmp_storage.get_path("paper-gp") is None

        # Save file
        tmp_storage.save(sample_pdf_bytes, "paper-gp")
        path = tmp_storage.get_path("paper-gp")
        assert path is not None
        assert os.path.exists(path)

    def test_storage_creates_directory(self, tmp_path):
        """FileStorage tự tạo directory nếu chưa có."""
        target_dir = tmp_path / "deep" / "nested" / "dir"
        storage = FileStorage(base_dir=str(target_dir))
        assert target_dir.exists()

    def test_storage_overwrite(self, tmp_storage):
        """save() ghi đè file nếu paper_id trùng."""
        content1 = b"%PDF first version" + b"a" * 100
        content2 = b"%PDF second version" + b"b" * 200

        path1 = tmp_storage.save(content1, "paper-ow")
        path2 = tmp_storage.save(content2, "paper-ow")

        assert path1 == path2  # Same path
        with open(path2, "rb") as f:
            assert f.read() == content2  # Content overwritten
