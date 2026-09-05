"""Phase 6 tests: the claim/review API — offline, deterministic, no network.

Extraction is replaced with the hand-built evidence fixtures and the Gemini
client with a keyless one, so the full route pipeline (bundle -> engine ->
grounding -> JSON) runs exactly as in production minus the network.
"""

import json

import pytest
from fastapi.testclient import TestClient

from claimiq.api import routes
from claimiq.data.schemas import Decision
from claimiq.extraction.extractor import ExtractionError
from claimiq.extraction.gemini_client import GeminiClient, GeminiUnavailableError
from claimiq.server import create_app

from tests.evidence_fixtures import evidence_for
from tests.test_extraction import make_settings

client = TestClient(create_app(), raise_server_exceptions=False)

EXPECTED_DECISIONS = {
    "CLM-001": Decision.APPROVE,
    "CLM-002": Decision.ESCALATE,
    "CLM-003": Decision.REQUEST_INFORMATION,
    "CLM-004": Decision.REJECT,
    "CLM-005": Decision.REJECT,
    "CLM-006": Decision.ESCALATE,
    "CLM-007": Decision.REQUEST_INFORMATION,
    "CLM-008": Decision.ESCALATE,
}


@pytest.fixture()
def offline_pipeline(monkeypatch):
    """Fixture evidence instead of Gemini extraction; keyless client for grounding."""
    monkeypatch.setattr(
        routes, "extract_claim_evidence",
        lambda bundle, client=None, use_cache=True: evidence_for(bundle.claim_id),
    )
    monkeypatch.setattr(
        routes, "_gemini_client", lambda: GeminiClient(make_settings(key=""))
    )


# --------------------------------------------------------------------------
# Claim listing / detail
# --------------------------------------------------------------------------


def test_list_claims_returns_all_eight():
    resp = client.get("/api/claims")
    assert resp.status_code == 200
    claims = resp.json()["claims"]
    assert [c["claim_id"] for c in claims] == [f"CLM-{i:03d}" for i in range(1, 9)]
    first = claims[0]
    assert {"claim_id", "title", "claim_type", "documents", "vehicle"} <= set(first)


def test_list_claims_never_leaks_ground_truth_or_scenario_tags():
    text = client.get("/api/claims").text
    assert "expected_decision" not in text
    assert "scenario" not in text
    assert "ground_truth" not in text


def test_claim_detail_includes_schedule_and_documents():
    resp = client.get("/api/claims/CLM-002")
    assert resp.status_code == 200
    body = resp.json()
    assert body["policy_schedule"]["registration_number"] == "DL8CAF5027"
    docs = {d["doc_type"] for d in body["documents_full"]}
    assert docs == {"claim_form", "repair_estimate", "incident_description"}
    assert all(len(d["text"]) > 100 for d in body["documents_full"])


def test_unknown_claim_is_json_404():
    for path in ("/api/claims/CLM-999", "/api/claims/CLM-999/review"):
        resp = client.get(path) if "review" not in path else client.post(path)
        assert resp.status_code == 404
        assert "Unknown claim" in resp.json()["detail"]


# --------------------------------------------------------------------------
# Review endpoint — offline full pipeline
# --------------------------------------------------------------------------


@pytest.mark.parametrize("claim_id", sorted(EXPECTED_DECISIONS))
def test_review_decisions_match_regression_expectations(offline_pipeline, claim_id):
    resp = client.post(f"/api/claims/{claim_id}/review")
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == EXPECTED_DECISIONS[claim_id].value
    assert body["findings"], "review must contain findings"
    assert body["decision_reasons"]
    assert body["explanation"] is None  # keyless -> deterministic fallback
    assert body["explanation_source"] == "deterministic_fallback"
    assert body["warnings"]


def test_review_response_structure_for_contradiction_case(offline_pipeline):
    body = client.post("/api/claims/CLM-002/review").json()
    contradictions = [f for f in body["findings"] if f["category"] == "CONTRADICTION"]
    assert contradictions
    date_finding = next(f for f in contradictions if "date" in f["title"].lower())
    values = {e["value"] for e in date_finding["evidence"] if e["source"] == "document"}
    assert {"2026-02-18", "2026-02-14"} <= values  # both versions preserved
    assert body["document_citations"]
    assert all(c["valid"] for c in body["document_citations"])
    clause_ids = {c["clause_id"] for c in body["policy_citations"]}
    assert clause_ids <= {f"POL-{i:02d}" for i in range(1, 18)}


def test_review_is_idempotent_across_calls(offline_pipeline):
    first = client.post("/api/claims/CLM-004/review").json()
    second = client.post("/api/claims/CLM-004/review").json()
    assert first["decision"] == second["decision"] == "REJECT"
    assert [f["finding_id"] for f in first["findings"]] == [
        f["finding_id"] for f in second["findings"]
    ]


# --------------------------------------------------------------------------
# Failure behaviour
# --------------------------------------------------------------------------


def test_review_without_gemini_key_is_503(monkeypatch):
    monkeypatch.setattr(
        routes, "extract_claim_evidence",
        lambda *a, **k: (_ for _ in ()).throw(GeminiUnavailableError("no key")),
    )
    resp = client.post("/api/claims/CLM-001/review")
    assert resp.status_code == 503
    assert "GEMINI_API_KEY" in resp.json()["detail"]


def test_review_extraction_failure_is_502(monkeypatch):
    monkeypatch.setattr(
        routes, "extract_claim_evidence",
        lambda *a, **k: (_ for _ in ()).throw(ExtractionError("all documents failed")),
    )
    resp = client.post("/api/claims/CLM-001/review")
    assert resp.status_code == 502
    assert "extraction failed" in resp.json()["detail"].lower()


def test_no_secrets_in_any_response(offline_pipeline):
    for resp in (
        client.get("/api/health"),
        client.get("/api/claims"),
        client.get("/api/claims/CLM-001"),
        client.post("/api/claims/CLM-001/review"),
    ):
        text = resp.text.lower()
        assert "api_key" not in text
        assert "gemini_api_key" not in text


def test_frontend_served_and_contains_no_key():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "ClaimIQ" in resp.text
    assert "GEMINI_API_KEY" not in resp.text.replace(
        "GEMINI_API_KEY not set", ""  # the health warning label is fine
    )
    assert "api_key" not in resp.text
