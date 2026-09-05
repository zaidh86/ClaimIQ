"""GroundedReview: the deterministic ClaimReview wrapped with validated
citations, retrieved policy context, and a Gemini-written explanation.

Authority is one-directional. The decision and findings come from
review_claim() and are carried through verbatim — GroundedReview has no
decision field of its own, so nothing in this layer can change the outcome.
The explanation model receives only grounded material and is guarded: if its
text mentions any clause or finding ID outside the supplied set, the
explanation is discarded and the deterministic rationale is used instead.
Every failure (no key, retrieval down, bad model output) degrades to a
warning, never to a broken review.
"""

from __future__ import annotations

import logging
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from claimiq.data.loader import load_policy
from claimiq.data.schemas import ClaimBundle, Policy
from claimiq.engine.schemas import ClaimReview
from claimiq.extraction.gemini_client import GeminiClient, GeminiError
from claimiq.extraction.schemas import ClaimEvidence
from claimiq.rag.citations import (
    DocumentCitation,
    PolicyCitation,
    build_document_citations,
    build_policy_citations,
)
from claimiq.rag.index import PolicyIndexError, load_policy_index
from claimiq.rag.retriever import (
    PolicyRetriever,
    RetrievalError,
    RetrievedClause,
)

logger = logging.getLogger(__name__)

MAX_RETRIEVAL_QUERIES = 3


class RetrievedContext(BaseModel):
    clause_id: str
    title: str
    score: float
    reason: str  # which finding this context relates to
    already_cited: bool  # True when the engine already cites this clause


class WireExplanation(BaseModel):
    """Structured output schema for the explanation model."""

    summary: str = Field(description="2-3 sentences for the investigator: what was decided and why, strictly from the supplied findings.")
    key_points: list[str] = Field(description="3-6 short bullet points, each grounded in a supplied finding, quote, or clause.")
    investigator_note: str = Field(description="One or two sentences on what (if anything) a human should verify next. Empty string if nothing remains.")


class GroundedExplanation(BaseModel):
    summary: str
    key_points: list[str]
    investigator_note: str


class GroundedReview(BaseModel):
    review: ClaimReview  # the deterministic result, verbatim — the only decision
    document_citations: list[DocumentCitation]
    policy_citations: list[PolicyCitation]
    retrieved_context: list[RetrievedContext]
    explanation: Optional[GroundedExplanation] = None
    explanation_source: Literal["gemini", "deterministic_fallback"]
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Retrieval of related policy context (explanatory only)
# --------------------------------------------------------------------------


def _retrieve_context(
    review: ClaimReview, retriever: PolicyRetriever
) -> tuple[list[RetrievedContext], list[str]]:
    cited = {cid for f in review.findings for cid in f.clause_ids}
    driving = [review.finding(fid) for fid in review.decision_reasons]
    driving = [f for f in driving if f is not None][:MAX_RETRIEVAL_QUERIES]

    context: list[RetrievedContext] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for finding in driving:
        query = f"{finding.title}. {finding.explanation[:300]}"
        try:
            hits: list[RetrievedClause] = retriever.retrieve(query, top_k=2)
        except RetrievalError as exc:
            warnings.append(f"policy retrieval unavailable: {exc}")
            return context, warnings
        for hit in hits:
            if hit.clause_id in seen:
                continue
            seen.add(hit.clause_id)
            context.append(
                RetrievedContext(
                    clause_id=hit.clause_id,
                    title=hit.title,
                    score=hit.score,
                    reason=f"related to {finding.finding_id}: {finding.title}",
                    already_cited=hit.clause_id in cited,
                )
            )
    return context, warnings


# --------------------------------------------------------------------------
# Grounded Gemini explanation
# --------------------------------------------------------------------------


