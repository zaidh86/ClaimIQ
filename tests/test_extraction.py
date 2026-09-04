"""Phase 3 tests: extraction schemas, provenance, client failure handling,
caching, and the extractor pipeline — all offline, no network required."""

import inspect
import json
from datetime import date

import pytest
from pydantic import ValidationError

from claimiq import extraction
from claimiq.config import Settings
from claimiq.data.loader import get_claim
from claimiq.data.schemas import DocType
from claimiq.extraction import cache, extractor as extractor_module
from claimiq.extraction.extractor import ExtractionError, extract_claim_evidence
from claimiq.extraction.gemini_client import (
    GeminiClient,
    GeminiRequestError,
    GeminiResponseError,
    GeminiUnavailableError,
    strip_code_fences,
)
from claimiq.extraction.prompts import build_document_prompt
from claimiq.extraction.schemas import (
    ClaimEvidence,
    DocumentFacts,
    Fact,
    WireDocumentFacts,
    quote_appears_in,
)


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Every test gets its own empty cache directory — never the repo's."""
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")


def make_settings(key: str = "test-key") -> Settings:
    return Settings(
        host="127.0.0.1",
        port=8000,
        gemini_api_key=key,
        gemini_model="test-model",
        gemini_timeout_seconds=5,
        log_level="info",
    )


class FakeGeminiClient(GeminiClient):
    """GeminiClient with the network call replaced by canned responses.

    Exercises the real validation/repair pipeline in generate_validated.
    """

    def __init__(self, responses_by_doc_type: dict[str, object]):
        super().__init__(make_settings())
        self.responses = responses_by_doc_type
        self.calls: list[str] = []

    def _call_model(self, prompt: str, response_schema) -> str:
        self.calls.append(prompt)
        for doc_type, response in self.responses.items():
            if f"Document type: {doc_type}" in prompt:
                if isinstance(response, Exception):
                    raise response
                return response if isinstance(response, str) else json.dumps(response)
        raise AssertionError("no canned response matches prompt")


# --------------------------------------------------------------------------
# Schemas: null handling, normalization, provenance
# --------------------------------------------------------------------------


def test_empty_response_means_everything_unknown():
    wire = WireDocumentFacts.model_validate_json("{}")
    facts = DocumentFacts.from_wire(wire, document_text="whatever")
    assert all(
        getattr(facts, name) in (None, [])
        for name in DocumentFacts.model_fields
    )


def test_registration_formatting_normalized_but_never_corrected():
    wire = WireDocumentFacts.model_validate(
        {"vehicle_registration": {"value": "dl 8c-af 5072", "quote": "Regn: DL 8C AF 5072"}}
    )
    facts = DocumentFacts.from_wire(wire, document_text="Regn: DL 8C AF 5072")
    # spaces/hyphens/case normalized; the transposed digits preserved as-is
    assert facts.vehicle_registration.value == "DL8CAF5072"
    assert facts.vehicle_registration.quote_verified


def test_iso_dates_become_real_dates_and_bad_dates_fail_validation():
    good = WireDocumentFacts.model_validate(
        {"incident_date": {"value": "2026-02-18", "quote": "Date of Accident: 18/02/2026"}}
    )
    facts = DocumentFacts.from_wire(good, document_text="Date of Accident: 18/02/2026")
    assert facts.incident_date.value == date(2026, 2, 18)

    bad = WireDocumentFacts.model_validate(
        {"incident_date": {"value": "18/02/2026", "quote": "x"}}
    )
    with pytest.raises(ValidationError):
        DocumentFacts.from_wire(bad, document_text="x")


def test_fabricated_quotes_are_marked_unverified_but_value_kept():
    doc_text = "Estimated repair cost: Rs. 8,450/-"
    wire = WireDocumentFacts.model_validate(
        {
            "claimed_amount": {"value": 8450, "quote": "Estimated repair cost: Rs. 8,450/-"},
            "driver_name": {"value": "Someone Made Up", "quote": "the driver was Someone Made Up"},
        }
    )
    facts = DocumentFacts.from_wire(wire, document_text=doc_text)
    assert facts.claimed_amount.quote_verified
    assert facts.driver_name.quote_verified is False
    assert facts.driver_name.value == "Someone Made Up"  # kept, flagged


