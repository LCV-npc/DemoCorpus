"""
infrastructure/nlp/llm_loader.py
LLM model loading utilities (Milestone 9).

Provides:
- TransformersLLM: HuggingFace transformers model wrapper for local inference.
- ApiLLM: OpenAI-compatible API wrapper.
- StubLLM: Deterministic stub for unit testing.
- load_llm(): Factory function — loads best available LLM backend.

All classes implement the same interface:
    generate(prompt: str) -> str

Pattern follows ner_model_loader.py.
"""

from __future__ import annotations

import json
import logging

from config.constants import LLM_API_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


class TransformersLLM:
    """
    Local LLM using HuggingFace transformers pipeline.

    Wraps `transformers.pipeline("text-generation", ...)` into
    the `generate(prompt) -> str` interface.
    """

    def __init__(self, model_path: str, max_new_tokens: int = 150):
        """
        Load text-generation pipeline.

        Args:
            model_path: Path or HuggingFace model ID.
            max_new_tokens: Maximum tokens to generate.
        """
        try:
            from transformers import pipeline
            self._pipeline = pipeline(
                "text-generation",
                model=model_path,
                max_new_tokens=max_new_tokens,
            )
            self._model_path = model_path
            self._max_new_tokens = max_new_tokens
            logger.info(f"TransformersLLM loaded: {model_path}")
        except Exception as e:
            logger.error(f"Failed to load LLM model '{model_path}': {e}")
            raise

    def generate(self, prompt: str) -> str:
        """
        Generate text from prompt.

        Args:
            prompt: Input prompt.

        Returns:
            Generated text (excluding prompt).
        """
        if not prompt or not prompt.strip():
            return ""

        try:
            results = self._pipeline(prompt)
            if results and isinstance(results, list) and len(results) > 0:
                generated = results[0].get("generated_text", "")
                # Remove the prompt from the output (some models include it)
                if generated.startswith(prompt):
                    generated = generated[len(prompt):].strip()
                return generated
            return ""
        except Exception as e:
            logger.error(f"LLM generation error: {e}")
            return ""


class ApiLLM:
    """
    OpenAI-compatible API wrapper.

    Uses urllib (stdlib) to avoid external dependencies.
    """

    def __init__(
        self,
        api_url: str,
        api_key: str,
        model: str = "gpt-3.5-turbo",
        timeout: int = LLM_API_TIMEOUT_SECONDS,
    ):
        """
        Initialize API client.

        Args:
            api_url: API endpoint URL (e.g., "https://api.openai.com/v1/chat/completions").
            api_key: API key (NOT logged).
            model: Model name.
            timeout: Request timeout in seconds.
        """
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        logger.info(f"ApiLLM initialized: url={api_url}, model={model}")

    def generate(self, prompt: str) -> str:
        """
        Generate text via OpenAI-compatible API.

        Args:
            prompt: Input prompt.

        Returns:
            Generated text. Empty string on error.
        """
        if not prompt or not prompt.strip():
            return ""

        import urllib.request
        import urllib.error

        # Build chat completion request
        payload = json.dumps({
            "model": self._model,
            "messages": [
                {"role": "system", "content": "You are a scientific metadata validator. Return ONLY valid JSON."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "max_tokens": 200,
        }).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        # Determine endpoint
        url = self._api_url
        if not url.endswith("/chat/completions"):
            url = url.rstrip("/") + "/chat/completions"

        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

        # Retry logic: 3 attempts with exponential backoff
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as response:
                    raw = response.read().decode("utf-8")
                    data = json.loads(raw)
                    choices = data.get("choices", [])
                    if choices:
                        return choices[0].get("message", {}).get("content", "")
                    return ""
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    wait = 2 ** attempt  # 2s, 4s
                    logger.warning(
                        f"API HTTP {e.code}, retry {attempt}/{max_retries} in {wait}s"
                    )
                    import time
                    time.sleep(wait)
                    continue
                logger.warning(f"API HTTP error {e.code}: {e.reason}")
                return ""
            except urllib.error.URLError as e:
                logger.warning(f"API URL error: {e.reason}")
                return ""
            except TimeoutError:
                if attempt < max_retries:
                    logger.warning(
                        f"API timeout, retry {attempt}/{max_retries}"
                    )
                    continue
                logger.warning(f"API timeout ({self._timeout}s) after {max_retries} attempts")
                return ""
            except Exception as e:
                logger.error(f"API unexpected error: {e}")
                return ""

        return ""


class StubLLM:
    """
    Deterministic stub for testing.

    Returns a configurable JSON response for every prompt.
    Tracks call count for test assertions.
    """

    def __init__(
        self,
        response: str = '{"is_valid": true, "confidence": 0.85, "reason": "stub validation"}',
    ):
        """
        Initialize stub.

        Args:
            response: JSON string returned for every generate() call.
        """
        self._response = response
        self.call_count: int = 0
        self.last_prompt: str = ""
        logger.info("StubLLM initialized (test mode)")

    def generate(self, prompt: str) -> str:
        """
        Return preconfigured response.

        Args:
            prompt: Input prompt (stored for assertions).

        Returns:
            Configured response string.
        """
        self.call_count += 1
        self.last_prompt = prompt
        return self._response


def load_llm(
    model_path: str = "",
    api_url: str = "",
    api_key: str = "",
    api_model: str = "",
) -> TransformersLLM | ApiLLM | None:
    """
    Factory function: load best available LLM backend.

    Priority:
    1. Local TransformersLLM (if model_path provided and transformers available)
    2. ApiLLM (if api_url and api_key provided)
    3. None (no LLM available)

    Args:
        model_path: Path or HuggingFace model ID for local model.
        api_url: OpenAI-compatible API URL.
        api_key: API key.
        If any are empty, reads from settings.

    Returns:
        LLM instance or None if unavailable.
    """
    # Read from settings if not provided
    if not model_path or not api_url or not api_key:
        try:
            from config.settings import settings
            if not model_path:
                model_path = settings.LLM_MODEL_PATH
            # Gemini is an OpenAI-compatible API but must use a Gemini model
            # name and endpoint. Prefer it whenever its key is configured.
            if settings.GEMINI_API_KEY:
                if not api_url:
                    api_url = settings.GEMINI_API_URL
                if not api_key:
                    api_key = settings.GEMINI_API_KEY
                if not api_model:
                    api_model = settings.GEMINI_MODEL
            else:
                if not api_url:
                    api_url = settings.OPENAI_API_URL
                if not api_key:
                    api_key = settings.OPENAI_API_KEY
                if not api_model:
                    api_model = settings.OPENAI_MODEL
        except Exception:
            pass

    # Strategy 1: Local model
    if model_path:
        try:
            import transformers  # noqa: F401 — check availability
            return TransformersLLM(model_path)
        except ImportError:
            logger.info("transformers not installed — local LLM unavailable")
        except Exception as e:
            logger.warning(f"Failed to load local LLM: {e}")

    # Strategy 2: API
    if api_url and api_key:
        try:
            return ApiLLM(
                api_url=api_url,
                api_key=api_key,
                model=api_model or "gpt-3.5-turbo",
            )
        except Exception as e:
            logger.warning(f"Failed to initialize API LLM: {e}")

    # Strategy 3: No LLM
    logger.info("No LLM backend available — LLM enhancement will be skipped")
    return None
