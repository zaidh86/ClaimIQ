"""Evidence reconciliation matrix: one field per row, one document per column.

Built in Python from the stored extraction evidence, so the frontend only
renders it. Conflict flags are NOT recomputed here — a row is marked
conflicted exactly when a deterministic contradiction finding references its
field, so the matrix can never disagree with the engine (which compares
values through per-field normalization, not raw strings).

Absent facts stay absent: a field no document states renders as "not stated",
never as a value — unknown is unknown, not "no".
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from claimiq.data.schemas import ClaimBundle
from claimiq.engine.schemas import ClaimReview, Finding, FindingCategory, FindingEffect
from claimiq.extraction.schemas import ClaimEvidence, DocumentFacts
from claimiq.record.correspondence import doc_label

# Human labels for matrix rows (fallback: prettified field name).
FIELD_LABELS = {
    "claim_type": "Claim type",
    "policyholder_name": "Policyholder",
    "vehicle_registration": "Vehicle registration",
    "vehicle_make_model": "Make / model",
    "incident_date": "Incident date",
    "incident_time": "Incident time",
    "incident_location": "Location",
    "document_date": "Document date",
    "vehicle_received_at_garage_date": "Received at garage",
    "discovered_date": "Theft discovered",
    "driver_name": "Driver",
    "driver_is_policyholder": "Driver is policyholder",
    "driver_licence_number": "Driving licence",
    "claimed_amount": "Claimed amount",
    "claimed_amount_note": "Amount (as stated)",
    "fir_number": "FIR number",
    "fir_date": "FIR date",
    "police_station": "Police station",
    "stolen_items": "Stolen items",
    "vehicle_itself_stolen": "Vehicle itself stolen",
    "keys_information": "Keys / custody",
    "damage_description": "Damage described",
}

# Findings produced when a field is missing entirely: rule -> subject field.
# Ensures e.g. the blank keys field still gets a row showing "not stated".
_RULE_SUBJECT_FIELDS = {
    "theft_keys_check": "keys_information",
    "claimed_amount_check": "claimed_amount",
}

# Fields the trusted policy schedule can be compared against.
_SCHEDULE_FIELDS = {
    "vehicle_registration": "registration_number",
    "policyholder_name": "policyholder",
    "vehicle_make_model": "make_model",
}

SCHEDULE_COLUMN = "policy_schedule"

# Evidence-ref field aliases: a schedule ref on a registration finding uses the
# schedule's own field name.
_FIELD_ALIASES = {"registration_number": "vehicle_registration"}


class MatrixCell(BaseModel):
    value: str  # display form; bools become Yes/No so blank never reads as "No"
    quote: Optional[str] = None
    quote_verified: bool = False


class MatrixRow(BaseModel):
    field: str
    label: str
    conflict: bool = False
    needs_information: bool = False
    finding_ids: list[str] = Field(default_factory=list)
    cells: dict[str, Optional[MatrixCell]] = Field(default_factory=dict)
    schedule_value: Optional[str] = None  # trusted record, when comparable


class MatrixColumn(BaseModel):
    doc_type: str
    label: str
    failed: bool = False  # submitted but extraction failed


class EvidenceMatrix(BaseModel):
    columns: list[MatrixColumn]
    rows: list[MatrixRow]
    has_schedule_column: bool = False


def _display_value(value: object) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _add_field(target: dict[str, list[str]], field: str, finding: Finding) -> None:
    field = _FIELD_ALIASES.get(field, field)
    target.setdefault(field, [])
    if finding.finding_id not in target[field]:
        target[field].append(finding.finding_id)


def conflicted_fields(review: ClaimReview) -> dict[str, list[str]]:
    """field -> ids of the contradiction findings that reference it.

    The single source of truth for "this fact is contested", shared by the
    evidence matrix and the timeline so neither can disagree with the engine.
    """
    conflicts: dict[str, list[str]] = {}
    for f in review.findings:
        if f.category != FindingCategory.CONTRADICTION:
            continue
        for ref in f.evidence:
            if ref.field != "risk_mention":
                _add_field(conflicts, ref.field, f)
    return conflicts


def needs_information_fields(review: ClaimReview) -> dict[str, list[str]]:
    """field -> ids of needs-information findings whose subject it is."""
    needs_info: dict[str, list[str]] = {}
    for f in review.findings:
        if f.effect != FindingEffect.NEEDS_INFORMATION:
            continue
        subject = _RULE_SUBJECT_FIELDS.get(f.rule)
        if subject:
            _add_field(needs_info, subject, f)
    return needs_info


def build_evidence_matrix(
    bundle: ClaimBundle, evidence: ClaimEvidence, review: ClaimReview
) -> EvidenceMatrix:
    columns = [
        MatrixColumn(
            doc_type=d.doc_type.value,
            label=doc_label(d.doc_type.value),
            failed=d.doc_type.value in evidence.failed_documents,
        )
        for d in bundle.documents
    ]
    conflicts = conflicted_fields(review)
    needs_info = needs_information_fields(review)

    # Row order follows the extraction schema's field order (a stable,
    # sensible reading order); summaries and risk mentions are not facts rows.
    skip = {"incident_summary", "risk_mentions"}
    rows: list[MatrixRow] = []
    has_schedule = False
    schedule = bundle.policy_schedule

    for field in DocumentFacts.model_fields:
        if field in skip:
            continue
        cells: dict[str, Optional[MatrixCell]] = {}
        any_value = False
        for col in columns:
            facts = evidence.documents.get(col.doc_type)
            fact = getattr(facts, field) if facts is not None else None
            if fact is None:
                cells[col.doc_type] = None
                continue
            any_value = True
            cells[col.doc_type] = MatrixCell(
                value=_display_value(fact.value),
                quote=fact.quote,
                quote_verified=fact.quote_verified,
            )
        conflict_ids = conflicts.get(field, [])
        info_ids = needs_info.get(field, [])
        if not (any_value or conflict_ids or info_ids):
            continue  # nothing to show and nothing flagged — no row

        schedule_value = None
        sched_attr = _SCHEDULE_FIELDS.get(field)
        # The trusted schedule value is shown only where a check compares
        # against it (registration), or where documents state the field too.
        if sched_attr and (any_value or conflict_ids):
            schedule_value = str(getattr(schedule, sched_attr))
            has_schedule = True

        rows.append(MatrixRow(
            field=field,
            label=FIELD_LABELS.get(field, field.replace("_", " ").capitalize()),
            conflict=bool(conflict_ids),
            needs_information=bool(info_ids),
            finding_ids=[*conflict_ids, *info_ids],
            cells=cells,
            schedule_value=schedule_value,
        ))

    return EvidenceMatrix(columns=columns, rows=rows, has_schedule_column=has_schedule)
