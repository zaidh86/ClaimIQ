"""API routes.

The browser talks only to these endpoints; all Gemini access stays server-side
and the API key never appears in any response. The claim bundle's internal
`scenario` authoring tag and ground_truth.json are deliberately never exposed.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from claimiq import APP_NAME, TRACK_ID, __version__
from claimiq.config import settings
from claimiq.data.loader import DatasetError, get_claim, load_claims
from claimiq.data.schemas import ClaimBundle
from claimiq.engine.engine import EngineInputError, review_claim
from claimiq.extraction.extractor import ExtractionError, extract_claim_evidence
from claimiq.extraction.gemini_client import GeminiClient, GeminiUnavailableError
from claimiq.rag.grounded import ground_review
from claimiq.record.correspondence import build_correspondence
from claimiq.record.hints import hints_for_review
from claimiq.record.matrix import build_evidence_matrix

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def _gemini_client() -> GeminiClient:
    """Client factory — indirection so tests can inject offline fakes."""
    return GeminiClient()


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


def _claim_summary(bundle: ClaimBundle) -> dict:
    s = bundle.policy_schedule
    return {
        "claim_id": bundle.claim_id,
        "title": bundle.title,
        "claim_type": bundle.claim_type_filed.value,
        "submitted_at": bundle.submitted_at.isoformat(),
        "policyholder": s.policyholder,
        "vehicle": {
            "make_model": s.make_model,
            "registration_number": s.registration_number,
            "vehicle_type": s.vehicle_type.value,
        },
        "documents": [d.doc_type.value for d in bundle.documents],
    }


@router.get("/claims")
def list_claims() -> dict:
    claims = sorted(load_claims().values(), key=lambda b: b.claim_id)
    return {"claims": [_claim_summary(b) for b in claims]}


def _get_bundle_or_404(claim_id: str) -> ClaimBundle:
    try:
        return get_claim(claim_id)
    except DatasetError:
        raise HTTPException(
            status_code=404, detail=f"Unknown claim: {claim_id}"
        ) from None


@router.get("/claims/{claim_id}")
def claim_detail(claim_id: str) -> dict:
    bundle = _get_bundle_or_404(claim_id)
    s = bundle.policy_schedule
    return {
        **_claim_summary(bundle),
        "policy_schedule": {
            "policy_number": s.policy_number,
            "policyholder": s.policyholder,
            "vehicle_type": s.vehicle_type.value,
            "registration_number": s.registration_number,
            "make_model": s.make_model,
            "declared_vehicle_value": s.declared_vehicle_value,
            "policy_start": s.policy_start.isoformat(),
            "policy_end": s.policy_end.isoformat(),
        },
        "documents_full": [
            {"doc_type": d.doc_type.value, "title": d.title, "text": d.text}
            for d in bundle.documents
        ],
    }


@router.post("/claims/{claim_id}/review")
def run_review(claim_id: str) -> dict:
    """Full pipeline: extraction (cached) -> deterministic engine -> grounding.

    The decision comes exclusively from the deterministic engine; grounding
    only adds citations, retrieved context, and an explanation.
    """
    bundle = _get_bundle_or_404(claim_id)
    client = _gemini_client()
    timings: dict[str, float] = {}
    total_start = time.monotonic()

    try:
        stage = time.monotonic()
        evidence = extract_claim_evidence(bundle, client=client)
        timings["extraction_s"] = round(time.monotonic() - stage, 2)
    except GeminiUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Gemini is not configured on the server, so evidence cannot be "
                "extracted. Set GEMINI_API_KEY and restart. "
                f"({exc})"
            ),
        ) from exc
    except ExtractionError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Evidence extraction failed for every document: {exc}",
        ) from exc

    try:
        stage = time.monotonic()
        review = review_claim(bundle, evidence)
        timings["engine_s"] = round(time.monotonic() - stage, 3)
    except EngineInputError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"The review engine could not process this claim: {exc}",
        ) from exc

    stage = time.monotonic()
    grounded = ground_review(bundle, evidence, review, client=client)
    timings["grounding_s"] = round(time.monotonic() - stage, 2)

    payload = grounded.model_dump(mode="json")
    review_payload = payload.pop("review")

    # Phase 11 adjudication record: deterministic transformations of the review
    # above — no Gemini, no network. A failure here degrades to a warning; the
    # decision and citations are never affected.
    correspondence = None
    resolution_hints: dict = {}
    evidence_matrix = None
    try:
        correspondence = build_correspondence(
            bundle, review, grounded.document_citations, grounded.policy_citations
        ).model_dump(mode="json")
        resolution_hints = hints_for_review(review)
        evidence_matrix = build_evidence_matrix(bundle, evidence, review).model_dump(
            mode="json"
        )
    except Exception:  # pragma: no cover - defensive; record building is pure
        logger.exception("adjudication record build failed for %s", bundle.claim_id)
        payload["warnings"].append(
            "adjudication record could not be generated; the review itself is "
            "unaffected."
        )
    timings["total_s"] = round(time.monotonic() - total_start, 2)
    return {
        "claim_id": bundle.claim_id,
        "claim_type": review_payload["claim_type"],
        "decision": review_payload["decision"],
        "decision_reasons": review_payload["decision_reasons"],
        "decision_rationale": review_payload["decision_rationale"],
        "findings": review_payload["findings"],
        "checks_run": review_payload["checks_run"],
        "engine_version": review_payload["engine_version"],
        "reviewed_at": review_payload["reviewed_at"],
        "document_citations": payload["document_citations"],
        "policy_citations": payload["policy_citations"],
        "retrieved_context": payload["retrieved_context"],
        "explanation": payload["explanation"],
        "explanation_source": payload["explanation_source"],
        "warnings": payload["warnings"],
        "correspondence": correspondence,
        "resolution_hints": resolution_hints,
        "evidence_matrix": evidence_matrix,
        "extraction": {
            "model": evidence.model,
            "documents_extracted": sorted(evidence.documents),
            "failed_documents": evidence.failed_documents,
        },
        "timings": timings,
    }
