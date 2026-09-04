"""Phase 4 tests: the deterministic review engine.

The engine must reach every decision from evidence + policy rules alone —
fixtures carry no expectations, and ground truth is used only to verify
outcomes from the outside.
"""

import inspect

import pytest

from claimiq.data.loader import get_claim, load_ground_truth, load_policy
from claimiq.data.schemas import Decision
from claimiq.engine import checks as checks_module
from claimiq.engine import engine as engine_module
from claimiq.engine import schemas as engine_schemas
from claimiq.engine.engine import EngineInputError, review_claim
from claimiq.engine.schemas import FindingCategory, FindingEffect, Severity
from claimiq.extraction.schemas import ClaimEvidence

from tests.evidence_fixtures import evidence_for

ALL_CLAIMS = [f"CLM-{i:03d}" for i in range(1, 9)]


def run(claim_id: str):
    return review_claim(get_claim(claim_id), evidence_for(claim_id))


def _strip_field(evidence: ClaimEvidence, field: str) -> ClaimEvidence:
    out = ClaimEvidence(claim_id=evidence.claim_id, model=evidence.model)
    for doc, facts in evidence.documents.items():
        out.documents[doc] = facts.model_copy(update={field: None})
    return out


# --------------------------------------------------------------------------
# All sample claims reach the ground-truth decision from evidence + policy
# --------------------------------------------------------------------------


@pytest.mark.parametrize("claim_id", ALL_CLAIMS)
def test_sample_claim_reaches_ground_truth_decision(claim_id):
    review = run(claim_id)
    expected = load_ground_truth()[claim_id].expected_decision
    assert review.decision == expected, (
        f"{claim_id}: engine said {review.decision}, ground truth expects "
        f"{expected}. Rationale: {review.decision_rationale}"
    )
    assert review.decision_reasons, "every decision must reference findings"
    for fid in review.decision_reasons:
        assert review.finding(fid) is not None


# --------------------------------------------------------------------------
# Scenario-specific behaviour
# --------------------------------------------------------------------------


def test_clean_claim_approves_on_positive_findings_only():
    review = run("CLM-001")
    assert review.decision == Decision.APPROVE
    assert not review.findings_in(FindingCategory.CONTRADICTION)
    for fid in review.decision_reasons:
        assert review.finding(fid).severity == Severity.INFO


def test_capitalization_and_spacing_never_become_contradictions():
    # CLM-001 has 'ROHAN MALHOTRA'/'Rohan Malhotra' and spaced/unspaced
    # registration variants across documents — none may conflict.
    review = run("CLM-001")
    assert review.findings_in(FindingCategory.CONTRADICTION) == []


def test_contradiction_claim_preserves_both_versions_of_every_conflict():
    review = run("CLM-002")
    assert review.decision == Decision.ESCALATE
    contradictions = review.findings_in(FindingCategory.CONTRADICTION)

    date_findings = [f for f in contradictions if "incident date" in f.title.lower()]
    assert date_findings, "the date conflict must be surfaced"
    date_values = {r.value for f in date_findings for r in f.evidence}
    assert "2026-02-18" in date_values and "2026-02-14" in date_values

    driver_findings = [f for f in contradictions if "driving" in f.title.lower()]
    assert driver_findings
    driver_values = " ".join(r.value for f in driver_findings for r in f.evidence)
    assert "Arjun" in driver_values and "Karan" in driver_values

    reg_findings = [f for f in contradictions if "egistration" in f.title]
    assert reg_findings
    reg_values = " ".join(r.value for f in reg_findings for r in f.evidence)
    assert "DL8CAF5027" in reg_values and "DL8CAF5072" in reg_values

    timeline = [f for f in contradictions if f.rule == "temporal_consistency_check"]
    assert timeline, "garage-before-accident timeline must be flagged"
    assert "2026-02-15" in timeline[0].explanation

    # escalation reasons point at the contradictions
    reason_findings = [review.finding(fid) for fid in review.decision_reasons]
    assert any(f.category == FindingCategory.CONTRADICTION for f in reason_findings)


