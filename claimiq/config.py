"""Application configuration.

All environment handling lives here. A minimal `.env` loader is included so the
judge can drop a `GEMINI_API_KEY` into a `.env` file without extra tooling.
The application must always start, even when no API key is configured —
Gemini-dependent features degrade gracefully instead of crashing at boot.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "web" / "static"
DATA_DIR = BASE_DIR / "data"

DEFAULT_PORT = 8000


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE pairs from a .env file without overriding real env vars.

    Tolerant of how Windows tools actually write these files: a UTF-8 BOM
    (PowerShell `>` redirection), UTF-16 encoding (older Out-File defaults),
    and bash-style `export KEY=value` lines.
    """
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8-sig")  # strips a UTF-8 BOM if present
    except UnicodeDecodeError:
        try:
            text = path.read_text(encoding="utf-16")
        except (OSError, UnicodeError) as exc:
            logger.warning("Could not decode %s: %s", path, exc)
            return
    except OSError as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return
    for raw in text.splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r — falling back to %d", name, raw, default)
        return default


DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
DEFAULT_EMBEDDING_MODEL = "gemini-embedding-001"


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    gemini_api_key: str
    gemini_model: str
    gemini_embedding_model: str
    gemini_timeout_seconds: int
    log_level: str

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv(BASE_DIR / ".env")
        return cls(
            host=os.environ.get("HOST", "0.0.0.0").strip() or "0.0.0.0",
            port=_int_env("PORT", DEFAULT_PORT),
            gemini_api_key=os.environ.get("GEMINI_API_KEY", "").strip(),
            gemini_model=os.environ.get("GEMINI_MODEL", "").strip()
            or DEFAULT_GEMINI_MODEL,
            gemini_embedding_model=os.environ.get("GEMINI_EMBEDDING_MODEL", "").strip()
            or DEFAULT_EMBEDDING_MODEL,
            gemini_timeout_seconds=_int_env("GEMINI_TIMEOUT_SECONDS", 45),
            log_level=os.environ.get("LOG_LEVEL", "info").strip().lower() or "info",
        )


settings = Settings.from_env()
