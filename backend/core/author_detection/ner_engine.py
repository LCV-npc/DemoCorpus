"""
core/author_detection/ner_engine.py
NER Engine — interface cho Named Entity Recognition.

Cung cấp:
- NEREngine protocol (typing.Protocol): interface thống nhất
- StubNEREngine: implementation rỗng (luôn trả về [])

NER model thật (TransformersNERModel) nằm ở infrastructure/nlp/ner_model_loader.py
và được inject vào AuthorDetector qua constructor.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class NEREngine(Protocol):
    """
    Protocol cho NER engine.

    Bất kỳ class nào implement `predict()` và `extract_persons()`
    đều có thể được dùng làm NER engine.
    """

    def predict(self, text: str) -> list[dict]:
        """
        Chạy NER prediction trên text.

        Args:
            text: Text cần phân tích.

        Returns:
            Danh sách entities, mỗi entity là dict với keys:
            - "text": str — text của entity
            - "label": str — nhãn (PERSON, ORGANIZATION, ...)
            - "score": float — confidence score
        """
        ...

    def extract_persons(self, text: str) -> list[str]:
        """
        Trích xuất chỉ PERSON entities từ text.

        Args:
            text: Text cần phân tích.

        Returns:
            Danh sách tên người.
        """
        ...


class StubNEREngine:
    """
    Stub NER engine — luôn trả về danh sách rỗng.

    Dùng khi:
    - Không có NER model (transformers chưa install)
    - Testing
    - Chỉ muốn dùng rule-based detection
    """

    def predict(self, text: str) -> list[dict]:
        """Luôn trả về []."""
        return []

    def extract_persons(self, text: str) -> list[str]:
        """Luôn trả về []."""
        return []
