"""Phase 11 tests: correspondence, evidence matrix, resolution hints.

Everything here is offline and deterministic — fixture evidence through the
real engine and citation builders, then the record package. The key security
properties proven:

- correspondence items originate only from existing findings,
- every clause reference resolves to a clause the findings actually cite,
- conflicting values are all preserved and none is chosen as correct,
- the builders are pure (same input, same output; nothing mutated),
- the Gemini narrative cannot reach the artifact (its builder never sees it).
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from claimiq.data.loader import get_claim, load_policy
from claimiq.data.schemas import DocType
from claimiq.engine.engine import review_claim
from claimiq.engine.schemas import (
    EvidenceRef,
    Finding,
    FindingCategory,
    FindingEffect,
    Severity,
)
from claimiq.rag.citations import build_document_citations, build_policy_citations
from claimiq.record.correspondence import build_correspondence
from claimiq.record.hints import RESOLUTION_HINTS, hints_for_review, resolution_hints
from claimiq.record.matrix import build_evidence_matrix
from claimiq.record.timeline import EVENT_FIELDS as TIMELINE_FIELDS, build_timeline

from tests.evidence_fixtures import evidence_for

EXPECTED_KINDS = {
    "CLM-001": "approval_record",
    "CLM-002": "investigator_handoff",
    "CLM-003": "information_request",
    "CLM-004": "decision_rationale",
    "CLM-005": "decision_rationale",
    "CLM-006": "investigator_handoff",
    "CLM-007": "information_request",
    "CLM-008": "investigator_handoff",
}

_CACHE: dict[str, tuple] = {}


def record_for(claim_id: str):
    """(bundle, evidence, review, doc_cits, pol_cits, correspondence)."""
    if claim_id not in _CACHE:
        bundle = get_claim(claim_id)
        evidence = evidence_for(claim_id)
        review = review_claim(bundle, evidence)
        doc_cits = build_document_citations(review, evidence)
        pol_cits = build_policy_citations(review, load_policy())
        corr = build_correspondence(bundle, review, doc_cits, pol_cits)
        _CACHE[claim_id] = (bundle, evidence, review, doc_cits, pol_cits, corr)
    return _CACHE[claim_id]


# --------------------------------------------------------------------------
# Correspondence: kind and universal grounding properties
# --------------------------------------------------------------------------


@pytest.mark.parametrize("claim_id", sorted(EXPECTED_KINDS))
def test_correspondence_kind_matches_decision(claim_id):
    _, _, review, _, _, corr = record_for(claim_id)
    assert corr.kind == EXPECTED_KINDS[claim_id]
    assert corr.decision == review.decision.value
    assert corr.claim_id == claim_id
    assert corr.text.strip()
    assert "language model" in corr.generated_note


@pytest.mark.parametrize("claim_id", sorted(EXPECTED_KINDS))
def test_correspondence_never_invents_policy_clauses(claim_id):
    _, _, review, _, _, corr = record_for(claim_id)
    cited = {cid for f in review.findings for cid in f.clause_ids}
    mentioned = set(re.findall(r"POL-\d{2}", corr.text))
    assert mentioned <= cited, f"invented clauses: {mentioned - cited}"


@pytest.mark.parametrize("claim_id", sorted(EXPECTED_KINDS))
def test_correspondence_never_invents_documents(claim_id):
    bundle, _, _, _, _, corr = record_for(claim_id)
    submitted = {d.doc_type.value for d in bundle.documents}
    for section in corr.sections:
        for item in section.items:
            for ev in item.evidence:
                if ev.source == "document":
                    assert ev.doc_type in submitted


@pytest.mark.parametrize("claim_id", sorted(EXPECTED_KINDS))
def test_correspondence_evidence_lines_match_stored_refs(claim_id):
    """Every quoted value in the artifact exists on a finding evidence ref."""
    _, _, review, _, _, corr = record_for(claim_id)
    stored = set()
    for f in review.findings:
        for ref in f.evidence:
            stored.add((ref.value, ref.quote or ""))
    for section in corr.sections:
        for item in section.items:
            for ev in item.evidence:
                if ev.source == "document":
                    assert (ev.value, ev.quote or "") in stored


@pytest.mark.parametrize("claim_id", sorted(EXPECTED_KINDS))
def test_correspondence_is_deterministic(claim_id):
    bundle, evidence, review, doc_cits, pol_cits, corr = record_for(claim_id)
    again = build_correspondence(bundle, review, doc_cits, pol_cits)
    assert again.model_dump() == corr.model_dump()
    # A fresh engine run (new reviewed_at timestamp) yields the same artifact.
    fresh = review_claim(bundle, evidence)
    corr2 = build_correspondence(
        bundle, fresh, build_document_citations(fresh, evidence), pol_cits
    )
    assert corr2.text == corr.text


def test_correspondence_rejects_mismatched_inputs():
    bundle, _, _, doc_cits, pol_cits, _ = record_for("CLM-001")
    _, _, other_review, _, _, _ = record_for("CLM-002")
    with pytest.raises(ValueError):
        build_correspondence(bundle, other_review, doc_cits, pol_cits)


# --------------------------------------------------------------------------
# Information request (CLM-003, CLM-007)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("claim_id", ["CLM-003", "CLM-007"])
def test_information_request_items_are_exactly_the_needs_info_findings(claim_id):
    _, _, review, _, _, corr = record_for(claim_id)
    expected = [f.finding_id for f in review.findings
                if f.effect == FindingEffect.NEEDS_INFORMATION]
    section = next(s for s in corr.sections if s.title == "Information required")
    assert [i.finding_id for i in section.items] == expected
    assert expected, "these claims must have missing-information findings"
    # every requested item is structurally linked to a real finding
    for item in section.items:
        assert review.finding(item.finding_id) is not None


def test_information_request_letter_content_clm003():
    bundle, _, review, _, _, corr = record_for("CLM-003")
    assert corr.doc_title == "Information Request"
    assert bundle.policy_schedule.policyholder in corr.text  # neutral greeting
    assert "no assessment outcome has been reached" in corr.text.lower()
    # the missing repair estimate is requested with its policy basis
    assert "Repair Estimate" in corr.text
    section = next(s for s in corr.sections if s.title == "Information required")
    doc_finding = next(
        i for i in section.items
        if review.finding(i.finding_id).category == FindingCategory.DOCUMENT_COMPLETENESS
    )
    assert doc_finding.policy_basis, "missing-document request must cite its clause"
    for basis in doc_finding.policy_basis:
        cid = re.search(r"POL-\d{2}", basis).group(0)
        assert cid in review.finding(doc_finding.finding_id).clause_ids


def test_information_request_keys_unknown_clm007():
    _, _, review, _, _, corr = record_for("CLM-007")
    text = corr.text.lower()
    assert "keys" in text
    # unknown stays unknown — the artifact never asserts the keys were missing
    assert "no keys" not in text
    assert "keys were not" not in text


# --------------------------------------------------------------------------
# Rejection rationale (CLM-004, CLM-005)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("claim_id", ["CLM-004", "CLM-005"])
def test_rejection_grounds_are_exactly_the_blocking_findings(claim_id):
    _, _, review, _, _, corr = record_for(claim_id)
    expected = [f.finding_id for f in review.findings
                if f.effect == FindingEffect.BLOCK_REJECT]
    section = next(s for s in corr.sections if s.title.startswith("Grounds"))
    assert [i.finding_id for i in section.items] == expected
    assert expected


def test_rejection_rationale_quotes_and_clause_text_clm004():
    _, _, review, doc_cits, pol_cits, corr = record_for("CLM-004")
    # the claimant's own verified statement appears, verbatim
    assert "two-three drinks" in corr.text
    stored_quotes = {c.quote for c in doc_cits if c.quote}
    for section in corr.sections:
        for item in section.items:
            for ev in item.evidence:
                if ev.quote:
                    assert ev.quote in stored_quotes
    # the engaged exclusion clause is quoted verbatim from the policy
    blocking = next(f for f in review.findings
                    if f.effect == FindingEffect.BLOCK_REJECT)
    policy = load_policy()
    for cid in blocking.clause_ids:
        assert policy.clause_by_id(cid).text in corr.text


def test_rejection_rationale_window_clm005():
    _, _, review, _, _, corr = record_for("CLM-005")
    assert corr.kind == "decision_rationale"
    assert "notification window" in corr.text.lower()
    # rejection artifacts never smuggle in an approval or escalation
    assert "Review outcome: Reject" in corr.text


# --------------------------------------------------------------------------
# Investigator handoff (CLM-002, CLM-006, CLM-008)
# --------------------------------------------------------------------------


def test_handoff_preserves_every_conflicting_value_clm002():
    _, _, review, _, _, corr = record_for("CLM-002")
    contradictions = [f for f in review.findings
                      if f.category == FindingCategory.CONTRADICTION]
    assert contradictions
    for f in contradictions:
        for ref in f.evidence:
            if ref.source == "document":
                assert ref.value in corr.text, (
                    f"conflicting value {ref.value!r} dropped from the handoff"
                )
    # both dates, both drivers, both registrations — nothing resolved
    for value in ("2026-02-18", "2026-02-14", "Arjun Mehta", "Karan Mehta",
                  "DL8CAF5027", "DL8CAF5072"):
        assert value in corr.text
    assert "none assumed correct" in corr.text.lower()


def test_doc_label_substitution_is_whole_word_only_clm002():
    """'fir' inside 'confirmed' must never be rewritten into the FIR label."""
    _, _, review, _, _, corr = record_for("CLM-002")
    assert "conFIR" not in corr.text
    assert "confirmed" in corr.text  # the registration finding uses this word

    from claimiq.record.correspondence import _pretty
    assert _pretty("the fir was submitted") == "the FIR / Police Complaint was submitted"
    assert _pretty("must be confirmed, not assumed") == "must be confirmed, not assumed"
    assert _pretty("claim_form and repair_estimate") == "Claim Form and Repair Estimate"


def test_handoff_never_declares_a_conflict_winner_clm002():
    _, _, _, _, _, corr = record_for("CLM-002")
    lowered = corr.text.lower()
    for phrase in ("is the correct", "is correct and", "should be treated as correct",
                   "the true value", "actually occurred on"):
        assert phrase not in lowered


def test_handoff_hints_are_deterministic_suggestions_clm002():
    _, _, review, _, _, corr = record_for("CLM-002")
    section = next(s for s in corr.sections
                   if s.title == "What would help resolve the case")
    hints = [i.heading for i in section.items]
    assert hints
    known = {h for hint_list in RESOLUTION_HINTS.values() for h in hint_list}
    assert set(hints) <= known  # no invented suggestions
    assert "not resolved by this review" in " ".join(section.paragraphs)


def test_handoff_total_loss_clm006():
    _, _, review, _, _, corr = record_for("CLM-006")
    assert corr.kind == "investigator_handoff"
    assert "exceeds the declared" in corr.text.lower()


def test_handoff_out_of_scope_clm008_omits_unavailable_sections():
    _, _, review, _, _, corr = record_for("CLM-008")
    assert corr.kind == "investigator_handoff"
    assert "not theft of the insured vehicle" in corr.text.lower()
    titles = {s.title for s in corr.sections}
    contradictions = [f for f in review.findings
                      if f.category == FindingCategory.CONTRADICTION]
    if not contradictions:
        # honesty: no hints or conflict sections are fabricated
        assert "What would help resolve the case" not in titles
        assert not any(t.startswith("Conflicting information") for t in titles)


# --------------------------------------------------------------------------
# Resolution hints
# --------------------------------------------------------------------------


def test_hints_cover_every_contradiction_clm002():
    _, _, review, _, _, _ = record_for("CLM-002")
    hints = hints_for_review(review)
    contradiction_ids = {f.finding_id for f in review.findings
                         if f.category == FindingCategory.CONTRADICTION}
    assert set(hints) == contradiction_ids
    for values in hints.values():
        assert values
        assert len(values) == len(set(values))  # deduplicated


def test_hints_only_for_contradictions_and_known_fields():
    _, _, review, _, _, _ = record_for("CLM-004")
    for f in review.findings:
        if f.category != FindingCategory.CONTRADICTION:
            assert resolution_hints(f) == []
    unknown = Finding(
        finding_id="FIND-099", category=FindingCategory.CONTRADICTION,
        severity=Severity.MATERIAL, effect=FindingEffect.NEEDS_ESCALATION,
        title="x", explanation="x", rule="cross_document_contradiction_check",
        evidence=[EvidenceRef(source="document", doc_type=DocType.CLAIM_FORM,
                              field="some_future_field", value="v")],
    )
    assert resolution_hints(unknown) == []  # nothing invented for unknown fields


def test_hints_do_not_mutate_the_review():
    bundle = get_claim("CLM-002")
    review = review_claim(bundle, evidence_for("CLM-002"))
    before = review.model_dump()
    first = hints_for_review(review)
    second = hints_for_review(review)
    assert first == second  # deterministic
    assert review.model_dump() == before  # untouched


# --------------------------------------------------------------------------
# Evidence matrix
# --------------------------------------------------------------------------


def matrix_for(claim_id):
    bundle, evidence, review, _, _, _ = record_for(claim_id)
    return build_evidence_matrix(bundle, evidence, review)


def rows_by_field(matrix):
    return {r.field: r for r in matrix.rows}


def test_matrix_columns_follow_bundle_order():
    bundle, _, _, _, _, _ = record_for("CLM-002")
    matrix = matrix_for("CLM-002")
    assert [c.doc_type for c in matrix.columns] == [
        d.doc_type.value for d in bundle.documents
    ]
    assert not any(c.failed for c in matrix.columns)


def test_matrix_flags_conflicts_from_engine_findings_clm002():
    matrix = matrix_for("CLM-002")
    rows = rows_by_field(matrix)

    date_row = rows["incident_date"]
    assert date_row.conflict is True
    assert date_row.finding_ids
    assert date_row.cells["claim_form"].value == "2026-02-18"
    assert date_row.cells["incident_description"].value == "2026-02-14"
    assert date_row.cells["repair_estimate"] is None  # estimate states no date

    reg_row = rows["vehicle_registration"]
    assert reg_row.conflict is True
    assert reg_row.schedule_value == "DL8CAF5027"  # trusted record shown
    assert reg_row.cells["repair_estimate"].value == "DL8CAF5072"
    assert matrix.has_schedule_column

    driver_row = rows["driver_name"]
    assert driver_row.conflict is True
    assert {driver_row.cells["claim_form"].value,
            driver_row.cells["incident_description"].value} == {
        "Arjun Mehta", "Karan Mehta"}


def test_matrix_conflict_flags_come_from_findings_not_string_compares():
    """CLM-001 has cosmetic value differences (case) but no engine conflict."""
    matrix = matrix_for("CLM-001")
    assert not any(r.conflict for r in matrix.rows)
    rows = rows_by_field(matrix)
    # values displayed in their original per-document form, unresolved
    names = {c.value for c in rows["policyholder_name"].cells.values() if c}
    assert "ROHAN MALHOTRA" in names and "Rohan Malhotra" in names


def test_matrix_unknown_keys_never_becomes_no_clm007():
    matrix = matrix_for("CLM-007")
    rows = rows_by_field(matrix)
    keys_row = rows["keys_information"]
    assert all(cell is None for cell in keys_row.cells.values())  # not stated
    assert keys_row.needs_information is True
    assert keys_row.conflict is False
    assert keys_row.finding_ids  # linked to the keys finding
    _, _, review, _, _, _ = record_for("CLM-007")
    linked = review.finding(keys_row.finding_ids[0])
    assert linked is not None and linked.rule == "theft_keys_check"


def test_matrix_bool_display_distinguishes_stated_no_from_unknown():
    matrix = matrix_for("CLM-008")
    rows = rows_by_field(matrix)
    stolen = rows["vehicle_itself_stolen"]
    stated = [c for c in stolen.cells.values() if c is not None]
    assert stated and all(c.value == "No" for c in stated)
    assert all(c.quote for c in stated)  # a stated "No" carries its quote


def test_matrix_preserves_quote_verification_status():
    matrix = matrix_for("CLM-001")
    rows = rows_by_field(matrix)
    driver_cell = rows["driver_name"].cells["incident_description"]
    assert driver_cell.quote_verified is False  # fixture's unverified quote
    form_cell = rows["driver_name"].cells["claim_form"]
    assert form_cell.quote_verified is True


# --------------------------------------------------------------------------
# Phase 12: claim timeline
# --------------------------------------------------------------------------


def timeline_for(claim_id):
    bundle, evidence, review, _, _, _ = record_for(claim_id)
    return build_timeline(bundle, evidence, review)


def test_timeline_events_are_all_evidence_backed_clm002():
    bundle, evidence, _, _, _, _ = record_for("CLM-002")
    tl = timeline_for("CLM-002")
    stated = {
        (o.doc_type.value, f, o.value.isoformat())
        for f, _ in TIMELINE_FIELDS
        for o in evidence.observations(f)
        if isinstance(o.value, date)
    }
    for ev in tl.events:
        if ev.field == "reported_date":
            assert ev.date == bundle.submitted_at.isoformat()
            assert ev.source == "Insurer record" and ev.doc_type == ""
            assert ev.quote is None  # insurer record, not a document quote
            continue
        assert (ev.doc_type, ev.field, ev.date) in stated
        assert ev.quote  # every document-sourced event carries its quote
    # nothing invented: exactly the stated dates plus the one insurer record
    assert len(tl.events) == len(stated) + 1


def test_timeline_is_chronological_and_keeps_both_contested_dates_clm002():
    tl = timeline_for("CLM-002")
    dates = [e.date for e in tl.events]
    assert dates == sorted(dates)
    incident = [e for e in tl.events if e.field == "incident_date"]
    assert {e.date for e in incident} == {"2026-02-18", "2026-02-14"}
    assert all(e.contested for e in incident)
    assert all(e.finding_ids for e in incident)
    assert {e.source for e in incident} == {"Claim Form", "Incident Description"}
    assert "incident_date" in tl.contested_fields
    assert "does not decide which is correct" in tl.note


def test_timeline_contested_flags_come_from_findings():
    _, _, review, _, _, _ = record_for("CLM-002")
    tl = timeline_for("CLM-002")
    contradiction_ids = {f.finding_id for f in review.findings
                         if f.category == FindingCategory.CONTRADICTION}
    for ev in tl.events:
        assert set(ev.finding_ids) <= contradiction_ids
        assert bool(ev.finding_ids) == ev.contested


def test_timeline_has_no_conflicts_on_a_clean_claim():
    tl = timeline_for("CLM-001")
    assert tl.events
    assert not tl.contested_fields
    assert not any(e.contested for e in tl.events)
    assert "not assumed" in tl.note


def test_timeline_omits_dates_no_document_states():
    """CLM-003 has no FIR and no garage date — no events may appear for them."""
    tl = timeline_for("CLM-003")
    fields = {e.field for e in tl.events}
    assert "fir_date" not in fields
    assert "vehicle_received_at_garage_date" not in fields
    assert "incident_date" in fields and "reported_date" in fields


def test_timeline_theft_claim_orders_discovery_and_fir():
    tl = timeline_for("CLM-007")
    fields = [e.field for e in tl.events]
    assert "discovered_date" in fields and "fir_date" in fields
    discovered = next(e for e in tl.events if e.field == "discovered_date")
    reported = next(e for e in tl.events if e.field == "reported_date")
    assert discovered.date <= reported.date


def test_timeline_is_deterministic_and_pure():
    bundle, evidence, review, _, _, _ = record_for("CLM-002")
    before = review.model_dump()
    first = build_timeline(bundle, evidence, review)
    second = build_timeline(bundle, evidence, review)
    assert first.model_dump() == second.model_dump()
    assert review.model_dump() == before


def test_matrix_is_deterministic_and_pure():
    bundle, evidence, review, _, _, _ = record_for("CLM-002")
    before_review = review.model_dump()
    before_evidence = evidence.model_dump()
    first = build_evidence_matrix(bundle, evidence, review)
    second = build_evidence_matrix(bundle, evidence, review)
    assert first.model_dump() == second.model_dump()
    assert review.model_dump() == before_review
    assert evidence.model_dump() == before_evidence
