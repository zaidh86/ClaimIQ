"""Local content-hash cache for extraction results.

Keyed by sha256(model | prompt version | doc type | document text), so any
change to the document, the prompt, or the model is automatically a cache
miss. Files live under .cache/extraction/ (git-ignored); deleting the
directory is the whole invalidation story. Corrupt entries are ignored and
overwritten, never fatal.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from claimiq.config import BASE_DIR

logger = logging.getLogger(__name__)

CACHE_DIR = BASE_DIR / ".cache" / "extraction"


def cache_key(model: str, prompt_version: str, doc_type: str, text: str) -> str:
    payload = "\x1f".join([model, prompt_version, doc_type, text])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get(key: str) -> dict | None:
    path = CACHE_DIR / f"{key}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring unreadable cache entry %s: %s", path.name, exc)
        return None


def put(key: str, payload: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = CACHE_DIR / f"{key}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:  # caching is best-effort, never fatal
        logger.warning("Could not write cache entry: %s", exc)