def test_missing_document_requests_information_citing_the_policy():
    review = run("CLM-003")
    assert review.decision == Decision.REQUEST_INFORMATION
    missing = [
        f for f in review.findings_in(FindingCategory.DOCUMENT_COMPLETENESS)
        if f.effect == FindingEffect.NEEDS_INFORMATION
    ]
    assert len(missing) == 1
    assert "repair_estimate" in missing[0].title
    assert missing[0].clause_ids == ["POL-07"]


def test_exclusion_rejects_on_claimants_own_verified_statement():
    review = run("CLM-004")
    assert review.decision == Decision.REJECT
    exclusions = review.findings_in(FindingCategory.POLICY_EXCLUSION)
    assert len(exclusions) == 1
    f = exclusions[0]
    assert f.effect == FindingEffect.BLOCK_REJECT
    assert f.clause_ids == ["POL-12"]
    assert any("two-three drinks" in (r.quote or "") for r in f.evidence)


def test_unverified_exclusion_quote_escalates_instead_of_rejecting():
    evidence = evidence_for("CLM-004")
    facts = evidence.documents["incident_description"]
    facts.risk_mentions[0].quote_verified = False
    review = review_claim(get_claim("CLM-004"), evidence)
    exclusions = review.findings_in(FindingCategory.POLICY_EXCLUSION)
    assert exclusions[0].effect == FindingEffect.NEEDS_ESCALATION
    assert review.decision == Decision.ESCALATE  # investigate, don't auto-reject


def test_window_violation_rejects_with_policy_arithmetic():
    review = run("CLM-005")
    assert review.decision == Decision.REJECT
    window = [
        f for f in review.findings_in(FindingCategory.CLAIM_WINDOW)
        if f.effect == FindingEffect.BLOCK_REJECT
    ]
    assert len(window) == 1
    assert window[0].clause_ids == ["POL-05"]
    assert "24 days" in window[0].explanation


def test_insured_value_exceeded_escalates_without_inventing_a_payout():
    review = run("CLM-006")
    assert review.decision == Decision.ESCALATE
    limit = review.findings_in(FindingCategory.INSURED_VALUE)
    assert len(limit) == 1
    f = limit[0]
    assert f.effect == FindingEffect.NEEDS_ESCALATION
    assert f.clause_ids == ["POL-04"]
    assert "385600" in f.explanation and "310000" in f.explanation
    assert "No payout amount is computed" in f.explanation


def test_theft_with_unknown_keys_requests_information():
    review = run("CLM-007")
    assert review.decision == Decision.REQUEST_INFORMATION
    keys = [f for f in review.findings_in(FindingCategory.THEFT_REQUIREMENT)
            if f.rule == "theft_keys_check"]
    assert len(keys) == 1
    assert keys[0].effect == FindingEffect.NEEDS_INFORMATION
    assert keys[0].clause_ids == ["POL-09"]
    # FIR timing was fine and must NOT block anything
    fir = [f for f in review.findings_in(FindingCategory.THEFT_REQUIREMENT)
           if f.rule == "theft_fir_timing_check"]
    assert fir and fir[0].severity == Severity.INFO


def test_contents_theft_is_out_of_scope_and_escalates():
    review = run("CLM-008")
    assert review.decision == Decision.ESCALATE
    oos = review.findings_in(FindingCategory.OUT_OF_SCOPE)
    assert len(oos) == 1
    assert set(oos[0].clause_ids) == {"POL-01", "POL-03"}
    assert oos[0].severity == Severity.CRITICAL
    # the hedged "not sure I locked it" statement must NOT auto-reject
    exclusions = review.findings_in(FindingCategory.POLICY_EXCLUSION)
    for f in exclusions:
        assert f.effect == FindingEffect.NEEDS_ESCALATION
    assert review.decision != Decision.REJECT


