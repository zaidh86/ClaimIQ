"""Phase 2 tests: the policy/claim dataset itself is coherent and the
intentional defects (contradictions, gaps, violations) are really there."""

import pytest

from claimiq.data.loader import (
    get_clause,
    load_claims,
    load_ground_truth,
    load_policy,
    required_documents_for,
    validate_dataset,
)
from claimiq.data.schemas import Decision, DocType, RuleType

EXPECTED_SCENARIOS = {
    "clean_accident",
    "contradictory_documents",
    "missing_documents",
    "exclusion_dui",
    "late_notification",
    "insured_value_exceeded",
    "theft_incomplete_evidence",
    "out_of_scope",
}


# --------------------------------------------------------------------------
# Whole-dataset integrity
# --------------------------------------------------------------------------


def test_dataset_cross_file_integrity():
    assert validate_dataset() == []


def test_policy_loads_with_sensible_size():
    policy = load_policy()
    assert 12 <= len(policy.clauses) <= 18
    assert len(policy.clause_ids) == len(policy.clauses)  # unique IDs


def test_policy_covers_all_rule_categories():
    types = {c.rule_type for c in load_policy().clauses}
    assert {
        RuleType.COVERAGE,
        RuleType.EXCLUSION,
        RuleType.LIMIT,
        RuleType.CLAIM_WINDOW,
        RuleType.REQUIRED_DOCUMENTS,
        RuleType.CONDITION,
    } <= types


def test_required_documents_defined_for_both_claim_types():
    assert set(required_documents_for("accident")) == {
        DocType.CLAIM_FORM,
        DocType.REPAIR_ESTIMATE,
        DocType.INCIDENT_DESCRIPTION,
    }
    assert set(required_documents_for("theft")) == {
        DocType.CLAIM_FORM,
        DocType.FIR,
        DocType.INCIDENT_DESCRIPTION,
    }


def test_claims_load_unique_and_complete():
    claims = load_claims()
    assert len(claims) == 8
    truths = load_ground_truth()
    assert set(claims) == set(truths)


def test_all_scenarios_represented_exactly_once():
    scenarios = [c.scenario for c in load_claims().values()]
    assert set(scenarios) == EXPECTED_SCENARIOS
    assert len(scenarios) == len(set(scenarios))
    for claim_id, gt in load_ground_truth().items():
        assert gt.scenario == load_claims()[claim_id].scenario


def test_every_referenced_clause_exists():
    clause_ids = load_policy().clause_ids
    for gt in load_ground_truth().values():
        for ref in gt.applicable_clauses + gt.violated_clauses:
            assert ref in clause_ids, f"{gt.claim_id} references unknown {ref}"


def test_all_decision_categories_appear():
    decisions = {gt.expected_decision for gt in load_ground_truth().values()}
    assert decisions == set(Decision)


def test_documents_are_realistic_raw_text():
    for claim in load_claims().values():
        for doc in claim.documents:
            assert len(doc.text) > 200, f"{claim.claim_id}/{doc.doc_type} too thin"


# --------------------------------------------------------------------------
# Per-scenario intent: the defects we planted are really in the data
# --------------------------------------------------------------------------


def _accident_window_days() -> int:
    for clause in load_policy().clauses_of_type(RuleType.CLAIM_WINDOW):
        if clause.parameters.get("claim_type") == "accident":
            return clause.parameters["max_report_days"]
    pytest.fail("no accident CLAIM_WINDOW clause")


def test_clean_case_is_actually_clean():
    gt = load_ground_truth()["CLM-001"]
    assert gt.expected_decision == Decision.APPROVE
    assert not gt.contradictions and not gt.missing_information
    assert not gt.documents_missing
    assert (gt.reported_date - gt.incident_date).days <= _accident_window_days()
    assert gt.claimed_amount < gt.declared_vehicle_value


def test_contradiction_case_has_material_contradictions():
    gt = load_ground_truth()["CLM-002"]
    assert gt.expected_decision == Decision.ESCALATE
    material = [c for c in gt.contradictions if c.severity == "material"]
    assert len(material) >= 2
    assert {c.field for c in gt.contradictions} >= {"incident_date", "driver"}
    assert gt.incident_date is None  # genuinely contested — not smoothed over
    # both conflicting dates really appear in the raw documents
    bundle = load_claims()["CLM-002"]
    form = bundle.document(DocType.CLAIM_FORM).text
    statement = bundle.document(DocType.INCIDENT_DESCRIPTION).text
    assert "18/02/2026" in form
    assert "14th February" in statement
    assert "Karan" in statement and "SELF" in form


def test_missing_document_case():
    gt = load_ground_truth()["CLM-003"]
    bundle = load_claims()["CLM-003"]
    assert gt.expected_decision == Decision.REQUEST_INFORMATION
    assert gt.documents_missing == [DocType.REPAIR_ESTIMATE]
    assert bundle.document(DocType.REPAIR_ESTIMATE) is None
    assert gt.claimed_amount is None
    assert gt.missing_information


def test_exclusion_case_cites_an_exclusion_clause():
    gt = load_ground_truth()["CLM-004"]
    assert gt.expected_decision == Decision.REJECT
    assert gt.violated_clauses
    assert any(
        get_clause(ref).rule_type == RuleType.EXCLUSION for ref in gt.violated_clauses
    )
    # the incriminating admission is really in the raw text
    statement = load_claims()["CLM-004"].document(DocType.INCIDENT_DESCRIPTION).text
    assert "two-three drinks" in statement


def test_window_case_really_breaches_the_window():
    gt = load_ground_truth()["CLM-005"]
    assert gt.expected_decision == Decision.REJECT
    days = (gt.reported_date - gt.incident_date).days
    assert days > _accident_window_days()
    assert any(
        get_clause(ref).rule_type == RuleType.CLAIM_WINDOW for ref in gt.violated_clauses
    )


def test_insured_value_case_exceeds_declared_value():
    gt = load_ground_truth()["CLM-006"]
    assert gt.expected_decision == Decision.ESCALATE
    assert gt.claimed_amount > gt.declared_vehicle_value
    assert any(
        get_clause(ref).rule_type == RuleType.LIMIT for ref in gt.applicable_clauses
    )


def test_theft_case_documents_complete_but_keys_unknown():
    gt = load_ground_truth()["CLM-007"]
    bundle = load_claims()["CLM-007"]
    assert gt.expected_decision == Decision.REQUEST_INFORMATION
    assert bundle.doc_types == set(required_documents_for("theft"))
    assert gt.missing_information and "keys" in gt.missing_information[0].lower()
    # notification within the theft window, measured from discovery
    assert (gt.reported_date - gt.discovered_date).days <= 3
    # the keys field is blank on the form, and no other document addresses keys
    for doc in bundle.documents:
        if doc.doc_type == DocType.CLAIM_FORM:
            assert "No. of keys submitted with this form: \n" in doc.text
        else:
            assert "key" not in doc.text.lower(), f"{doc.doc_type} mentions keys"


def test_null_case_is_out_of_scope_and_escalates():
    gt = load_ground_truth()["CLM-008"]
    assert gt.true_claim_type == "out_of_scope"
    assert gt.expected_decision == Decision.ESCALATE
    assert not gt.violated_clauses  # nothing violated — the policy is silent
    assert gt.escalation_reasons
    # vehicle itself untouched, per the raw documents
    text = load_claims()["CLM-008"].document(DocType.CLAIM_FORM).text
    assert "car itself was not taken" in text
