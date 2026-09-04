"""Review orchestration and deterministic decision logic.

review_claim(bundle, evidence) runs every check, collects structured findings,
and derives the decision by fixed precedence. Gemini has zero authority here:
no network, no LLM, no ground truth — evidence and policy in, findings and
decision out, identically every time.

Decision precedence (each tier only if no higher tier applies):

  1. CRITICAL escalation findings (out-of-scope loss, unestablishable core
     facts, engine failure)                                     -> ESCALATE
  2. Established policy violations (exclusions, window breach,
     outside policy period)                                     -> REJECT
  3. Any other escalation finding (material contradictions,
     total-loss referral per the limit clause)                  -> ESCALATE
  4. Fixable gaps (missing documents/information)               -> REQUEST_INFORMATION
  5. Documents complete, coverage established, nothing adverse  -> APPROVE
  6. Anything else                                              -> ESCALATE

Note one deliberate deviation from the "missing info before contradiction"
ordering sometimes suggested: material contradictions ESCALATE even when
information is also missing, because requesting documents while the existing
evidence contradicts itself risks papering over the conflict. Approval is
never the fallback — tier 5 requires positive establishment, and everything
unclassifiable escalates.
"""

from __future__ import annotations

import logging

from claimiq.data.loader import load_policy
from claimiq.data.schemas import ClaimBundle, Decision, Policy
from claimiq.engine.checks import ALL_CHECKS, CheckContext
from claimiq.engine.schemas import (
    ClaimReview,
    Finding,
    FindingCategory,
    FindingEffect,
    Severity,
)
from claimiq.extraction.schemas import ClaimEvidence

logger = logging.getLogger(__name__)


class EngineInputError(Exception):
    """The engine was handed inconsistent inputs (caller bug, not claim data)."""


def _decide(ctx: CheckContext) -> tuple[Decision, list[str], str]:
    findings = ctx.findings
    critical_esc = [
        f for f in findings
        if f.effect == FindingEffect.NEEDS_ESCALATION and f.severity == Severity.CRITICAL
    ]
    rejects = [f for f in findings if f.effect == FindingEffect.BLOCK_REJECT]
    other_esc = [
        f for f in findings
        if f.effect == FindingEffect.NEEDS_ESCALATION and f.severity != Severity.CRITICAL
    ]
    needs_info = [f for f in findings if f.effect == FindingEffect.NEEDS_INFORMATION]

    def ids(fs: list[Finding]) -> list[str]:
        return [f.finding_id for f in fs]

    def titles(fs: list[Finding], limit: int = 3) -> str:
        return "; ".join(f.title for f in fs[:limit])

    if critical_esc:
        all_esc = critical_esc + other_esc
        return (
            Decision.ESCALATE,
            ids(all_esc),
            f"Escalated to an investigator: {titles(critical_esc)}. The system "
            f"does not decide claims it cannot ground in the policy and evidence.",
        )
    if rejects:
        return (
            Decision.REJECT,
            ids(rejects),
            f"Rejected under the policy: {titles(rejects)}.",
        )
    if other_esc:
        return (
            Decision.ESCALATE,
            ids(other_esc),
            f"Escalated to an investigator: {titles(other_esc)}.",
        )
    if needs_info:
        return (
            Decision.REQUEST_INFORMATION,
            ids(needs_info),
            f"Specific information must be requested before assessment: "
            f"{titles(needs_info)}.",
        )

    completeness_ok = any(
        f.category == FindingCategory.DOCUMENT_COMPLETENESS and f.severity == Severity.INFO
        for f in findings
    )
    coverage_ok = any(
        f.category == FindingCategory.POLICY_COVERAGE and f.severity == Severity.INFO
        for f in findings
    )
    if completeness_ok and coverage_ok:
        positives = [
            f for f in findings
            if f.severity == Severity.INFO and f.category in (
                FindingCategory.DOCUMENT_COMPLETENESS,
                FindingCategory.POLICY_COVERAGE,
                FindingCategory.CLAIM_WINDOW,
                FindingCategory.INSURED_VALUE,
                FindingCategory.POLICY_PERIOD,
            )
        ]
        return (
            Decision.APPROVE,
            ids(positives),
            "All required documents are present, the documents are consistent, "
            "coverage applies, and every policy condition checked is satisfied.",
        )

    # Never default to approval.
    fallback = ctx.add(
        FindingCategory.UNCERTAINTY, Severity.CRITICAL,
        FindingEffect.NEEDS_ESCALATION,
        "Insufficient established evidence for an automated outcome",
        "No adverse finding was established, but the positive conditions for "
        "approval (complete documents and established coverage) are not all "
        "present. The safe outcome is human review.",
        rule="decision_fallback",
    )
    return (
        Decision.ESCALATE,
        [fallback.finding_id],
        "Escalated: the evidence does not establish enough for any automated outcome.",
    )


def review_claim(
    bundle: ClaimBundle,
    evidence: ClaimEvidence,
    policy: Policy | None = None,
) -> ClaimReview:
    """Run the full deterministic review for one claim."""
    if evidence.claim_id != bundle.claim_id:
        raise EngineInputError(
            f"Evidence is for {evidence.claim_id!r} but bundle is {bundle.claim_id!r}"
        )
    policy = policy or load_policy()
    ctx = CheckContext(bundle, evidence, policy)
    checks_run: list[str] = []

    for check in ALL_CHECKS:
        try:
            check(ctx)
            checks_run.append(check.__name__)
        except Exception as exc:  # a broken check must fail safe, not crash
            logger.exception("%s failed for %s", check.__name__, bundle.claim_id)
            ctx.add(
                FindingCategory.UNCERTAINTY, Severity.CRITICAL,
                FindingEffect.NEEDS_ESCALATION,
                f"Automated check failed: {check.__name__}",
                f"The {check.__name__} check raised {type(exc).__name__} and its "
                f"result is unavailable. The review cannot be completed "
                f"automatically, so the claim is escalated.",
                rule=check.__name__,
            )
            checks_run.append(f"{check.__name__} (failed)")

    decision, reasons, rationale = _decide(ctx)
    return ClaimReview(
        claim_id=bundle.claim_id,
        claim_type=ctx.claim_type,
        decision=decision,
        decision_reasons=reasons,
        decision_rationale=rationale,
        findings=ctx.findings,
        checks_run=checks_run,
    )
