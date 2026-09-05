"""Deterministic resolution hints for contradiction findings.

For each contradicted field, a fixed mapping names the additional records that
could help an investigator establish the correct value. These are suggestions
only: the system never says which conflicting value is correct, and nothing
here feeds back into the decision — hints are derived FROM findings, after the
decision is already made.
"""

from __future__ import annotations

from claimiq.engine.schemas import ClaimReview, Finding, FindingCategory

# field -> records that could help establish the correct value.
# Keys are evidence-ref field names as they appear on contradiction findings.
RESOLUTION_HINTS: dict[str, list[str]] = {
    "incident_date": [
        "The garage or workshop intake register / job-card entry for the vehicle",
        "The FIR or police record entry stating when the incident occurred",
        "Any contemporaneous record made at the time (tow slip, helpline call log, intimation record)",
    ],
    "discovered_date": [
        "The FIR or police complaint entry recording when the theft was discovered",
        "Parking or building CCTV / security logs for the period in question",
    ],
    "driver_name": [
        "The driving licence of the person stated to have been driving at the time",
        "The FIR or police record identifying the driver",
        "The garage intake record identifying who brought the vehicle in",
    ],
    "driver_is_policyholder": [
        "The driving licence of the person stated to have been driving at the time",
        "The FIR or police record identifying the driver",
        "The garage intake record identifying who brought the vehicle in",
    ],
    "vehicle_registration": [
        "The original Registration Certificate (RC) of the insured vehicle",
        "The garage job-card showing the registration of the vehicle actually received",
        "A corrected document from whichever party recorded a different registration",
    ],
    # The trusted-schedule reference in a registration finding uses this field name.
    "registration_number": [
        "The original Registration Certificate (RC) of the insured vehicle",
        "The garage job-card showing the registration of the vehicle actually received",
        "A corrected document from whichever party recorded a different registration",
    ],
    "claimed_amount": [
        "An itemised garage estimate or invoice for the repair",
        "Written clarification from the claimant of the amount actually claimed",
    ],
    "fir_number": [
        "A certified copy of the FIR from the police station",
        "Written clarification from the claimant of the correct complaint number",
    ],
    "fir_date": [
        "A certified copy of the FIR showing its date of registration",
    ],
    "vehicle_received_at_garage_date": [
        "The garage's intake register or job-card entry with its date",
        "The towing receipt or transport record for the vehicle",
    ],
    "policyholder_name": [
        "Identity documentation for the policyholder named on the policy schedule",
    ],
}


def resolution_hints(finding: Finding) -> list[str]:
    """Hints for one finding — contradictions only, deduplicated, ordered.

    Non-contradiction findings and fields with no mapping yield no hints;
    nothing is ever invented for an unknown field.
    """
    if finding.category != FindingCategory.CONTRADICTION:
        return []
    hints: list[str] = []
    for ref in finding.evidence:
        for hint in RESOLUTION_HINTS.get(ref.field, []):
            if hint not in hints:
                hints.append(hint)
    return hints


def hints_for_review(review: ClaimReview) -> dict[str, list[str]]:
    """finding_id -> hints, for every finding that has any."""
    out: dict[str, list[str]] = {}
    for finding in review.findings:
        hints = resolution_hints(finding)
        if hints:
            out[finding.finding_id] = hints
    return out
