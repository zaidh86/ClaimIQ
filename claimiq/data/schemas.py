"""Typed schemas for the policy and claim dataset.

These models are the single vocabulary the rest of the system builds on:
the loader validates raw JSON into them, the review engine (Phase 4) consumes
them, and ground truth is expressed with the same enums so tests and engine
can never drift apart.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class RuleType(str, Enum):
    DEFINITION = "DEFINITION"
    COVERAGE = "COVERAGE"
    EXCLUSION = "EXCLUSION"
    REQUIRED_DOCUMENTS = "REQUIRED_DOCUMENTS"
    CLAIM_WINDOW = "CLAIM_WINDOW"
    LIMIT = "LIMIT"
    CONDITION = "CONDITION"


class DocType(str, Enum):
    CLAIM_FORM = "claim_form"
    REPAIR_ESTIMATE = "repair_estimate"
    FIR = "fir"
    INCIDENT_DESCRIPTION = "incident_description"


class VehicleType(str, Enum):
    TWO_WHEELER = "two_wheeler"
    CAR = "car"


class ClaimType(str, Enum):
    ACCIDENT = "accident"
    THEFT = "theft"


class Decision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_INFORMATION = "REQUEST_INFORMATION"
    ESCALATE = "ESCALATE"


# --------------------------------------------------------------------------
# Policy
# --------------------------------------------------------------------------


class PolicyClause(BaseModel):
    id: str = Field(pattern=r"^POL-\d{2}$")
    title: str
    rule_type: RuleType
    text: str
    parameters: dict = Field(default_factory=dict)


class Policy(BaseModel):
    insurer: str
    product: str
    version: str
    description: str
    clauses: list[PolicyClause]

    @field_validator("clauses")
    @classmethod
    def _unique_clause_ids(cls, clauses: list[PolicyClause]) -> list[PolicyClause]:
        ids = [c.id for c in clauses]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"duplicate clause ids: {dupes}")
        return clauses

    def clause_by_id(self, clause_id: str) -> Optional[PolicyClause]:
        return next((c for c in self.clauses if c.id == clause_id), None)

    def clauses_of_type(self, rule_type: RuleType) -> list[PolicyClause]:
        return [c for c in self.clauses if c.rule_type == rule_type]

    @property
    def clause_ids(self) -> set[str]:
        return {c.id for c in self.clauses}


# --------------------------------------------------------------------------
# Claim bundle (what the insurer receives)
# --------------------------------------------------------------------------


class ClaimDocument(BaseModel):
    """One submitted document, kept as realistic raw text for later extraction."""

    doc_type: DocType
    title: str
    text: str


class PolicySchedule(BaseModel):
    """Insurer-side trusted record for the specific policy (not submitted text)."""

    policy_number: str
    policyholder: str
    vehicle_type: VehicleType
    registration_number: str
    make_model: str
    declared_vehicle_value: int = Field(gt=0)
    policy_start: date
    policy_end: date


class ClaimBundle(BaseModel):
    claim_id: str = Field(pattern=r"^CLM-\d{3}$")
    title: str
    scenario: str
    claim_type_filed: ClaimType
    submitted_at: date
    policy_schedule: PolicySchedule
    documents: list[ClaimDocument]

    @field_validator("documents")
    @classmethod
    def _unique_doc_types(cls, docs: list[ClaimDocument]) -> list[ClaimDocument]:
        types = [d.doc_type for d in docs]
        if len(types) != len(set(types)):
            raise ValueError("duplicate document types in claim bundle")
        return docs

    def document(self, doc_type: DocType) -> Optional[ClaimDocument]:
        return next((d for d in self.documents if d.doc_type == doc_type), None)

    @property
    def doc_types(self) -> set[DocType]:
        return {d.doc_type for d in self.documents}


# --------------------------------------------------------------------------
# Ground truth (development/testing only — never an input to the review)
# --------------------------------------------------------------------------


class GTContradiction(BaseModel):
    field: str
    documents: list[str] = Field(min_length=2)
    values: list[str] = Field(min_length=2)
    severity: Literal["material", "minor"]
    note: str = ""


class GroundTruth(BaseModel):
    claim_id: str = Field(pattern=r"^CLM-\d{3}$")
    scenario: str
    true_claim_type: Literal["accident", "theft", "out_of_scope"]
    vehicle_type: VehicleType
    registration_number: str
    incident_date: Optional[date]  # None when genuinely contested/unknown
    discovered_date: Optional[date] = None  # theft only
    reported_date: date
    driver_name: Optional[str]
    driver_is_policyholder: Optional[bool]
    claimed_amount: Optional[int]  # None when not stated anywhere
    declared_vehicle_value: int
    documents_present: list[DocType]
    documents_missing: list[DocType]
    contradictions: list[GTContradiction]
    missing_information: list[str]
    applicable_clauses: list[str]
    violated_clauses: list[str]
    expected_decision: Decision
    escalation_reasons: list[str]
    notes: str
