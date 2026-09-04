"""API routes.

Phase 1 exposes only the health endpoint. Claim-review endpoints are added in
later phases as their underlying modules (data, extraction, engine, retrieval)
come online.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from claimiq import APP_NAME, TRACK_ID, __version__
from claimiq.config import settings

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    """Liveness + configuration snapshot (never exposes secret values)."""
    return {
        "status": "ok",
        "app": APP_NAME,
        "version": __version__,
        "track": TRACK_ID,
        "gemini_configured": settings.gemini_configured,
        "gemini_model": settings.gemini_model,
        "time": datetime.now(timezone.utc).isoformat(),
    }