# --------------------------------------------------------------------------
# Unknown / synthetic edge cases
# --------------------------------------------------------------------------


def test_unknown_incident_date_escalates_instead_of_guessing():
    evidence = _strip_field(evidence_for("CLM-001"), "incident_date")
    review = review_claim(get_claim("CLM-001"), evidence)
    assert review.decision == Decision.ESCALATE
    core = [f for f in review.findings if f.rule == "core_facts_check"]
    assert core and core[0].severity == Severity.CRITICAL


def test_mixed_window_outcome_under_contested_dates_escalates():
    evidence = evidence_for("CLM-002")
    facts = evidence.documents["incident_description"]
    evidence.documents["incident_description"] = facts.model_copy(
        update={"incident_date": facts.incident_date.model_copy(
            update={"value": facts.incident_date.value.replace(day=5)})}
    )  # 2026-02-05: 15 days before reporting vs 2 days for the other date
    review = review_claim(get_claim("CLM-002"), evidence)
    mixed = [f for f in review.findings
             if f.rule == "claim_window_check"
             and f.category == FindingCategory.UNCERTAINTY]
    assert mixed, "window outcome that depends on the contested date must escalate"
    assert review.decision == Decision.ESCALATE


def test_incident_outside_policy_period_rejects():
    evidence = evidence_for("CLM-001")
    for doc in list(evidence.documents):
        facts = evidence.documents[doc]
        if facts.incident_date is not None:
            evidence.documents[doc] = facts.model_copy(
                update={"incident_date": facts.incident_date.model_copy(
                    update={"value": facts.incident_date.value.replace(year=2025, month=5)})}
            )  # 2025-05-10 — before the policy started
    review = review_claim(get_claim("CLM-001"), evidence)
    assert review.decision == Decision.REJECT
    period = [f for f in review.findings_in(FindingCategory.POLICY_PERIOD)
              if f.effect == FindingEffect.BLOCK_REJECT]
    assert period and period[0].clause_ids == ["POL-11"]


def test_no_default_approval_when_coverage_cannot_be_established():
    evidence = _strip_field(evidence_for("CLM-001"), "damage_description")
    review = review_claim(get_claim("CLM-001"), evidence)
    assert review.decision == Decision.ESCALATE  # never approve by default


def test_empty_evidence_escalates_safely():
    evidence = ClaimEvidence(claim_id="CLM-001", model="fixture-model")
    review = review_claim(get_claim("CLM-001"), evidence)
    assert review.decision == Decision.ESCALATE


# --------------------------------------------------------------------------
# Engine integrity
# --------------------------------------------------------------------------


def test_every_referenced_clause_exists_in_the_policy():
    clause_ids = load_policy().clause_ids
    for claim_id in ALL_CLAIMS:
        for finding in run(claim_id).findings:
            for cid in finding.clause_ids:
                assert cid in clause_ids, f"{claim_id}/{finding.finding_id}: {cid}"


def test_review_is_deterministic():
    a = run("CLM-002").model_dump(exclude={"reviewed_at"})
    b = run("CLM-002").model_dump(exclude={"reviewed_at"})
    assert a == b


def test_engine_has_no_ground_truth_dependency():
    for module in (engine_module, checks_module, engine_schemas):
        source = inspect.getsource(module)
        assert "ground_truth" not in source
        assert "load_ground_truth" not in source


def test_a_crashing_check_fails_safe_to_escalation(monkeypatch):
    def boom(ctx):
        raise RuntimeError("check exploded")

    monkeypatch.setattr(engine_module, "ALL_CHECKS", [boom])
    review = review_claim(get_claim("CLM-001"), evidence_for("CLM-001"))
    assert review.decision == Decision.ESCALATE
    assert any("boom" in f.title for f in review.findings)
    assert "boom (failed)" in review.checks_run


def test_mismatched_evidence_and_bundle_is_rejected():
    with pytest.raises(EngineInputError):
        review_claim(get_claim("CLM-001"), evidence_for("CLM-002"))
