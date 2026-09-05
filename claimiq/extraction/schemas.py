"""Extraction schemas.

Two layers, deliberately separate:

- Wire models (`WireDocumentFacts`): exactly what Gemini is asked to return for
  ONE document. All values are strings/ints/bools with a verbatim supporting
  quote; dates are ISO strings. This model doubles as the structured-output
  schema sent to the API.

- Domain models (`DocumentFacts`, `ClaimEvidence`): validated, typed facts the
  rest of the system consumes. Dates become `datetime.date`, registrations are
  normalized, and every quote is checked against the source document text
  (`quote_verified`). Contested facts are NOT resolved here — each document's
  version of a fact is kept separately, and `ClaimEvidence.observations()`
  exposes all of them side by side for the deterministic engine.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, Field

from claimiq.data.schemas import DocType

# --------------------------------------------------------------------------
# Wire layer — the shape Gemini must produce (per document)
# --------------------------------------------------------------------------


class WireValue(BaseModel):
    """A single extracted value plus the verbatim excerpt that supports it."""

    value: str = Field(description="The extracted value, normalized as instructed.")
    quote: str = Field(
        description=(
            "Verbatim excerpt from the document (copied character-for-character, "
            "max ~200 chars) that states this value."
        )
    )


class WireIntValue(BaseModel):
    value: int = Field(description="The extracted amount in whole rupees, no commas.")
    quote: str = Field(description="Verbatim excerpt stating this amount.")


class WireBoolValue(BaseModel):
    value: bool
    quote: str = Field(description="Verbatim excerpt supporting this true/false fact.")


class WireRiskMention(BaseModel):
    risk_type: Literal[
        "alcohol_or_drugs",
        "commercial_use",
        "racing_or_speed_trial",
        "vehicle_left_unlocked_or_keys_inside",
    ]
    quote: str = Field(description="Verbatim statement from the document.")


class WireDocumentFacts(BaseModel):
    """Facts stated by ONE claim document. Null = this document does not state it."""

    claim_type: Optional[WireValue] = Field(
        default=None,
        description="'accident' or 'theft', only if this document indicates it.",
    )
    policyholder_name: Optional[WireValue] = Field(
        default=None, description="Name of the insured/policyholder as stated."
    )
    vehicle_registration: Optional[WireValue] = Field(
        default=None,
        description=(
            "Registration number, uppercase with spaces/hyphens removed. Report the "
            "exact characters the document contains — never correct apparent typos."
        ),
    )
    vehicle_make_model: Optional[WireValue] = Field(
        default=None, description="Vehicle make/model as stated."
    )
    incident_date: Optional[WireValue] = Field(
        default=None,
        description=(
            "Date of the accident/theft per THIS document, as YYYY-MM-DD. "
            "Dates in these documents are written day-first (18/02/2026 = 18 Feb 2026)."
        ),
    )
    incident_time: Optional[WireValue] = Field(
        default=None, description="Approximate time of the incident as stated."
    )
    incident_location: Optional[WireValue] = Field(
        default=None, description="Place of the incident as stated."
    )
    document_date: Optional[WireValue] = Field(
        default=None,
        description="Date this document itself was signed/issued/registered, YYYY-MM-DD.",
    )
    vehicle_received_at_garage_date: Optional[WireValue] = Field(
        default=None,
        description="Date the vehicle was received/towed in at the garage, YYYY-MM-DD (repair estimates only).",
    )
    discovered_date: Optional[WireValue] = Field(
        default=None,
        description="Theft claims: date the theft was discovered, YYYY-MM-DD.",
    )
    driver_name: Optional[WireValue] = Field(
        default=None,
        description=(
            "Who was driving at the time, per THIS document. If the document says "
            "'self', report the policyholder's name if this document states it, else 'SELF'."
        ),
    )
    driver_is_policyholder: Optional[WireBoolValue] = Field(
        default=None,
        description="True/false only if THIS document indicates whether the policyholder was driving.",
    )
    driver_licence_number: Optional[WireValue] = Field(
        default=None, description="Driving licence number as stated."
    )
    claimed_amount: Optional[WireIntValue] = Field(
        default=None,
        description="Claimed/estimated amount in whole rupees, only when stated as a number.",
    )
    claimed_amount_note: Optional[WireValue] = Field(
        default=None,
        description=(
            "When the amount is stated non-numerically (e.g. 'as per declared value', "
            "'to follow'), the statement itself. Do not convert it to a number."
        ),
    )
    fir_number: Optional[WireValue] = Field(
        default=None, description="FIR/police complaint number as stated."
    )
    fir_date: Optional[WireValue] = Field(
        default=None, description="Date the FIR/police complaint was filed, YYYY-MM-DD."
    )
    police_station: Optional[WireValue] = Field(
        default=None, description="Police station named for the FIR/complaint."
    )
    stolen_items: Optional[WireValue] = Field(
        default=None,
        description="Theft claims: WHAT was stolen per this document (e.g. 'the vehicle', 'laptop and bag').",
    )
    vehicle_itself_stolen: Optional[WireBoolValue] = Field(
        default=None,
        description=(
            "Theft claims: true if THIS document indicates the insured vehicle itself "
            "was taken; false if it indicates the vehicle was NOT taken (e.g. found "
            "parked, undamaged). Null if the document does not address it."
        ),
    )
    keys_information: Optional[WireValue] = Field(
        default=None,
        description=(
            "Theft claims: what THIS document says about the vehicle's keys (count, "
            "custody, surrender). Null if keys are not mentioned at all — including "
            "when a keys field exists on a form but is left blank."
        ),
    )
    damage_description: Optional[WireValue] = Field(
        default=None, description="Damage to the vehicle as described by this document."
    )
    incident_summary: Optional[str] = Field(
        default=None,
        description=(
            "One or two sentences summarising what THIS document says happened. "
            "No facts from outside the document."
        ),
    )
    risk_mentions: list[WireRiskMention] = Field(
        default_factory=list,
        description=(
            "Verbatim statements in THIS document about: driver alcohol/drug "
            "consumption around the incident, commercial use of the vehicle, "
            "racing/speed trials, or the vehicle left unlocked / keys left in it. "
            "Empty list if none."
        ),
    )


# --------------------------------------------------------------------------
# Domain layer — validated, typed, provenance-preserving
# --------------------------------------------------------------------------

T = TypeVar("T")


def _normalize_for_quote_check(text: str) -> str:
    return re.sub(r"\s+", " ", text).casefold().strip()


def quote_appears_in(quote: str, document_text: str) -> bool:
    """Whitespace-insensitive, case-insensitive verbatim check."""
    if not quote:
        return False
    return _normalize_for_quote_check(quote) in _normalize_for_quote_check(document_text)


class Fact(BaseModel, Generic[T]):
    """A typed extracted value with provenance back to its document text."""

    value: T
    quote: Optional[str] = None
    quote_verified: bool = False


class RiskMention(BaseModel):
    risk_type: str
    quote: str
    quote_verified: bool = False


class DocumentFacts(BaseModel):
    """Validated facts from ONE document."""

    claim_type: Optional[Fact[Literal["accident", "theft"]]] = None
    policyholder_name: Optional[Fact[str]] = None
    vehicle_registration: Optional[Fact[str]] = None
    vehicle_make_model: Optional[Fact[str]] = None
    incident_date: Optional[Fact[date]] = None
    incident_time: Optional[Fact[str]] = None
    incident_location: Optional[Fact[str]] = None
    document_date: Optional[Fact[date]] = None
    vehicle_received_at_garage_date: Optional[Fact[date]] = None
    discovered_date: Optional[Fact[date]] = None
    driver_name: Optional[Fact[str]] = None
    driver_is_policyholder: Optional[Fact[bool]] = None
    driver_licence_number: Optional[Fact[str]] = None
    claimed_amount: Optional[Fact[int]] = None
    claimed_amount_note: Optional[Fact[str]] = None
    fir_number: Optional[Fact[str]] = None
    fir_date: Optional[Fact[date]] = None
    police_station: Optional[Fact[str]] = None
    stolen_items: Optional[Fact[str]] = None
    vehicle_itself_stolen: Optional[Fact[bool]] = None
    keys_information: Optional[Fact[str]] = None
    damage_description: Optional[Fact[str]] = None
    incident_summary: Optional[str] = None
    risk_mentions: list[RiskMention] = Field(default_factory=list)

    @classmethod
    def from_wire(cls, wire: WireDocumentFacts, document_text: str) -> "DocumentFacts":
        """Convert + validate a Gemini response against the source document.

        Raises pydantic.ValidationError when a value cannot be typed (e.g. a
        non-ISO date), which the caller treats as a repairable model error.
        """
        payload: dict = {}
        for name in cls.model_fields:
            if name in ("incident_summary", "risk_mentions"):
                continue
            raw = getattr(wire, name)
            if raw is None:
                continue
            value = raw.value
            if name == "vehicle_registration" and isinstance(value, str):
                value = re.sub(r"[\s\-]", "", value).upper()
            if name == "claim_type" and isinstance(value, str):
                value = value.strip().lower()
            payload[name] = {
                "value": value,
                "quote": raw.quote,
                "quote_verified": quote_appears_in(raw.quote, document_text),
            }
        payload["incident_summary"] = wire.incident_summary
        payload["risk_mentions"] = [
            {
                "risk_type": m.risk_type,
                "quote": m.quote,
                "quote_verified": quote_appears_in(m.quote, document_text),
            }
            for m in wire.risk_mentions
        ]
        return cls.model_validate(payload)


class Observation(BaseModel):
    """One document's version of one fact — the unit Phase 4 compares."""

    doc_type: DocType
    field: str
    value: object
    quote: Optional[str] = None
    quote_verified: bool = False


