"""Dev tool: full grounded pipeline — extraction -> engine -> citations,
retrieval and Gemini explanation.

    python scripts/grounded_review.py CLM-001 CLM-002 CLM-008
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claimiq.data.loader import get_claim  # noqa: E402
from claimiq.engine.engine import review_claim  # noqa: E402
from claimiq.extraction.extractor import ExtractionError, extract_claim_evidence  # noqa: E402
from claimiq.extraction.gemini_client import GeminiUnavailableError  # noqa: E402
from claimiq.rag.grounded import ground_review  # noqa: E402


def show(claim_id: str) -> None:
    bundle = get_claim(claim_id)
    print(f"\n{'=' * 72}\n{claim_id} — {bundle.title}\n{'=' * 72}")
    try:
        evidence = extract_claim_evidence(bundle)
    except (GeminiUnavailableError, ExtractionError) as exc:
        print(f"extraction unavailable: {exc}")
        return
    review = review_claim(bundle, evidence)
    grounded = ground_review(bundle, evidence, review)

    print(f"DECISION (deterministic): {review.decision.value}")
    print(f"explanation source: {grounded.explanation_source}")

    valid_doc = [c for c in grounded.document_citations if c.valid]
    print(f"\ndocument citations: {len(valid_doc)} valid / {len(grounded.document_citations)} total")
    for c in valid_doc[:5]:
        flag = "verified" if c.quote_verified else "UNVERIFIED"
        print(f"  [{c.finding_id}] {c.doc_type}.{c.field} = {c.value} ({flag})")
    print(f"policy citations: {len(grounded.policy_citations)}")
    for c in grounded.policy_citations[:8]:
        print(f"  [{c.finding_id}] {c.clause_id} — {c.title}")

    if grounded.retrieved_context:
        print("retrieved context:")
        for c in grounded.retrieved_context:
            cited = " (already cited)" if c.already_cited else ""
            print(f"  {c.clause_id} score={c.score}{cited} — {c.reason}")

    if grounded.explanation:
        e = grounded.explanation
        print(f"\nSUMMARY: {e.summary}")
        for point in e.key_points:
            print(f"  * {point}")
        if e.investigator_note:
            print(f"INVESTIGATOR NOTE: {e.investigator_note}")
    else:
        print(f"\nFALLBACK RATIONALE: {review.decision_rationale}")

    if grounded.warnings:
        print("\nwarnings:")
        for w in grounded.warnings:
            print(f"  ! {w}")


def main() -> None:
    claim_ids = sys.argv[1:] or ["CLM-001", "CLM-002", "CLM-008"]
    for claim_id in claim_ids:
        show(claim_id)


if __name__ == "__main__":
    main()
