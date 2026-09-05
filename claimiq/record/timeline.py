"""Chronological view of the dates the claim file actually states.

Every event is backed by an extracted date fact with its own source document
and verbatim quote, or by the insurer's own record of when the claim was
reported. Nothing is inferred: a date no document states produces no event,
and document metadata is never used as a substitute for evidence.

Contradictions survive intact. When documents disagree about a date, each
version becomes its own event, flagged as contested and linked to the
contradiction finding — the timeline never merges them, orders one as "the"
truth, or hides the loser.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field

from claimiq.data.schemas import ClaimBundle
from claimiq.engine.schemas import ClaimReview
from claimiq.extraction.schemas import ClaimEvidence
from claimiq.record.correspondence import doc_label
from claimiq.record.matrix import conflicted_fields

# Date fields that describe a real-world event, in the order they normally
# occur. Every one is an extracted fact carrying its own supporting quote.
EVENT_FIELDS: list[tuple[str, str]] = [
    ("incident_date", "Incident stated"),
    ("discovered_date", "Theft discovered"),
    ("fir_date", "FIR / police complaint filed"),
    ("vehicle_received_at_garage_date", "Vehicle received at garage"),
    ("document_date", "Document dated"),
]

_FIELD_ORDER = {field: i for i, (field, _) in enumerate(EVENT_FIELDS)}

REPORTED_LABEL = "Claim reported to the insurer"
INSURER_RECORD = "Insurer record"


class TimelineEvent(BaseModel):
    date: str  # ISO date, exactly as the evidence states it
    label: str
    field: str
    source: str  # human-readable origin: document label or insurer record
    doc_type: str = ""  # empty for the insurer's own record
    quote: Optional[str] = None
    quote_verified: bool = False
    contested: bool = False
    finding_ids: list[str] = Field(default_factory=list)


class Timeline(BaseModel):
    events: list[TimelineEvent]
    contested_fields: list[str] = Field(default_factory=list)
    note: str = ""


CONTESTED_NOTE = (
    "Documents disagree about one or more of these dates. Every stated version "
    "is listed separately with its source; the review does not decide which is "
    "correct."
)

PLAIN_NOTE = (
    "Only dates stated in the claim file appear here, each with the document "
    "that states it. Dates no document states are absent, not assumed."
)


def build_timeline(
    bundle: ClaimBundle, evidence: ClaimEvidence, review: ClaimReview
) -> Timeline:
    """Assemble the claim chronology from stated dates only."""
    conflicts = conflicted_fields(review)
    events: list[TimelineEvent] = []

    for field, label in EVENT_FIELDS:
        finding_ids = conflicts.get(field, [])
        for obs in evidence.observations(field):
            if not isinstance(obs.value, date):
                continue  # only real dates become events
            events.append(TimelineEvent(
                date=obs.value.isoformat(),
                label=label,
                field=field,
                source=doc_label(obs.doc_type.value),
                doc_type=obs.doc_type.value,
                quote=obs.quote,
                quote_verified=obs.quote_verified,
                contested=bool(finding_ids),
                finding_ids=list(finding_ids),
            ))

    # The insurer's own record of when the claim arrived. Not a document fact,
    # so it carries no quote — and it is labelled as the insurer's record.
    events.append(TimelineEvent(
        date=bundle.submitted_at.isoformat(),
        label=REPORTED_LABEL,
        field="reported_date",
        source=INSURER_RECORD,
    ))

    events.sort(key=lambda e: (
        e.date,
        _FIELD_ORDER.get(e.field, len(_FIELD_ORDER)),
        e.source,
    ))

    contested = sorted({e.field for e in events if e.contested})
    return Timeline(
        events=events,
        contested_fields=contested,
        note=CONTESTED_NOTE if contested else PLAIN_NOTE,
    )
