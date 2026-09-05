"""Precomputed policy-clause embedding index.

Built once by scripts/build_policy_index.py (live Gemini call) and committed,
so the application never generates embeddings at startup or request time for
the policy side. The index stores a content hash of the policy clauses; if the
policy changes, loading fails loudly with PolicyIndexStaleError instead of
silently retrieving against stale vectors.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from claimiq.config import PACKAGE_DIR
from claimiq.data.schemas import Policy, PolicyClause

INDEX_PATH = PACKAGE_DIR / "data" / "policy_index.json"
DOCUMENT_TASK_TYPE = "RETRIEVAL_DOCUMENT"


class PolicyIndexError(Exception):
    """Index missing, unreadable, or structurally invalid."""


class PolicyIndexStaleError(PolicyIndexError):
    """The policy has changed since the index was built."""


def policy_content_hash(policy: Policy) -> str:
    """Stable hash over exactly the clause content that embeddings represent."""
    canonical = json.dumps(
        [[c.id, c.title, c.rule_type.value, c.text] for c in policy.clauses],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def clause_embedding_text(clause: PolicyClause) -> str:
    return f"{clause.title}\n{clause.text}"


def build_index_payload(policy: Policy, vectors: list[list[float]]) -> dict:
    """Assemble the JSON-ready index from clause-order-aligned vectors."""
    if len(vectors) != len(policy.clauses):
        raise PolicyIndexError(
            f"{len(policy.clauses)} clauses but {len(vectors)} vectors"
        )
    dims = {len(v) for v in vectors}
    if len(dims) != 1 or 0 in dims:
        raise PolicyIndexError(f"inconsistent embedding dimensions: {sorted(dims)}")
    from claimiq.config import settings

    return {
        "embedding_model": settings.gemini_embedding_model,
        "task_type": DOCUMENT_TASK_TYPE,
        "dimensions": dims.pop(),
        "policy_version": policy.version,
        "policy_hash": policy_content_hash(policy),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "clauses": [
            {
                "clause_id": clause.id,
                "title": clause.title,
                "rule_type": clause.rule_type.value,
                "embedding": [round(x, 6) for x in vector],
            }
            for clause, vector in zip(policy.clauses, vectors)
        ],
    }


def save_index(payload: dict, path: Path = INDEX_PATH) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


class PolicyIndex:
    """Loaded, validated index with a normalized vector matrix for cosine."""

    def __init__(self, policy: Policy, payload: dict):
        try:
            self.embedding_model: str = payload["embedding_model"]
            self.dimensions: int = payload["dimensions"]
            self.policy_hash: str = payload["policy_hash"]
            rows = payload["clauses"]
            self.clause_ids: list[str] = [r["clause_id"] for r in rows]
            matrix = np.array([r["embedding"] for r in rows], dtype=np.float64)
        except (KeyError, TypeError, ValueError) as exc:
            raise PolicyIndexError(f"Malformed policy index: {exc}") from exc

        if matrix.ndim != 2 or matrix.shape[1] != self.dimensions:
            raise PolicyIndexError(
                f"Index vectors are {matrix.shape}, expected (*, {self.dimensions})"
            )
        if self.policy_hash != policy_content_hash(policy):
            raise PolicyIndexStaleError(
                "The policy has changed since the index was built — regenerate it "
                "with: python scripts/build_policy_index.py"
            )
        if set(self.clause_ids) != policy.clause_ids:
            raise PolicyIndexStaleError(
                "Index clause IDs do not match the policy — regenerate the index."
            )

        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        if np.any(norms == 0):
            raise PolicyIndexError("Index contains a zero-magnitude vector")
        self._matrix = matrix / norms
        self._policy = policy

    def top_k(
        self, query_vector: list[float], k: int = 3, min_score: float = 0.0
    ) -> list[tuple[PolicyClause, float]]:
        """Cosine similarity of the query against every clause vector."""
        q = np.array(query_vector, dtype=np.float64)
        if q.shape != (self.dimensions,):
            raise PolicyIndexError(
                f"Query vector has {q.shape[0] if q.ndim == 1 else '?'} dimensions, "
                f"index has {self.dimensions}"
            )
        norm = np.linalg.norm(q)
        if norm == 0:
            raise PolicyIndexError("Query vector has zero magnitude")
        scores = self._matrix @ (q / norm)
        order = np.argsort(scores)[::-1][:k]
        results = []
        for i in order:
            score = float(scores[i])
            if score < min_score:
                continue
            clause = self._policy.clause_by_id(self.clause_ids[int(i)])
            results.append((clause, score))
        return results


def load_policy_index(policy: Policy, path: Path = INDEX_PATH) -> PolicyIndex:
    if not path.is_file():
        raise PolicyIndexError(
            f"Policy index not found at {path}. Generate it with: "
            f"python scripts/build_policy_index.py"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyIndexError(f"Could not read policy index: {exc}") from exc
    return PolicyIndex(policy, payload)