class ClaimEvidence(BaseModel):
    """All validated evidence extracted for one claim, kept per-document.

    Conflicting values across documents are preserved side by side; resolving
    (or flagging) them is the deterministic engine's job, not extraction's.
    """

    claim_id: str
    model: str
    extracted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    documents: dict[str, DocumentFacts] = Field(default_factory=dict)
    failed_documents: dict[str, str] = Field(default_factory=dict)
    # doc_type -> "live" | "runtime_cache" | "seed_cache": where these facts
    # came from, so extraction provenance can be reported truthfully.
    document_sources: dict[str, str] = Field(default_factory=dict)

    def facts_for(self, doc_type: DocType) -> Optional[DocumentFacts]:
        return self.documents.get(doc_type.value)

    def observations(self, field: Optional[str] = None) -> list[Observation]:
        """Flatten per-document facts into comparable observations."""
        out: list[Observation] = []
        for doc_value, facts in self.documents.items():
            for name in DocumentFacts.model_fields:
                if field is not None and name != field:
                    continue
                if name in ("incident_summary", "risk_mentions"):
                    continue
                fact = getattr(facts, name)
                if fact is None:
                    continue
                out.append(
                    Observation(
                        doc_type=DocType(doc_value),
                        field=name,
                        value=fact.value,
                        quote=fact.quote,
                        quote_verified=fact.quote_verified,
                    )
                )
        return out

    def risk_observations(self) -> list[tuple[DocType, RiskMention]]:
        return [
            (DocType(doc_value), mention)
            for doc_value, facts in self.documents.items()
            for mention in facts.risk_mentions
        ]
