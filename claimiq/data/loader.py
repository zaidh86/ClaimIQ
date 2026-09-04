"""Dataset loading and integrity validation.

Single source of truth for reading the policy, claim bundles, and ground truth
from disk. Everything is validated through the pydantic schemas so malformed
data fails loudly at load time with a clear message, not deep inside the
review engine.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from claimiq.data.schemas import (
    ClaimBundle,
    DocType,
    GroundTruth,
    Policy,
    PolicyClause,
    RuleType,
)

DATA_DIR = Path(__file__).resolve().parent
POLICY_PATH = DATA_DIR / "policy.json"
CLAIMS_DIR = DATA_DIR / "claims"
GROUND_TRUTH_PATH = DATA_DIR / "ground_truth.json"


class DatasetError(Exception):
    """Raised when dataset files are missing, malformed, or inconsistent."""


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise DatasetError(f"Dataset file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise DatasetError(f"Malformed JSON in {path.name}: {exc}") from exc


@lru_cache(maxsize=1)
def load_policy() -> Policy:
    try:
        return Policy.model_validate(_read_json(POLICY_PATH))
    except ValidationError as exc:
        raise DatasetError(f"Invalid policy.json: {exc}") from exc


@lru_cache(maxsize=1)
def load_claims() -> dict[str, ClaimBundle]:
    claims: dict[str, ClaimBundle] = {}
    paths = sorted(CLAIMS_DIR.glob("CLM-*.json"))
    if not paths:
        raise DatasetError(f"No claim bundles found in {CLAIMS_DIR}")
    for path in paths:
        try:
            bundle = ClaimBundle.model_validate(_read_json(path))
        except ValidationError as exc:
            raise DatasetError(f"Invalid claim bundle {path.name}: {exc}") from exc
        if bundle.claim_id != path.stem:
            raise DatasetError(
                f"{path.name}: claim_id {bundle.claim_id!r} does not match filename"
            )
        if bundle.claim_id in claims:
            raise DatasetError(f"Duplicate claim_id {bundle.claim_id}")
        claims[bundle.claim_id] = bundle
    return claims


@lru_cache(maxsize=1)
def load_ground_truth() -> dict[str, GroundTruth]:
    raw = _read_json(GROUND_TRUTH_PATH)
    truths: dict[str, GroundTruth] = {}
    for claim_id, payload in raw.items():
        try:
            gt = GroundTruth.model_validate(payload)
        except ValidationError as exc:
            raise DatasetError(f"Invalid ground truth for {claim_id}: {exc}") from exc
        if gt.claim_id != claim_id:
            raise DatasetError(
                f"Ground truth key {claim_id!r} does not match claim_id {gt.claim_id!r}"
            )
        truths[claim_id] = gt
    return truths


def get_claim(claim_id: str) -> ClaimBundle:
    claims = load_claims()
    if claim_id not in claims:
        raise DatasetError(f"Unknown claim_id: {claim_id!r}")
    return claims[claim_id]


def get_clause(clause_id: str) -> PolicyClause:
    clause = load_policy().clause_by_id(clause_id)
    if clause is None:
        raise DatasetError(f"Unknown policy clause: {clause_id!r}")
    return clause


def required_documents_for(claim_type: str) -> list[DocType]:
    """Read the required-document list for a claim type from the policy itself."""
    for clause in load_policy().clauses_of_type(RuleType.REQUIRED_DOCUMENTS):
        if clause.parameters.get("claim_type") == claim_type:
            return [DocType(d) for d in clause.parameters["required_documents"]]
    raise DatasetError(f"No REQUIRED_DOCUMENTS clause for claim type {claim_type!r}")


def validate_dataset() -> list[str]:
    """Cross-file integrity checks. Returns a list of problems (empty = clean)."""
    problems: list[str] = []
    policy = load_policy()
    claims = load_claims()
    truths = load_ground_truth()

    if set(claims) != set(truths):
        missing_gt = sorted(set(claims) - set(truths))
        orphan_gt = sorted(set(truths) - set(claims))
        if missing_gt:
            problems.append(f"claims without ground truth: {missing_gt}")
        if orphan_gt:
            problems.append(f"ground truth without claims: {orphan_gt}")

    for claim_id, gt in truths.items():
        bundle = claims.get(claim_id)
        if bundle is None:
            continue
        sched = bundle.policy_schedule

        for ref in gt.applicable_clauses + gt.violated_clauses:
            if ref not in policy.clause_ids:
                problems.append(f"{claim_id}: references unknown clause {ref}")

        if set(gt.documents_present) != bundle.doc_types:
            problems.append(
                f"{claim_id}: ground-truth documents_present "
                f"{sorted(d.value for d in gt.documents_present)} does not match bundle "
                f"{sorted(d.value for d in bundle.doc_types)}"
            )
        overlap = set(gt.documents_missing) & bundle.doc_types
        if overlap:
            problems.append(
                f"{claim_id}: documents_missing overlap with submitted docs: "
                f"{sorted(d.value for d in overlap)}"
            )
        try:
            required = set(required_documents_for(bundle.claim_type_filed.value))
            declared = set(gt.documents_present) | set(gt.documents_missing)
            if not required <= declared:
                problems.append(
                    f"{claim_id}: required documents not accounted for in ground truth: "
                    f"{sorted(d.value for d in required - declared)}"
                )
        except DatasetError as exc:
            problems.append(f"{claim_id}: {exc}")

        if gt.registration_number != sched.registration_number:
            problems.append(f"{claim_id}: registration mismatch with policy schedule")
        if gt.vehicle_type != sched.vehicle_type:
            problems.append(f"{claim_id}: vehicle_type mismatch with policy schedule")
        if gt.declared_vehicle_value != sched.declared_vehicle_value:
            problems.append(f"{claim_id}: declared value mismatch with policy schedule")
        if gt.reported_date != bundle.submitted_at:
            problems.append(f"{claim_id}: reported_date does not match submitted_at")
        if gt.incident_date and not (
            sched.policy_start <= gt.incident_date <= sched.policy_end
        ):
            problems.append(f"{claim_id}: incident date outside policy period")

    return problems
