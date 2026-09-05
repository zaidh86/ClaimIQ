"""Local content-hash cache for extraction results.

Keyed by sha256(model | prompt version | doc type | document text), so any
change to the document, the prompt, or the model is automatically a cache
miss.

Two locations share that one key format:

- CACHE_DIR (.cache/extraction/, git-ignored) is the writable runtime cache.
  Live extractions are written here; deleting the directory is the whole
  invalidation story.
- SEED_DIR (claimiq/data/extraction_seed/, committed) is a read-only baseline
  of validated extractions for the shipped sample claims, so a fresh clone
  demos quickly without re-extracting every document. It is never written to
  at runtime.

Runtime entries win over seeded ones. Corrupt entries are ignored and
overwritten, never fatal. The caller re-validates and re-verifies whatever
comes back, so neither location is trusted on its word.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Literal, NamedTuple

from claimiq.config import BASE_DIR, PACKAGE_DIR

logger = logging.getLogger(__name__)

CACHE_DIR = BASE_DIR / ".cache" / "extraction"
SEED_DIR = PACKAGE_DIR / "data" / "extraction_seed"

CacheSource = Literal["runtime_cache", "seed_cache"]


class CacheHit(NamedTuple):
    payload: dict
    source: CacheSource


def cache_key(model: str, prompt_version: str, doc_type: str, text: str) -> str:
    payload = "\x1f".join([model, prompt_version, doc_type, text])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring unreadable cache entry %s: %s", path.name, exc)
        return None
    if not isinstance(payload, dict):
        logger.warning("Ignoring malformed cache entry %s: not an object", path.name)
        return None
    return payload


def lookup(key: str) -> CacheHit | None:
    """Find an entry, preferring the writable runtime cache over the seed."""
    payload = _read(CACHE_DIR / f"{key}.json")
    if payload is not None:
        return CacheHit(payload, "runtime_cache")
    payload = _read(SEED_DIR / f"{key}.json")
    if payload is not None:
        return CacheHit(payload, "seed_cache")
    return None


def get(key: str) -> dict | None:
    """Payload for a key, or None. Source-agnostic convenience wrapper."""
    hit = lookup(key)
    return hit.payload if hit else None


def put(key: str, payload: dict) -> None:
    """Write to the runtime cache only — the seed is read-only at runtime."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = CACHE_DIR / f"{key}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:  # caching is best-effort, never fatal
        logger.warning("Could not write cache entry: %s", exc)
