"""Dev tool: extract (Gemini, cached) then run the deterministic review engine.

Usage (from the repository root, with GEMINI_API_KEY configured):

    python scripts/review_claim.py                 # all 8 sample claims
    python scripts/review_claim.py CLM-002         # one claim, full findings

Ground truth is never consulted here — this shows what the engine concludes
from evidence + policy alone.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claimiq.data.loader import load_claims, get_claim  # noqa: E402
from claimiq.engine.engine import review_claim  # noqa: E402
from claimiq.extraction.extractor import ExtractionError, extract_claim_evidence  # noqa: E402
from claimiq.extraction.gemini_client import GeminiUnavailableError  # noqa: E402

EFFECT_MARK = {
    "NONE": " ",
    "BLOCK_REJECT": "X",
    "NEEDS_INFORMATION": "?",
    "NEEDS_ESCALATION": "!",
}


def review_one(claim_id: str, verbose: bool) -> str | None:
    bundle = get_claim(claim_id)
    try:
        evidence = extract_claim_evidence(bundle)
    except (GeminiUnavailableError, ExtractionError) as exc:
        print(f"{claim_id}: extraction unavailable ({exc})")
        return None
    review = review_claim(bundle, evidence)

    print(f"\n{'=' * 72}\n{claim_id} — {bundle.title}\n{'=' * 72}")
    print(f"DECISION: {review.decision.value}")
    print(f"WHY: {review.decision_rationale}")
    print(f"driven by: {', '.join(review.decision_reasons)}")
    print(f"\nfindings ({len(review.findings)}):")
    for f in review.findings:
        mark = EFFECT_MARK.get(f.effect.value, " ")
        clauses = f" [{', '.join(f.clause_ids)}]" if f.clause_ids else ""
        print(f"  {mark} {f.finding_id} {f.severity.value:8} {f.category.value:22} {f.title}{clauses}")
        if verbose:
            print(f"        {f.explanation}")
            for r in f.evidence:
                src = r.doc_type.value if r.doc_type else r.source
                quote = f' — "{(r.quote or "")[:60]}"' if r.quote else ""
                print(f"        · {src}.{r.field} = {r.value}{quote}")
    return review.decision.value


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    claim_ids = args or sorted(load_claims())
    verbose = len(claim_ids) == 1

    decisions: dict[str, str | None] = {}
    for claim_id in claim_ids:
        decisions[claim_id] = review_one(claim_id, verbose)

    print(f"\n{'=' * 72}\nSUMMARY\n{'=' * 72}")
    for claim_id, decision in decisions.items():
        print(f"  {claim_id}: {decision or 'EXTRACTION FAILED'}")


if __name__ == "__main__":
    main()
