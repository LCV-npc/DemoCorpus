"""
infrastructure/nlp/ner_model_loader.py
NER model loading utilities.

Provides:
- TransformersNERModel: HuggingFace transformers pipeline wrapper.
- load_ner_model(): Factory function — loads model if available, else None.

TransformersNERModel implements the NEREngine protocol from
core/author_detection/ner_engine.py.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class TransformersNERModel:
    """
    NER model sử dụng HuggingFace transformers pipeline.

    Wraps `transformers.pipeline("ner", ...)` thành interface
    tương thích với NEREngine protocol.
    """

    def __init__(self, model_path: str, aggregation_strategy: str = "simple"):
        """
        Load NER pipeline.

        Args:
            model_path: Path hoặc HuggingFace model ID.
            aggregation_strategy: "simple", "first", "average", "max".
        """
        try:
            from transformers import pipeline
            self._pipeline = pipeline(
                "ner",
                model=model_path,
                aggregation_strategy=aggregation_strategy,
            )
            self._model_path = model_path
            logger.info(f"TransformersNERModel loaded: {model_path}")
        except Exception as e:
            logger.error(f"Failed to load NER model '{model_path}': {e}")
            raise

    def predict(self, text: str) -> list[dict]:
        """
        Chạy NER prediction.

        Args:
            text: Text cần phân tích.

        Returns:
            List entities: [{"text": ..., "label": ..., "score": ...}]
        """
        if not text or not text.strip():
            return []

        try:
            raw_results = self._pipeline(text)
            entities: list[dict] = []
            for r in raw_results:
                entities.append({
                    "text": r.get("word", "").strip(),
                    "label": r.get("entity_group", r.get("entity", "UNKNOWN")),
                    "score": round(r.get("score", 0.0), 4),
                })
            return entities
        except Exception as e:
            logger.error(f"NER prediction error: {e}")
            return []

    def extract_persons(self, text: str) -> list[str]:
        """
        Trích xuất PERSON entities.

        Args:
            text: Text cần phân tích.

        Returns:
            Danh sách tên người (PERSON/PER labels).
        """
        entities = self.predict(text)
        persons: list[str] = []
        for ent in entities:
            label = ent.get("label", "").upper()
            if label in ("PERSON", "PER", "B-PER", "I-PER"):
                name = ent.get("text", "").strip()
                if name:
                    persons.append(name)
        return persons


def load_ner_model(model_path: str = "") -> TransformersNERModel | None:
    """
    Factory function: load NER model nếu có thể.

    Kiểm tra:
    1. model_path không rỗng
    2. transformers package available
    3. Model load thành công

    Args:
        model_path: Path hoặc HuggingFace model ID.
                    Nếu rỗng, đọc từ settings.NER_MODEL_PATH.

    Returns:
        TransformersNERModel nếu thành công, None nếu không.
    """
    # Đọc từ settings nếu không truyền
    if not model_path:
        try:
            from config.settings import settings
            model_path = settings.NER_MODEL_PATH
        except Exception:
            pass

    if not model_path:
        logger.info("NER model path not configured — skipping NER")
        return None

    try:
        import transformers  # noqa: F401 — check availability
    except ImportError:
        logger.info("transformers not installed — NER unavailable")
        return None

    try:
        return TransformersNERModel(model_path)
    except Exception as e:
        logger.warning(f"Failed to load NER model: {e}")
        return None
