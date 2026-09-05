"""Build the precomputed policy-clause embedding index (development tool).

    python scripts/build_policy_index.py

Requires GEMINI_API_KEY. Embeds every policy clause with the configured
embedding model (gemini-embedding-001) and writes
claimiq/data/policy_index.json, which is committed so the application never
needs to generate embeddings at startup. Re-run this whenever policy.json
changes — the app detects a stale index and refuses to use it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claimiq.config import settings  # noqa: E402
from claimiq.data.loader import load_policy  # noqa: E402
from claimiq.extraction.gemini_client import GeminiClient, GeminiError  # noqa: E402
from claimiq.rag.index import (  # noqa: E402
    DOCUMENT_TASK_TYPE,
    INDEX_PATH,
    build_index_payload,
    clause_embedding_text,
    load_policy_index,
    save_index,
)


def main() -> int:
    client = GeminiClient()
    if not client.available:
        print("GEMINI_API_KEY is not configured - cannot build the index.")
        return 1

    policy = load_policy()
    texts = [clause_embedding_text(c) for c in policy.clauses]
    print(f"Embedding {len(texts)} policy clauses with {settings.gemini_embedding_model}...")
    try:
        vectors = client.embed(texts, task_type=DOCUMENT_TASK_TYPE)
    except GeminiError as exc:
        print(f"Embedding failed: {exc}")
        return 1

    payload = build_index_payload(policy, vectors)
    save_index(payload)
    print(
        f"Wrote {INDEX_PATH} — {payload['dimensions']} dimensions, "
        f"policy hash {payload['policy_hash'][:12]}..."
    )

    # Round-trip validation: the app must be able to load what we just wrote.
    index = load_policy_index(policy)
    print(f"Validated: index loads cleanly with {len(index.clause_ids)} clauses.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
