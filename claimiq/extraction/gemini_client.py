"""Thin, isolated Gemini client.

The only module that talks to the Gemini API. Everything else works with
validated pydantic models, so a missing key, network failure, or malformed
model response surfaces as one of three typed errors — never a crash and never
a half-parsed payload leaking onward:

- GeminiUnavailableError: no API key / SDK missing (configuration problem)
- GeminiRequestError:     the API call itself failed after a retry
- GeminiResponseError:    the model's output could not be validated after a
                          single repair attempt
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Callable, TypeVar

from pydantic import BaseModel, ValidationError

from claimiq.config import Settings, settings as default_settings

logger = logging.getLogger(__name__)

# The SDK warns on every response from thinking models ("non-text parts:
# ['thought_signature']") while still returning the full text — benign but
# noisy, so keep the SDK's loggers at ERROR. Real failures raise exceptions.
logging.getLogger("google_genai").setLevel(logging.ERROR)

T = TypeVar("T")

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class GeminiError(Exception):
    """Base class for all Gemini-layer failures."""


class GeminiUnavailableError(GeminiError):
    pass


class GeminiRequestError(GeminiError):
    pass


class GeminiResponseError(GeminiError):
    pass


def strip_code_fences(text: str) -> str:
    """Remove markdown ```json fences some models wrap around JSON."""
    return _FENCE_RE.sub("", text.strip())


class GeminiClient:
    def __init__(self, config: Settings | None = None) -> None:
        self._config = config or default_settings
        self._client = None  # created lazily on first use

    @property
    def model(self) -> str:
        return self._config.gemini_model

    @property
    def available(self) -> bool:
        return self._config.gemini_configured

    def _ensure_client(self):
        if not self.available:
            raise GeminiUnavailableError(
                "GEMINI_API_KEY is not configured. Set it in the environment or in "
                "a .env file to enable evidence extraction."
            )
        if self._client is None:
            try:
                from google import genai
                from google.genai import types as genai_types
            except ImportError as exc:
                raise GeminiUnavailableError(
                    "The google-genai package is not installed "
                    "(pip install -r requirements.txt)."
                ) from exc
            self._client = genai.Client(
                api_key=self._config.gemini_api_key,
                http_options=genai_types.HttpOptions(
                    timeout=self._config.gemini_timeout_seconds * 1000
                ),
            )
        return self._client

    def _call_model(self, prompt: str, response_schema: type[BaseModel]) -> str:
        """One raw structured-output call. Returns the response text."""
        from google.genai import types as genai_types

        client = self._ensure_client()
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            # No sampling overrides (temperature etc.): newer Gemini models
            # restrict or ignore them, and structured output + validation
            # already constrain the response.
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        )
        # Join text parts directly: thinking models attach non-text parts
        # (e.g. thought signatures) that make the `.text` accessor warn.
        text = ""
        try:
            candidates = response.candidates or []
            if candidates and candidates[0].content and candidates[0].content.parts:
                text = "".join(
                    part.text
                    for part in candidates[0].content.parts
                    if getattr(part, "text", None)
                )
        except (AttributeError, IndexError):
            text = ""
        if not text:
            text = response.text or ""
        if not text:
            raise GeminiResponseError("Gemini returned an empty response")
        return text

    def embed(
        self, texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT"
    ) -> list[list[float]]:
        """Embed texts with the configured Gemini embedding model.

        Returns one vector per input text; validates that all vectors share one
        non-zero dimension. One retry on transient failure, then typed errors.
        """
        if not texts:
            return []
        client = self._ensure_client()
        from google.genai import types as genai_types

        last_exc: Exception | None = None
        for attempt in (1, 2):
            started = time.monotonic()
            try:
                response = client.models.embed_content(
                    model=self._config.gemini_embedding_model,
                    contents=list(texts),
                    config=genai_types.EmbedContentConfig(task_type=task_type),
                )
                vectors = [list(e.values) for e in (response.embeddings or [])]
                if len(vectors) != len(texts):
                    raise GeminiResponseError(
                        f"expected {len(texts)} embeddings, got {len(vectors)}"
                    )
                dims = {len(v) for v in vectors}
                if len(dims) != 1 or 0 in dims:
                    raise GeminiResponseError(
                        f"inconsistent embedding dimensions: {sorted(dims)}"
                    )
                logger.info(
                    "embedded %d text(s) (%dd) in %.1fs",
                    len(vectors), dims.pop(), time.monotonic() - started,
                )
                return vectors
            except GeminiError:
                raise
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "embedding request failed (attempt %d): %s: %s",
                    attempt, type(exc).__name__, exc,
                )
        raise GeminiRequestError(
            f"Embedding request failed after retry: "
            f"{type(last_exc).__name__}: {last_exc}"
        )

    def generate_validated(
        self,
        prompt: str,
        response_schema: type[BaseModel],
        parse: Callable[[str], T],
        context: str = "",
    ) -> T:
        """Call Gemini and validate its output via `parse`.

        `parse` receives the raw response text and must return the validated
        result or raise (ValidationError / json errors). One transient retry
        for request failures; one repair attempt for invalid output, where the
        validation error is appended to the prompt.
        """
        attempt_prompt = prompt
        request_failures = 0
        last_validation_error: str | None = None

        for attempt in (1, 2):
            started = time.monotonic()
            try:
                raw = self._call_model(attempt_prompt, response_schema)
            except GeminiError:
                raise
            except Exception as exc:  # SDK/network errors of any flavour
                request_failures += 1
                logger.warning(
                    "Gemini request failed (%s, attempt %d): %s: %s",
                    context, attempt, type(exc).__name__, exc,
                )
                if request_failures >= 2:
                    raise GeminiRequestError(
                        f"Gemini request failed after retry: {type(exc).__name__}: {exc}"
                    ) from exc
                continue

            elapsed = time.monotonic() - started
            try:
                result = parse(strip_code_fences(raw))
            except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                last_validation_error = str(exc)[:800]
                logger.warning(
                    "Gemini response failed validation (%s, attempt %d): %s",
                    context, attempt, last_validation_error[:200],
                )
                # Single repair attempt: same task, plus what was wrong.
                attempt_prompt = (
                    f"{prompt}\n\nYour previous response was invalid and was "
                    f"rejected by schema validation with this error:\n"
                    f"{last_validation_error}\n"
                    f"Return corrected JSON that satisfies the schema. "
                    f"Use null for anything the document does not state."
                )
                continue

            logger.info("Gemini extraction ok (%s) in %.1fs", context, elapsed)
            return result

        raise GeminiResponseError(
            f"Gemini output failed validation after repair attempt "
            f"({context}): {last_validation_error}"
        )