def _explanation_prompt(
    bundle: ClaimBundle,
    review: ClaimReview,
    doc_citations: list[DocumentCitation],
    policy_citations: list[PolicyCitation],
    context: list[RetrievedContext],
) -> str:
    lines: list[str] = []
    lines.append(
        "You are the explanation writer for ClaimIQ, an insurance claim evidence "
        "review tool. A deterministic rule engine has already reviewed this claim. "
        "Your ONLY job is to explain its result clearly for a claims investigator."
    )
    lines.append(
        "\nHard rules:\n"
        "1. The decision is FIXED. Do not change, question, soften, or re-decide it.\n"
        "2. Do not create new findings and do not omit the decision-driving ones.\n"
        "3. Do not invent facts, amounts, dates, policy clauses, or citations. Use "
        "only the material below.\n"
        "4. Refer to policy clauses and findings only by the IDs supplied below.\n"
        "5. Where evidence is conflicting or unknown, say exactly that — do not "
        "resolve or smooth over it, and clearly separate what documents state "
        "from what is inferred.\n"
        "6. If the decision is ESCALATE, your explanation must support escalation "
        "and describe what the investigator needs to resolve.\n"
        "7. Be concise and factual; no marketing tone."
    )
    s = bundle.policy_schedule
    lines.append(
        f"\n== CLAIM ==\n{bundle.claim_id}: {bundle.title}\n"
        f"Filed as: {bundle.claim_type_filed.value}; reported {bundle.submitted_at}\n"
        f"Insured: {s.policyholder}; vehicle {s.make_model} ({s.registration_number}); "
        f"declared value {s.declared_vehicle_value}; policy period {s.policy_start} "
        f"to {s.policy_end}"
    )
    lines.append(f"\n== DECISION (FIXED) ==\n{review.decision.value}")
    lines.append(f"Deterministic rationale: {review.decision_rationale}")
    lines.append(f"Decision-driving findings: {', '.join(review.decision_reasons)}")

    lines.append("\n== FINDINGS ==")
    for f in review.findings:
        lines.append(
            f"{f.finding_id} [{f.severity.value}/{f.category.value}] {f.title} — "
            f"{f.explanation}"
        )

    verified_quotes = [c for c in doc_citations if c.valid]
    if verified_quotes:
        lines.append("\n== DOCUMENT EVIDENCE (verbatim quotes) ==")
        for c in verified_quotes[:15]:
            flag = "verified" if c.quote_verified else "UNVERIFIED"
            lines.append(
                f"[{c.finding_id}] {c.doc_type}.{c.field} = {c.value} "
                f"({flag} quote: \"{c.quote}\")"
            )

    cited_clauses = {c.clause_id: c for c in policy_citations if c.valid}
    if cited_clauses:
        lines.append("\n== POLICY CLAUSES CITED BY THE ENGINE ==")
        for c in cited_clauses.values():
            lines.append(f"{c.clause_id} ({c.title}): {c.text}")

    extra = [c for c in context if not c.already_cited]
    if extra:
        lines.append(
            "\n== RELATED POLICY CONTEXT (background only — NOT part of the "
            "decision basis; do not present these as reasons) =="
        )
        for c in extra:
            lines.append(f"{c.clause_id} ({c.title}), similarity {c.score}")

    lines.append(
        "\nWrite the explanation now as JSON with fields: summary, key_points, "
        "investigator_note."
    )
    return "\n".join(lines)


_POL_RE = re.compile(r"POL-\d{2}")
_FIND_RE = re.compile(r"FIND-\d{3}")


def _validate_explanation(
    explanation: WireExplanation,
    review: ClaimReview,
    policy_citations: list[PolicyCitation],
    context: list[RetrievedContext],
    policy: Policy,
) -> list[str]:
    """Deterministic guard: the narrative may only mention supplied IDs."""
    text = " ".join(
        [explanation.summary, explanation.investigator_note, *explanation.key_points]
    )
    allowed_clauses = (
        {c.clause_id for c in policy_citations}
        | {c.clause_id for c in context}
    ) & policy.clause_ids
    allowed_findings = {f.finding_id for f in review.findings}
    problems = []
    unknown_clauses = set(_POL_RE.findall(text)) - allowed_clauses
    if unknown_clauses:
        problems.append(
            f"explanation mentioned clause(s) outside the supplied material: "
            f"{sorted(unknown_clauses)}"
        )
    unknown_findings = set(_FIND_RE.findall(text)) - allowed_findings
    if unknown_findings:
        problems.append(
            f"explanation mentioned unknown finding id(s): {sorted(unknown_findings)}"
        )
    if not explanation.summary.strip():
        problems.append("explanation summary is empty")
    return problems


def ground_review(
    bundle: ClaimBundle,
    evidence: ClaimEvidence,
    review: ClaimReview,
    client: Optional[GeminiClient] = None,
    policy: Optional[Policy] = None,
) -> GroundedReview:
    """Wrap a deterministic review with citations, context, and explanation.

    Always returns a GroundedReview; every failure becomes a warning while the
    deterministic review and citations remain intact.
    """
    policy = policy or load_policy()
    client = client or GeminiClient()
    warnings: list[str] = []

    document_citations = build_document_citations(review, evidence)
    policy_citations = build_policy_citations(review, policy)
    for c in [*document_citations, *policy_citations]:
        if not c.valid:
            warnings.append(
                f"invalid citation on {c.finding_id}: {'; '.join(c.issues)}"
            )

    retrieved: list[RetrievedContext] = []
    if not client.available:
        warnings.append(
            "Gemini is not configured — retrieval and narrative explanation "
            "skipped; deterministic rationale used."
        )
    else:
        try:
            index = load_policy_index(policy)
            retriever = PolicyRetriever(index, client)
            retrieved, retrieval_warnings = _retrieve_context(review, retriever)
            warnings.extend(retrieval_warnings)
        except PolicyIndexError as exc:
            warnings.append(f"policy index unavailable: {exc}")

    explanation: Optional[GroundedExplanation] = None
    source: Literal["gemini", "deterministic_fallback"] = "deterministic_fallback"
    if client.available:
        prompt = _explanation_prompt(
            bundle, review, document_citations, policy_citations, retrieved
        )
        try:
            wire = client.generate_validated(
                prompt,
                response_schema=WireExplanation,
                parse=WireExplanation.model_validate_json,
                context=f"{bundle.claim_id}/explanation",
            )
            problems = _validate_explanation(
                wire, review, policy_citations, retrieved, policy
            )
            if problems:
                warnings.extend(problems)
                warnings.append(
                    "explanation discarded by grounding guard; deterministic "
                    "rationale used."
                )
            else:
                explanation = GroundedExplanation(**wire.model_dump())
                source = "gemini"
        except GeminiError as exc:
            warnings.append(
                f"explanation generation failed ({exc}); deterministic rationale used."
            )

    return GroundedReview(
        review=review,
        document_citations=document_citations,
        policy_citations=policy_citations,
        retrieved_context=retrieved,
        explanation=explanation,
        explanation_source=source,
        warnings=warnings,
    )
