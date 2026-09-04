"""Engine output models: findings, decision explanation, claim review."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

from claimiq.data.schemas import Decision, DocType

ENGINE_VERSION = "1.0.0"


class FindingCategory(str, Enum):
    DOCUMENT_COMPLETENESS = "DOCUMENT_COMPLETENESS"
    MISSING_INFORMATION = "MISSING_INFORMATION"
    CONTRADICTION = "CONTRADICTION"
    POLICY_COVERAGE = "POLICY_COVERAGE"
    POLICY_EXCLUSION = "POLICY_EXCLUSION"
    CLAIM_WINDOW = "CLAIM_WINDOW"
    INSURED_VALUE = "INSURED_VALUE"
    POLICY_PERIOD = "POLICY_PERIOD"
    DRIVER_ELIGIBILITY = "DRIVER_ELIGIBILITY"
    THEFT_REQUIREMENT = "THEFT_REQUIREMENT"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    UNCERTAINTY = "UNCERTAINTY"


class Severity(str, Enum):
    INFO = "INFO"          # satisfied check / neutral observation
    MINOR = "MINOR"        # worth showing, unlikely to change the outcome alone
    MATERIAL = "MATERIAL"  # affects the outcome
    CRITICAL = "CRITICAL"  # decision-driving


class FindingEffect(str, Enum):
    """What a finding implies for the decision (input to precedence rules)."""

    NONE = "NONE"
    BLOCK_REJECT = "BLOCK_REJECT"
    NEEDS_INFORMATION = "NEEDS_INFORMATION"
    NEEDS_ESCALATION = "NEEDS_ESCALATION"


class EvidenceRef(BaseModel):
    """Link from a finding to the evidence it rests on.

    Phase 5 turns these into formal citations; here they carry raw provenance.
    """

    source: Literal["document", "policy_schedule", "claim_metadata"]
    doc_type: Optional[DocType] = None  # set when source == "document"
    field: str
    value: str
    quote: Optional[str] = None
    quote_verified: Optional[bool] = None


class Finding(BaseModel):
    finding_id: str = Field(pattern=r"^FIND-\d{3}$")
    category: FindingCategory
    severity: Severity
    effect: FindingEffect
    title: str
    explanation: str
    rule: str  # name of the deterministic check that produced this finding
    clause_ids: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class ClaimReview(BaseModel):
    claim_id: str
    claim_type: str  # as filed: "accident" / "theft"
    decision: Decision
    decision_reasons: list[str]  # finding IDs that drove the decision
    decision_rationale: str      # deterministic template text, not LLM output
    findings: list[Finding]
    checks_run: list[str]
    engine_version: str = ENGINE_VERSION
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def finding(self, finding_id: str) -> Optional[Finding]:
        return next((f for f in self.findings if f.finding_id == finding_id), None)

    def findings_in(self, category: FindingCategory) -> list[Finding]:
        return [f for f in self.findings if f.category == category]
