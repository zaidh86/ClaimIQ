"""Deterministic checks over ClaimEvidence + policy.

Design rules embodied here:

- Unknown means unknown: a fact no document states is never assumed.
- Conflicts are surfaced, never resolved: when documents disagree on a fact,
  every version is preserved in the finding and no value is chosen as truth.
- Formatting differences are not contradictions: values are compared through
  per-field normalization (typed dates, normalized registrations, case-folded
  names) so 'ROHAN MALHOTRA' vs 'Rohan Malhotra' never conflicts.
- Every threshold (window days, required documents, FIR hours) is read from
  the policy's machine-readable parameters — nothing is hardcoded here.
- Clause IDs attached to findings come from actual policy clause objects, so a
  referenced clause always exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from datetime import date
from typing import Callable, Optional

from claimiq.data.schemas import ClaimBundle, DocType, PolicyClause, Policy, RuleType
from claimiq.engine.schemas import (
    EvidenceRef,
    Finding,
    FindingCategory,
    FindingEffect,
    Severity,
)
from claimiq.extraction.schemas import ClaimEvidence, Observation

# --------------------------------------------------------------------------
# Normalization (comparison only — displayed values keep their original form)
# --------------------------------------------------------------------------

_TITLES = {"mr", "mrs", "ms", "dr", "shri", "smt", "mx"}


def norm_name(value: object) -> str:
    text = " ".join(str(value).split()).casefold()
    parts = text.split(" ")
    while parts and parts[0].rstrip(".") in _TITLES:
        parts = parts[1:]
    return " ".join(parts)


def norm_compact(value: object) -> str:
    """For identifiers like FIR numbers: remove whitespace, case-fold."""
    return re.sub(r"\s+", "", str(value)).casefold()


# --------------------------------------------------------------------------
# Field views: one field across all documents
# --------------------------------------------------------------------------


@dataclass
class FieldView:
    field: str
    status: str  # "unknown" | "established" | "conflicted"
    value: object = None  # set when established (the normalized consensus)
    observations: list[Observation] = dc_field(default_factory=list)
    normalized: list[object] = dc_field(default_factory=list)

    @property
    def candidates(self) -> list[object]:
        """Distinct normalized values, in first-seen order."""
        seen: list[object] = []
        for v in self.normalized:
            if v not in seen:
                seen.append(v)
        return seen


def field_view(
    evidence: ClaimEvidence,
    field: str,
    normalize: Optional[Callable[[object], object]] = None,
) -> FieldView:
    observations = evidence.observations(field)
    if not observations:
        return FieldView(field=field, status="unknown")
    normalized = [normalize(o.value) if normalize else o.value for o in observations]
    distinct: list[object] = []
    for v in normalized:
        if v not in distinct:
            distinct.append(v)
    if len(distinct) == 1:
        return FieldView(field, "established", distinct[0], observations, normalized)
    return FieldView(field, "conflicted", None, observations, normalized)


# --------------------------------------------------------------------------
# Check context
# --------------------------------------------------------------------------


class CheckContext:
    def __init__(self, bundle: ClaimBundle, evidence: ClaimEvidence, policy: Policy):
        self.bundle = bundle
        self.evidence = evidence
        self.policy = policy
        self.schedule = bundle.policy_schedule
        self.claim_type = bundle.claim_type_filed.value
        self.findings: list[Finding] = []

    # -- finding construction ------------------------------------------------

    def add(
        self,
        category: FindingCategory,
        severity: Severity,
        effect: FindingEffect,
        title: str,
        explanation: str,
        rule: str,
        clauses: Optional[list[PolicyClause]] = None,
        evidence_refs: Optional[list[EvidenceRef]] = None,
    ) -> Finding:
        finding = Finding(
            finding_id=f"FIND-{len(self.findings) + 1:03d}",
            category=category,
            severity=severity,
            effect=effect,
            title=title,
            explanation=explanation,
            rule=rule,
            clause_ids=[c.id for c in (clauses or [])],
            evidence=evidence_refs or [],
        )
        self.findings.append(finding)
        return finding

    # -- policy lookup (always via real clause objects) ----------------------

    def clause(
        self, rule_type: RuleType, claim_type: Optional[str] = None
    ) -> Optional[PolicyClause]:
        for clause in self.policy.clauses_of_type(rule_type):
            if claim_type is None:
                return clause
            params = clause.parameters
            if params.get("claim_type") == claim_type:
                return clause
            if claim_type in params.get("applies_to", []):
                return clause
        return None

    # -- evidence reference helpers ------------------------------------------

    @staticmethod
    def obs_refs(observations: list[Observation]) -> list[EvidenceRef]:
        return [
            EvidenceRef(
                source="document",
                doc_type=o.doc_type,
                field=o.field,
                value=str(o.value),
                quote=o.quote,
                quote_verified=o.quote_verified,
            )
            for o in observations
        ]

    def sched_ref(self, field: str, value: object) -> EvidenceRef:
        return EvidenceRef(source="policy_schedule", field=field, value=str(value))

    def meta_ref(self, field: str, value: object) -> EvidenceRef:
        return EvidenceRef(source="claim_metadata", field=field, value=str(value))

    def view(self, field: str, normalize=None) -> FieldView:
        return field_view(self.evidence, field, normalize)

    def driver_view(self) -> FieldView:
        """Driver identity with 'SELF' resolved against the trusted schedule."""
        holder = norm_name(self.schedule.policyholder)

        def norm_driver(value: object) -> str:
            n = norm_name(value)
            return holder if n == "self" else n

        return self.view("driver_name", norm_driver)


def _fmt_obs(observations: list[Observation]) -> str:
    return "; ".join(f"{o.doc_type.value}: {o.value}" for o in observations)


# --------------------------------------------------------------------------
# Checks — each takes the context and appends findings
# --------------------------------------------------------------------------


def check_document_completeness(ctx: CheckContext) -> None:
    clause = ctx.clause(RuleType.REQUIRED_DOCUMENTS, ctx.claim_type)
    if clause is None:
        ctx.add(
            FindingCategory.UNCERTAINTY, Severity.CRITICAL,
            FindingEffect.NEEDS_ESCALATION,
            "No required-documents rule found for this claim type",
            f"The policy defines no REQUIRED_DOCUMENTS clause for claim type "
            f"'{ctx.claim_type}', so completeness cannot be assessed.",
            rule="document_completeness_check",
        )
        return

    required = {DocType(d) for d in clause.parameters.get("required_documents", [])}
    submitted = ctx.bundle.doc_types
    missing = sorted(required - submitted, key=lambda d: d.value)

    for doc in missing:
        ctx.add(
            FindingCategory.DOCUMENT_COMPLETENESS, Severity.MATERIAL,
            FindingEffect.NEEDS_INFORMATION,
            f"Missing required document: {doc.value}",
            f"{clause.title} ({clause.id}) requires a {doc.value.replace('_', ' ')} "
            f"for a {ctx.claim_type} claim, but none was submitted. The claim "
            f"cannot be assessed until it is provided.",
            rule="document_completeness_check",
            clauses=[clause],
            evidence_refs=[ctx.meta_ref(
                "submitted_documents", ", ".join(sorted(d.value for d in submitted))
            )],
        )

    failed = sorted(ctx.evidence.failed_documents)
    for doc_value in failed:
        ctx.add(
            FindingCategory.UNCERTAINTY, Severity.MATERIAL,
            FindingEffect.NEEDS_ESCALATION,
            f"Submitted document could not be processed: {doc_value}",
            f"The {doc_value.replace('_', ' ')} was submitted but its content "
            f"could not be extracted ({ctx.evidence.failed_documents[doc_value]}). "
            f"Its facts are unavailable to this review.",
            rule="document_completeness_check",
        )

    if not missing and not failed:
        ctx.add(
            FindingCategory.DOCUMENT_COMPLETENESS, Severity.INFO, FindingEffect.NONE,
            "All required documents submitted",
            f"All documents required by {clause.id} for a {ctx.claim_type} claim "
            f"are present: {', '.join(sorted(d.value for d in required))}.",
            rule="document_completeness_check",
            clauses=[clause],
        )


def check_core_facts(ctx: CheckContext) -> None:
    """The date anchoring the whole review must exist somewhere."""
    if ctx.claim_type == "theft":
        anchor, label = ctx.view("discovered_date"), "date the theft was discovered"
    else:
        anchor, label = ctx.view("incident_date"), "date of the incident"
    if anchor.status == "unknown":
        ctx.add(
            FindingCategory.UNCERTAINTY, Severity.CRITICAL,
            FindingEffect.NEEDS_ESCALATION,
            f"The {label} cannot be established",
            f"No submitted document states the {label}. Notification-window and "
            f"policy-period checks cannot be performed; the review cannot proceed "
            f"to a safe automated outcome without this fact.",
            rule="core_facts_check",
        )


_CONTRADICTION_FIELDS = [
    # (field, normalizer, severity, label)
    ("incident_date", None, Severity.MATERIAL, "incident date"),
    ("discovered_date", None, Severity.MATERIAL, "theft discovery date"),
    ("claimed_amount", None, Severity.MATERIAL, "claimed amount"),
    ("fir_number", norm_compact, Severity.MATERIAL, "FIR number"),
    ("policyholder_name", norm_name, Severity.MINOR, "policyholder name"),
]


def check_contradictions(ctx: CheckContext) -> None:
    for field, normalizer, severity, label in _CONTRADICTION_FIELDS:
        view = ctx.view(field, normalizer)
        if view.status != "conflicted":
            continue
        ctx.add(
            FindingCategory.CONTRADICTION, severity, FindingEffect.NEEDS_ESCALATION,
            f"Documents disagree on the {label}",
            f"The submitted documents give different values for the {label}: "
            f"{_fmt_obs(view.observations)}. Both versions are preserved; neither "
            f"is assumed correct. This conflict must be resolved by an "
            f"investigator, not by the system.",
            rule="cross_document_contradiction_check",
            evidence_refs=CheckContext.obs_refs(view.observations),
        )

    # Registration: compare documents against each other AND the trusted schedule.
    reg_view = ctx.view("vehicle_registration", norm_compact)
    sched_reg = norm_compact(ctx.schedule.registration_number)
    doc_values = set(reg_view.normalized)
    if reg_view.status != "unknown" and (doc_values | {sched_reg}) != {sched_reg}:
        matches_schedule = sched_reg in doc_values
        clause = ctx.clause(RuleType.DEFINITION)
        ctx.add(
            FindingCategory.CONTRADICTION,
            Severity.MINOR if matches_schedule else Severity.MATERIAL,
            FindingEffect.NEEDS_ESCALATION,
            "Registration number mismatch across the claim file",
            f"The policy schedule identifies the insured vehicle as "
            f"{ctx.schedule.registration_number}, but the documents also show: "
            f"{_fmt_obs(reg_view.observations)}. "
            + ("Most documents match the schedule, so the divergent value may be "
               "clerical — but vehicle identity must be confirmed, not assumed."
               if matches_schedule else
               "No submitted document matches the scheduled registration; vehicle "
               "identity cannot be confirmed from this file."),
            rule="registration_consistency_check",
            clauses=[clause] if clause else None,
            evidence_refs=CheckContext.obs_refs(reg_view.observations)
            + [ctx.sched_ref("registration_number", ctx.schedule.registration_number)],
        )


def check_temporal_consistency(ctx: CheckContext) -> None:
    incident_obs = ctx.evidence.observations("incident_date")
    followers = [
        ("vehicle_received_at_garage_date", "the garage received the vehicle"),
        ("fir_date", "the FIR was filed"),
    ]
    impossible: list[tuple[Observation, Observation, str]] = []
    for field, label in followers:
        for later in ctx.evidence.observations(field):
            for inc in incident_obs:
                if isinstance(later.value, date) and isinstance(inc.value, date):
                    if later.value < inc.value:
                        impossible.append((later, inc, label))
    if impossible:
        lines = "; ".join(
            f"{label} on {later.value} ({later.doc_type.value}), before the "
            f"incident date {inc.value} stated by the {inc.doc_type.value}"
            for later, inc, label in impossible
        )
        refs = []
        for later, inc, _ in impossible:
            refs.extend(CheckContext.obs_refs([later, inc]))
        ctx.add(
            FindingCategory.CONTRADICTION, Severity.MATERIAL,
            FindingEffect.NEEDS_ESCALATION,
            "Timeline is internally impossible",
            f"Events that must follow the incident are dated before it: {lines}. "
            f"At least one stated date cannot be correct.",
            rule="temporal_consistency_check",
            evidence_refs=refs,
        )


def check_policy_period(ctx: CheckContext) -> None:
    # The policy-period condition is the CONDITION clause with no claim_type param.
    period_clause = next(
        (c for c in ctx.policy.clauses_of_type(RuleType.CONDITION)
         if "claim_type" not in c.parameters),
        None,
    )
    view = ctx.view("incident_date")
    if view.status == "unknown" and ctx.claim_type == "theft":
        view = ctx.view("discovered_date")
    if view.status == "unknown":
        return  # core_facts_check already escalated the absent date

    start, end = ctx.schedule.policy_start, ctx.schedule.policy_end
    inside = [c for c in view.candidates if start <= c <= end]
    outside = [c for c in view.candidates if not (start <= c <= end)]
    refs = CheckContext.obs_refs(view.observations) + [
        ctx.sched_ref("policy_start", start), ctx.sched_ref("policy_end", end)
    ]

    if not outside:
        note = (" under every contested date" if view.status == "conflicted" else "")
        ctx.add(
            FindingCategory.POLICY_PERIOD, Severity.INFO, FindingEffect.NONE,
            "Incident falls within the policy period",
            f"The stated date(s) ({', '.join(str(c) for c in view.candidates)}) all "
            f"fall inside the policy period {start} to {end}{note}.",
            rule="policy_period_check",
            clauses=[period_clause] if period_clause else None,
            evidence_refs=refs,
        )
    elif not inside:
        ctx.add(
            FindingCategory.POLICY_PERIOD, Severity.CRITICAL, FindingEffect.BLOCK_REJECT,
            "Incident falls outside the policy period",
            f"Every stated incident date ({', '.join(str(c) for c in view.candidates)}) "
            f"is outside the policy period {start} to {end}. "
            f"{period_clause.title if period_clause else 'The policy period condition'} "
            f"limits cover to incidents within the policy period.",
            rule="policy_period_check",
            clauses=[period_clause] if period_clause else None,
            evidence_refs=refs,
        )
    else:
        ctx.add(
            FindingCategory.UNCERTAINTY, Severity.MATERIAL, FindingEffect.NEEDS_ESCALATION,
            "Policy-period status depends on which contested date is correct",
            f"Contested incident dates straddle the policy period {start}–{end}: "
            f"inside: {', '.join(str(c) for c in inside)}; outside: "
            f"{', '.join(str(c) for c in outside)}. Whether the policy responds "
            f"cannot be determined until the date conflict is resolved.",
            rule="policy_period_check",
            clauses=[period_clause] if period_clause else None,
            evidence_refs=refs,
        )


def check_claim_window(ctx: CheckContext) -> None:
    clause = ctx.clause(RuleType.CLAIM_WINDOW, ctx.claim_type)
    if clause is None:
        return
    max_days = clause.parameters.get("max_report_days")
    counted_from = clause.parameters.get("counted_from", "incident_date")
    if not isinstance(max_days, int):
        ctx.add(
            FindingCategory.UNCERTAINTY, Severity.MATERIAL, FindingEffect.NEEDS_ESCALATION,
            "Notification window rule has no usable limit",
            f"{clause.id} defines no machine-readable max_report_days; the window "
            f"cannot be checked deterministically.",
            rule="claim_window_check", clauses=[clause],
        )
        return

    view = ctx.view(counted_from)
    if view.status == "unknown":
        return  # absent anchor date already escalated by core_facts_check

    reported = ctx.bundle.submitted_at
    refs = CheckContext.obs_refs(view.observations) + [
        ctx.meta_ref("reported_date", reported)
    ]
    deltas = {c: (reported - c).days for c in view.candidates}

    if any(d < 0 for d in deltas.values()):
        bad = [f"{c} ({d} days)" for c, d in deltas.items() if d < 0]
        ctx.add(
            FindingCategory.CONTRADICTION, Severity.MATERIAL, FindingEffect.NEEDS_ESCALATION,
            "Claim reported before the stated incident date",
            f"The claim was reported on {reported}, which is before the stated "
            f"{counted_from.replace('_', ' ')}: {', '.join(bad)}. The timeline "
            f"cannot be correct as stated.",
            rule="claim_window_check", clauses=[clause], evidence_refs=refs,
        )
        return

    if all(d <= max_days for d in deltas.values()):
        note = " under every contested date" if len(deltas) > 1 else ""
        days_txt = ", ".join(f"{d} day(s) from {c}" for c, d in deltas.items())
        ctx.add(
            FindingCategory.CLAIM_WINDOW, Severity.INFO, FindingEffect.NONE,
            f"Reported within the {max_days}-day notification window",
            f"Reported on {reported}: {days_txt} — within the {max_days}-day limit "
            f"of {clause.id}{note}.",
            rule="claim_window_check", clauses=[clause], evidence_refs=refs,
        )
    elif all(d > max_days for d in deltas.values()):
        days_txt = ", ".join(f"{d} days from {c}" for c, d in deltas.items())
        ctx.add(
            FindingCategory.CLAIM_WINDOW, Severity.CRITICAL, FindingEffect.BLOCK_REJECT,
            f"Reported outside the {max_days}-day notification window",
            f"The claim was first reported on {reported} — {days_txt}. {clause.id} "
            f"({clause.title}) allows {max_days} days and states that later "
            f"notifications are not admissible. Any stated delay reason is visible "
            f"in the documents but condonation is outside this policy's text.",
            rule="claim_window_check", clauses=[clause], evidence_refs=refs,
        )
    else:
        ctx.add(
            FindingCategory.UNCERTAINTY, Severity.MATERIAL, FindingEffect.NEEDS_ESCALATION,
            "Notification-window status depends on which contested date is correct",
            f"Under the contested dates the delay is "
            f"{', '.join(f'{d} days (from {c})' for c, d in deltas.items())} against "
            f"a {max_days}-day limit ({clause.id}). The window outcome changes with "
            f"the date conflict, so it cannot be determined automatically.",
            rule="claim_window_check", clauses=[clause], evidence_refs=refs,
        )


def check_coverage(ctx: CheckContext) -> None:
    coverage = ctx.clause(RuleType.COVERAGE, ctx.claim_type)
    scope = ctx.clause(RuleType.DEFINITION)
    if coverage is None:
        ctx.add(
            FindingCategory.OUT_OF_SCOPE, Severity.CRITICAL, FindingEffect.NEEDS_ESCALATION,
            f"No coverage clause for a '{ctx.claim_type}' claim",
            "The policy contains no coverage section for this claim type. The "
            "system will not invent coverage; a human must determine how to "
            "handle the submission.",
            rule="coverage_check", clauses=[scope] if scope else None,
        )
        return

    if ctx.claim_type == "accident":
        damage = ctx.evidence.observations("damage_description")
        if damage:
            ctx.add(
                FindingCategory.POLICY_COVERAGE, Severity.INFO, FindingEffect.NONE,
                "Accidental damage cover applies",
                f"{coverage.id} ({coverage.title}) covers accidental damage to the "
                f"insured vehicle, and the documents describe such damage.",
                rule="coverage_check", clauses=[coverage],
                evidence_refs=CheckContext.obs_refs(damage[:3]),
            )
        else:
            ctx.add(
                FindingCategory.UNCERTAINTY, Severity.MATERIAL,
                FindingEffect.NEEDS_ESCALATION,
                "No document describes damage to the vehicle",
                f"The claim is filed as accident damage but no submitted document "
                f"describes damage to the insured vehicle, so it cannot be "
                f"confirmed that {coverage.id} is engaged.",
                rule="coverage_check", clauses=[coverage],
            )
        return

    # Theft: cover applies to theft of the ENTIRE insured vehicle only.
    stolen_view = ctx.view("vehicle_itself_stolen")
    items = ctx.evidence.observations("stolen_items")
    if stolen_view.status == "established" and stolen_view.value is True:
        ctx.add(
            FindingCategory.POLICY_COVERAGE, Severity.INFO, FindingEffect.NONE,
            "Vehicle-theft cover applies",
            f"All documents indicate the insured vehicle itself was stolen, which "
            f"{coverage.id} ({coverage.title}) covers.",
            rule="coverage_check", clauses=[coverage],
            evidence_refs=CheckContext.obs_refs(stolen_view.observations),
        )
    elif stolen_view.status == "established" and stolen_view.value is False:
        item_txt = f" The documents describe the stolen property as: {_fmt_obs(items)}." if items else ""
        ctx.add(
            FindingCategory.OUT_OF_SCOPE, Severity.CRITICAL, FindingEffect.NEEDS_ESCALATION,
            "Claimed loss is not theft of the insured vehicle",
            f"Every document indicates the insured vehicle itself was NOT stolen."
            f"{item_txt} {coverage.id} covers theft of the entire insured vehicle "
            f"only, and {scope.id if scope else 'the policy scope'} insures the "
            f"vehicle, not its contents. No clause in the policy covers this loss "
            f"— and no clause explicitly excludes it either. The policy is silent, "
            f"so the system will not force an approve/reject outcome; an "
            f"investigator must handle the claim.",
            rule="coverage_check",
            clauses=[c for c in (scope, coverage) if c],
            evidence_refs=CheckContext.obs_refs(stolen_view.observations + items),
        )
    else:
        status_txt = ("give conflicting accounts of" if stolen_view.status == "conflicted"
                      else "do not establish")
        ctx.add(
            FindingCategory.UNCERTAINTY, Severity.CRITICAL, FindingEffect.NEEDS_ESCALATION,
            "Cannot establish whether the insured vehicle itself was stolen",
            f"The documents {status_txt} whether the insured vehicle itself was "
            f"taken, which determines whether {coverage.id} applies at all.",
            rule="coverage_check", clauses=[coverage],
            evidence_refs=CheckContext.obs_refs(stolen_view.observations),
        )


# Risk types where a first-person verified statement is treated as establishing
# the excluded activity. Security/custody state (unlocked, keys inside) is
# frequently hedged or uncertain in statements, so it is investigated, never
# auto-rejected.
_REJECT_ON_VERIFIED_MENTION = {"alcohol_or_drugs", "commercial_use", "racing_or_speed_trial"}


def check_exclusions(ctx: CheckContext) -> None:
    mentions = ctx.evidence.risk_observations()
    if not mentions:
        return
    for clause in ctx.policy.clauses_of_type(RuleType.EXCLUSION):
        risk_type = clause.parameters.get("risk_type")
        if not risk_type or ctx.claim_type not in clause.parameters.get("applies_to", []):
            continue
        matched = [(d, m) for d, m in mentions if m.risk_type == risk_type]
        if not matched:
            continue
        verified = [(d, m) for d, m in matched if m.quote_verified]
        refs = [
            EvidenceRef(source="document", doc_type=d, field="risk_mention",
                        value=m.risk_type, quote=m.quote, quote_verified=m.quote_verified)
            for d, m in matched
        ]
        if verified and risk_type in _REJECT_ON_VERIFIED_MENTION:
            doc, mention = verified[0]
            ctx.add(
                FindingCategory.POLICY_EXCLUSION, Severity.CRITICAL,
                FindingEffect.BLOCK_REJECT,
                f"Exclusion engaged: {clause.title}",
                f"The claimant's own submitted evidence engages {clause.id} "
                f"({clause.title}). The {doc.value.replace('_', ' ')} states: "
                f"\"{mention.quote}\" — verified verbatim against the document. "
                f"Under {clause.id}, no claim is payable in these circumstances.",
                rule="exclusion_check", clauses=[clause], evidence_refs=refs,
            )
        else:
            ctx.add(
                FindingCategory.POLICY_EXCLUSION, Severity.MATERIAL,
                FindingEffect.NEEDS_ESCALATION,
                f"Possible exclusion requires investigation: {clause.title}",
                f"A statement in the submitted documents may engage {clause.id} "
                f"({clause.title}): {_fmt_obs_quotes(matched)}. The statement does "
                f"not conclusively establish the excluded circumstance, so this is "
                f"referred for investigation rather than decided automatically.",
                rule="exclusion_check", clauses=[clause], evidence_refs=refs,
            )


def _fmt_obs_quotes(matched) -> str:
    return "; ".join(f"{d.value}: \"{m.quote}\"" for d, m in matched)


def check_driver(ctx: CheckContext) -> None:
    if ctx.claim_type != "accident":
        return
    clause = ctx.clause(RuleType.CONDITION, "accident")  # licence/driver condition
    name_view = ctx.driver_view()
    bool_view = ctx.view("driver_is_policyholder")

    if name_view.status == "conflicted" or bool_view.status == "conflicted":
        observations = name_view.observations + bool_view.observations
        ctx.add(
            FindingCategory.CONTRADICTION, Severity.MATERIAL,
            FindingEffect.NEEDS_ESCALATION,
            "Documents disagree on who was driving",
            f"The submitted documents identify different drivers: "
            f"{_fmt_obs(observations)}. "
            f"{clause.id if clause else 'The driver condition'} requires the driver "
            f"to be consistent across all documents and determines whose licence "
            f"must be verified. Neither version is assumed correct; this requires "
            f"investigation.",
            rule="driver_consistency_check",
            clauses=[clause] if clause else None,
            evidence_refs=CheckContext.obs_refs(observations),
        )
        return

    licence_obs = ctx.evidence.observations("driver_licence_number")
    if licence_obs:
        ctx.add(
            FindingCategory.DRIVER_ELIGIBILITY, Severity.INFO, FindingEffect.NONE,
            "Driving licence details provided",
            f"A driving licence number is stated ({_fmt_obs(licence_obs)}) and the "
            f"driver is identified consistently. (Licence validity against the "
            f"transport registry is outside this system's scope.)",
            rule="driver_licence_check",
            clauses=[clause] if clause else None,
            evidence_refs=CheckContext.obs_refs(licence_obs),
        )
    else:
        ctx.add(
            FindingCategory.DRIVER_ELIGIBILITY, Severity.MATERIAL,
            FindingEffect.NEEDS_INFORMATION,
            "No driving licence details in any document",
            f"{clause.id if clause else 'The driver condition'} makes an accident "
            f"claim admissible only if the driver held a valid licence, but no "
            f"submitted document states any licence details.",
            rule="driver_licence_check",
            clauses=[clause] if clause else None,
        )


def check_theft_requirements(ctx: CheckContext) -> None:
    if ctx.claim_type != "theft":
        return
    clause = ctx.clause(RuleType.CONDITION, "theft")
    if clause is None:
        return
    max_hours = clause.parameters.get("fir_max_hours_after_discovery")

    fir_view = ctx.view("fir_date")
    discovered_view = ctx.view("discovered_date")
    if (fir_view.status == "established" and discovered_view.status == "established"
            and isinstance(max_hours, int)):
        days = (fir_view.value - discovered_view.value).days
        refs = CheckContext.obs_refs(fir_view.observations + discovered_view.observations)
        if days < 0:
            ctx.add(
                FindingCategory.CONTRADICTION, Severity.MATERIAL,
                FindingEffect.NEEDS_ESCALATION,
                "FIR dated before the theft was discovered",
                f"The FIR is dated {fir_view.value}, before the stated discovery "
                f"date {discovered_view.value}. The timeline cannot be correct.",
                rule="theft_fir_timing_check", clauses=[clause], evidence_refs=refs,
            )
        elif days == 0:
            ctx.add(
                FindingCategory.THEFT_REQUIREMENT, Severity.INFO, FindingEffect.NONE,
                f"FIR filed within {max_hours} hours of discovery",
                f"The FIR ({fir_view.value}) was filed on the same day the theft "
                f"was discovered ({discovered_view.value}), satisfying the "
                f"{max_hours}-hour condition in {clause.id}.",
                rule="theft_fir_timing_check", clauses=[clause], evidence_refs=refs,
            )
        elif days == 1:
            ctx.add(
                FindingCategory.THEFT_REQUIREMENT, Severity.INFO, FindingEffect.NONE,
                f"FIR filed the day after discovery — {max_hours}-hour condition "
                f"not confirmable at day precision",
                f"The FIR ({fir_view.value}) is dated one day after discovery "
                f"({discovered_view.value}); whether it was within {max_hours} "
                f"hours depends on times of day the documents do not establish.",
                rule="theft_fir_timing_check", clauses=[clause], evidence_refs=refs,
            )
        else:
            ctx.add(
                FindingCategory.THEFT_REQUIREMENT, Severity.MATERIAL,
                FindingEffect.NEEDS_ESCALATION,
                f"FIR filed {days} days after discovery",
                f"{clause.id} requires an FIR within {max_hours} hours of "
                f"discovering the theft; the FIR ({fir_view.value}) is {days} days "
                f"after discovery ({discovered_view.value}). Under {clause.id} this "
                f"requires investigation before assessment.",
                rule="theft_fir_timing_check", clauses=[clause], evidence_refs=refs,
            )
    elif ctx.bundle.document(DocType.FIR) is not None:
        ctx.add(
            FindingCategory.THEFT_REQUIREMENT, Severity.MATERIAL,
            FindingEffect.NEEDS_INFORMATION,
            "FIR filing time cannot be established",
            "The FIR filing date and/or the discovery date could not be "
            "established from the documents, so the FIR-timing condition in "
            f"{clause.id} cannot be verified.",
            rule="theft_fir_timing_check", clauses=[clause],
        )

    if clause.parameters.get("keys_confirmation_required"):
        keys_view = ctx.view("keys_information")
        if keys_view.status == "unknown":
            ctx.add(
                FindingCategory.THEFT_REQUIREMENT, Severity.MATERIAL,
                FindingEffect.NEEDS_INFORMATION,
                "Key custody is not addressed by any document",
                f"{clause.id} ({clause.title}) requires written confirmation of "
                f"the number and whereabouts of all original keys. The claim "
                f"form's keys field is blank and no document addresses key "
                f"custody. Unknown is treated as unknown — not as satisfied. A "
                f"specific keys confirmation must be requested from the "
                f"policyholder.",
                rule="theft_keys_check", clauses=[clause],
            )
        else:
            ctx.add(
                FindingCategory.THEFT_REQUIREMENT, Severity.INFO, FindingEffect.NONE,
                "Key custody is addressed in the documents",
                f"Statements about the keys: {_fmt_obs(keys_view.observations)}. "
                f"Adequacy of the confirmation is for the claims handler.",
                rule="theft_keys_check", clauses=[clause],
                evidence_refs=CheckContext.obs_refs(keys_view.observations),
            )


def check_amounts(ctx: CheckContext) -> None:
    limit_clause = ctx.clause(RuleType.LIMIT)
    amount_view = ctx.view("claimed_amount")
    dvv = ctx.schedule.declared_vehicle_value

    if amount_view.status == "unknown":
        notes = ctx.evidence.observations("claimed_amount_note")
        if ctx.claim_type == "accident":
            note_txt = (f" The documents say only: {_fmt_obs(notes)}." if notes else "")
            ctx.add(
                FindingCategory.MISSING_INFORMATION, Severity.MATERIAL,
                FindingEffect.NEEDS_INFORMATION,
                "No claimed or estimated amount is stated",
                f"No submitted document states a numeric claimed/estimated repair "
                f"amount.{note_txt} The claim cannot be assessed against the "
                f"declared vehicle value without it.",
                rule="claimed_amount_check",
                clauses=[limit_clause] if limit_clause else None,
                evidence_refs=CheckContext.obs_refs(notes),
            )
        elif notes:
            ctx.add(
                FindingCategory.INSURED_VALUE, Severity.INFO, FindingEffect.NONE,
                "Theft claim amount stated by reference to the declared value",
                f"The claim states its amount as: {_fmt_obs(notes)}. Theft "
                f"settlements are limited by the declared vehicle value "
                f"({dvv}) under {limit_clause.id if limit_clause else 'the limit rule'}.",
                rule="claimed_amount_check",
                clauses=[limit_clause] if limit_clause else None,
                evidence_refs=CheckContext.obs_refs(notes),
            )
        return

    highest = max(v for v in amount_view.normalized if isinstance(v, int))
    refs = CheckContext.obs_refs(amount_view.observations) + [
        ctx.sched_ref("declared_vehicle_value", dvv)
    ]
    if highest > dvv:
        ctx.add(
            FindingCategory.INSURED_VALUE, Severity.MATERIAL,
            FindingEffect.NEEDS_ESCALATION,
            "Estimated cost exceeds the declared vehicle value",
            f"The stated repair/claim amount ({highest}) exceeds the Declared "
            f"Vehicle Value of {dvv}. "
            f"{limit_clause.id if limit_clause else 'The limit rule'} requires such "
            f"claims to be treated as a potential total loss and referred for "
            f"assessment before any settlement. No payout amount is computed by "
            f"this system — that is an assessment outcome.",
            rule="insured_value_check",
            clauses=[limit_clause] if limit_clause else None,
            evidence_refs=refs,
        )
    else:
        ctx.add(
            FindingCategory.INSURED_VALUE, Severity.INFO, FindingEffect.NONE,
            "Claimed amount is within the declared vehicle value",
            f"The stated amount ({highest}) is within the Declared Vehicle Value "
            f"of {dvv}.",
            rule="insured_value_check",
            clauses=[limit_clause] if limit_clause else None,
            evidence_refs=refs,
        )


ALL_CHECKS = [
    check_document_completeness,
    check_core_facts,
    check_contradictions,
    check_temporal_consistency,
    check_policy_period,
    check_claim_window,
    check_coverage,
    check_exclusions,
    check_driver,
    check_theft_requirements,
    check_amounts,
]
