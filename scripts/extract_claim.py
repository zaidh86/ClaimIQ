"""Dev tool: run live Gemini extraction against sample claims and inspect it.

Usage (from the repository root, with GEMINI_API_KEY configured):

    python scripts/extract_claim.py                  # CLM-001 CLM-002 CLM-007
    python scripts/extract_claim.py CLM-004          # specific claims
    python scripts/extract_claim.py --no-cache       # force fresh API calls

Not part of the judged app — a development aid for verifying extraction
behaviour (conflict preservation, unknown handling) against real model output.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claimiq.data.loader import get_claim  # noqa: E402
from claimiq.extraction.extractor import ExtractionError, extract_claim_evidence  # noqa: E402
from claimiq.extraction.gemini_client import GeminiClient, GeminiUnavailableError  # noqa: E402


def show(claim_id: str, use_cache: bool) -> None:
    bundle = get_claim(claim_id)
    print(f"\n{'=' * 70}\n{claim_id} — {bundle.title}\n{'=' * 70}")
    try:
        evidence = extract_claim_evidence(bundle, use_cache=use_cache)
    except (GeminiUnavailableError, ExtractionError) as exc:
        print(f"  EXTRACTION FAILED (gracefully): {exc}")
        return

    print(f"model: {evidence.model}")
    print(f"documents extracted: {sorted(evidence.documents)}")
    if evidence.failed_documents:
        print(f"documents FAILED: {evidence.failed_documents}")

    by_field: dict[str, list] = defaultdict(list)
    for obs in evidence.observations():
        by_field[obs.field].append(obs)

    for field in sorted(by_field):
        observations = by_field[field]
        values = {repr(o.value) for o in observations}
        marker = "  <-- MULTIPLE VALUES" if len(values) > 1 else ""
        print(f"\n  {field}:{marker}")
        for o in observations:
            check = "verified" if o.quote_verified else "UNVERIFIED"
            quote = (o.quote or "")[:70].replace("\n", " ")
            print(f"    [{o.doc_type.value}] {o.value!r}  ({check}: \"{quote}\")")

    risks = evidence.risk_observations()
    if risks:
        print("\n  risk_mentions:")
        for doc_type, mention in risks:
            print(f"    [{doc_type.value}] {mention.risk_type}: \"{mention.quote[:80]}\"")

    for doc_value, facts in evidence.documents.items():
        if facts.incident_summary:
            print(f"\n  summary[{doc_value}]: {facts.incident_summary}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("claims", nargs="*", default=["CLM-001", "CLM-002", "CLM-007"])
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    client = GeminiClient()
    if not client.available:
        print("GEMINI_API_KEY is not configured - cannot run live extraction.")
        print("Set it in the environment or .env, then re-run this script.")
        sys.exit(1)

    for claim_id in args.claims:
        show(claim_id, use_cache=not args.no_cache)


if __name__ == "__main__":
    main()
