"""Formal citations, built and validated by Python — never by an LLM.

Document citations are constructed from the EvidenceRefs the deterministic
engine attached to its findings, then validated against the stored extraction
evidence. Policy citations are constructed from finding clause IDs, with text
taken verbatim from the authoritative policy. Invalid references are kept but
marked invalid with the reason — nothing is silently dropped or repaired, and
quote_verified is passed through untouched (false never becomes true).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from claimiq.data.schemas import Policy
from claimiq.engine.schemas import ClaimReview
from claimiq.extraction.schemas import ClaimEvidence, DocumentFacts


class DocumentCitation(BaseModel):
    finding_id: str
    doc_type: str
    field: str
    value: str
    quote: Optional[str] = None
    quote_verified: bool = False
    valid: bool = True
    issues: list[str] = []


class PolicyCitation(BaseModel):
    finding_id: str
    clause_id: str
    title: str = ""
    rule_type: str = ""
    text: str = ""
    parameters: dict = {}  # machine-readable rule values, verbatim from policy.json
    valid: bool = True
    issues: list[str] = []


def _validate_document_ref(
    evidence: ClaimEvidence, doc_type: str, field: str, value: str, quote: Optional[str]
) -> list[str]:
    issues: list[str] = []
    facts = evidence.documents.get(doc_type)
    if facts is None:
        return [f"document '{doc_type}' has no extracted evidence"]

    if field == "risk_mention":
        if not any(m.quote == quote for m in facts.risk_mentions):
            issues.append("quote does not match any recorded risk mention")
        return issues

    if field not in DocumentFacts.model_fields:
        return [f"'{field}' is not an evidence field"]
    fact = getattr(facts, field)
    if fact is None:
        return [f"'{field}' was not extracted from {doc_type}"]
    if str(fact.value) != value:
        issues.append(
            f"cited value {value!r} does not match stored evidence {str(fact.value)!r}"
        )
    if quote is not None and fact.quote != quote:
        issues.append("cited quote does not match the stored evidence quote")
    return issues


def build_document_citations(
    review: ClaimReview, evidence: ClaimEvidence
) -> list[DocumentCitation]:
    citations: list[DocumentCitation] = []
    for finding in review.findings:
        for ref in finding.evidence:
            if ref.source != "document" or ref.doc_type is None:
                continue
            issues = _validate_document_ref(
                evidence, ref.doc_type.value, ref.field, ref.value, ref.quote
            )
            citations.append(
                DocumentCitation(
                    finding_id=finding.finding_id,
                    doc_type=ref.doc_type.value,
                    field=ref.field,
                    value=ref.value,
                    quote=ref.quote,
                    quote_verified=bool(ref.quote_verified),  # never upgraded
                    valid=not issues,
                    issues=issues,
                )
            )
    return citations


def build_policy_citations(review: ClaimReview, policy: Policy) -> list[PolicyCitation]:
    citations: list[PolicyCitation] = []
    for finding in review.findings:
        for clause_id in finding.clause_ids:
            clause = policy.clause_by_id(clause_id)
            if clause is None:
                citations.append(
                    PolicyCitation(
                        finding_id=finding.finding_id,
                        clause_id=clause_id,
                        valid=False,
                        issues=[f"clause {clause_id} does not exist in the policy"],
                    )
                )
                continue
            citations.append(
                PolicyCitation(
                    finding_id=finding.finding_id,
                    clause_id=clause.id,
                    title=clause.title,
                    rule_type=clause.rule_type.value,
                    text=clause.text,  # verbatim from the authoritative policy
                    parameters=clause.parameters,
                )
            )
    return citations