def test_quote_check_is_whitespace_and_case_insensitive():
    text = "     TOTAL:   Rs. 8,450/-\n(Estimate only.)"
    assert quote_appears_in("total: rs. 8,450/-", text)
    assert not quote_appears_in("Rs. 9,999/-", text)


def test_conflicting_values_from_different_documents_are_both_preserved():
    evidence = ClaimEvidence(claim_id="CLM-XXX", model="test")
    evidence.documents[DocType.CLAIM_FORM.value] = DocumentFacts(
        incident_date=Fact[date](value=date(2026, 2, 18), quote="18/02/2026")
    )
    evidence.documents[DocType.INCIDENT_DESCRIPTION.value] = DocumentFacts(
        incident_date=Fact[date](value=date(2026, 2, 14), quote="14th February 2026")
    )
    observations = evidence.observations("incident_date")
    assert {o.value for o in observations} == {date(2026, 2, 18), date(2026, 2, 14)}
    assert {o.doc_type for o in observations} == {
        DocType.CLAIM_FORM,
        DocType.INCIDENT_DESCRIPTION,
    }


# --------------------------------------------------------------------------
# Client: graceful failure, retry, repair
# --------------------------------------------------------------------------


def test_missing_key_is_a_clean_unavailable_error():
    client = GeminiClient(make_settings(key=""))
    assert client.available is False
    with pytest.raises(GeminiUnavailableError):
        client.generate_validated("p", WireDocumentFacts, parse=lambda raw: raw)


def test_strip_code_fences():
    assert strip_code_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_code_fences('{"a": 1}') == '{"a": 1}'


def test_invalid_output_gets_one_repair_attempt_with_error_context():
    class RepairableClient(GeminiClient):
        def __init__(self):
            super().__init__(make_settings())
            self.calls = []

        def _call_model(self, prompt, response_schema):
            self.calls.append(prompt)
            if len(self.calls) == 1:
                return "this is not json at all"
            return "{}"

    client = RepairableClient()
    result = client.generate_validated(
        "extract things", WireDocumentFacts,
        parse=WireDocumentFacts.model_validate_json,
    )
    assert isinstance(result, WireDocumentFacts)
    assert len(client.calls) == 2
    assert "previous response was invalid" in client.calls[1]


def test_persistently_invalid_output_raises_response_error():
    class BrokenClient(GeminiClient):
        def _call_model(self, prompt, response_schema):
            return '{"claim_type": "not-an-object"}'

    with pytest.raises(GeminiResponseError):
        BrokenClient(make_settings()).generate_validated(
            "p", WireDocumentFacts, parse=WireDocumentFacts.model_validate_json
        )


def test_transient_request_failure_is_retried_then_fatal():
    class FlakyClient(GeminiClient):
        def __init__(self, failures: int):
            super().__init__(make_settings())
            self.failures = failures

        def _call_model(self, prompt, response_schema):
            if self.failures > 0:
                self.failures -= 1
                raise RuntimeError("connection reset")
            return "{}"

    ok = FlakyClient(failures=1).generate_validated(
        "p", WireDocumentFacts, parse=WireDocumentFacts.model_validate_json
    )
    assert isinstance(ok, WireDocumentFacts)

    with pytest.raises(GeminiRequestError):
        FlakyClient(failures=2).generate_validated(
            "p", WireDocumentFacts, parse=WireDocumentFacts.model_validate_json
        )


# --------------------------------------------------------------------------
# Extractor: document separation, partial failure, no ground-truth leakage
# --------------------------------------------------------------------------

CANNED_CLM001 = {
    "claim_form": {
        "claim_type": {"value": "accident", "quote": "[X] Accident Damage"},
        "vehicle_registration": {"value": "MH 12 QT 4431", "quote": "Vehicle Reg. No: MH 12 QT 4431"},
        "incident_date": {"value": "2026-01-10", "quote": "Date of Accident: 10/01/2026"},
    },
    "repair_estimate": {
        "claimed_amount": {"value": 8450, "quote": "TOTAL: Rs. 8,450/-"},
    },
    "incident_description": {
        "incident_date": {"value": "2026-01-10", "quote": "On the evening of 10th Jan 2026"},
    },
}


def test_extractor_keeps_documents_separate_and_verifies_quotes():
    bundle = get_claim("CLM-001")
    client = FakeGeminiClient(CANNED_CLM001)
    evidence = extract_claim_evidence(bundle, client=client, use_cache=False)

    assert set(evidence.documents) == {"claim_form", "repair_estimate", "incident_description"}
    assert not evidence.failed_documents
    # facts stayed attached to their source document
    form = evidence.facts_for(DocType.CLAIM_FORM)
    assert form.vehicle_registration.value == "MH12QT4431"
    assert evidence.facts_for(DocType.REPAIR_ESTIMATE).claimed_amount.value == 8450
    assert evidence.facts_for(DocType.REPAIR_ESTIMATE).incident_date is None
    # quotes were checked against the real document text
    assert form.incident_date.quote_verified
    both = evidence.observations("incident_date")
    assert len(both) == 2 and all(o.quote_verified for o in both)


def test_extractor_records_partial_failure_and_continues():
    bundle = get_claim("CLM-001")
    responses = dict(CANNED_CLM001)
    responses["repair_estimate"] = RuntimeError("boom")
    evidence = extract_claim_evidence(
        bundle, client=FakeGeminiClient(responses), use_cache=False
    )
    assert set(evidence.documents) == {"claim_form", "incident_description"}
    assert "repair_estimate" in evidence.failed_documents


def test_extractor_raises_when_everything_fails():
    bundle = get_claim("CLM-001")
    responses = {d: RuntimeError("down") for d in CANNED_CLM001}
    with pytest.raises(ExtractionError):
        extract_claim_evidence(bundle, client=FakeGeminiClient(responses), use_cache=False)


def test_extractor_unavailable_without_key():
    bundle = get_claim("CLM-001")
    with pytest.raises(GeminiUnavailableError):
        extract_claim_evidence(
            bundle, client=GeminiClient(make_settings(key="")), use_cache=False
        )


def test_prompts_and_extractor_never_see_ground_truth():
    bundle = get_claim("CLM-002")
    for doc in bundle.documents:
        prompt = build_document_prompt(doc.doc_type, doc.text)
        assert "ground truth" not in prompt.lower()
        assert "ESCALATE" not in prompt and "expected_decision" not in prompt
    # and the extraction package simply has no path to the ground-truth file
    for module in (extractor_module, extraction):
        assert "ground_truth" not in inspect.getsource(module)


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------


def test_cache_roundtrip_and_key_sensitivity():
    k1 = cache.cache_key("m", "1", "claim_form", "text")
    assert cache.get(k1) is None
    cache.put(k1, {"facts": {"x": 1}})
    assert cache.get(k1) == {"facts": {"x": 1}}
    assert cache.cache_key("m", "1", "claim_form", "text2") != k1
    assert cache.cache_key("m2", "1", "claim_form", "text") != k1
    assert cache.cache_key("m", "2", "claim_form", "text") != k1


def test_corrupt_cache_entry_is_ignored():
    key = cache.cache_key("m", "1", "fir", "text")
    cache.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (cache.CACHE_DIR / f"{key}.json").write_text("{not valid json", encoding="utf-8")
    assert cache.get(key) is None


def test_extractor_serves_from_cache_without_calling_gemini():
    bundle = get_claim("CLM-001")
    first = FakeGeminiClient(CANNED_CLM001)
    extract_claim_evidence(bundle, client=first, use_cache=True)
    assert len(first.calls) == 3

    # second run: a client whose network path would explode — cache must serve
    exploding = FakeGeminiClient({d: RuntimeError("no network") for d in CANNED_CLM001})
    evidence = extract_claim_evidence(bundle, client=exploding, use_cache=True)
    assert len(exploding.calls) == 0
    assert evidence.facts_for(DocType.CLAIM_FORM).incident_date.value == date(2026, 1, 10)
