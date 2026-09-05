"""Local policy-clause retrieval: Gemini query embedding + NumPy cosine.

Retrieval provides related policy context for explanation. It is NOT
authoritative: it never creates findings, never changes the decision, and the
clause IDs cited by the deterministic engine always outrank anything found
here. If retrieval fails, the review proceeds without it.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from claimiq.data.schemas import RuleType
from claimiq.extraction.gemini_client import GeminiClient, GeminiError
from claimiq.rag.index import PolicyIndex, PolicyIndexError

logger = logging.getLogger(__name__)

QUERY_TASK_TYPE = "RETRIEVAL_QUERY"
DEFAULT_TOP_K = 3
MIN_SCORE = 0.45  # below this, clauses are not similar enough to present


class RetrievedClause(BaseModel):
    clause_id: str
    title: str
    rule_type: RuleType
    text: str
    score: float


class RetrievalError(Exception):
    """Retrieval could not run (embedding failure or unusable index)."""


class PolicyRetriever:
    def __init__(self, index: PolicyIndex, client: GeminiClient):
        self._index = index
        self._client = client

    def retrieve(
        self, query: str, top_k: int = DEFAULT_TOP_K, min_score: float = MIN_SCORE
    ) -> list[RetrievedClause]:
        try:
            [vector] = self._client.embed([query], task_type=QUERY_TASK_TYPE)
        except GeminiError as exc:
            raise RetrievalError(f"query embedding failed: {exc}") from exc
        try:
            hits = self._index.top_k(vector, k=top_k, min_score=min_score)
        except PolicyIndexError as exc:
            raise RetrievalError(str(exc)) from exc
        results = [
            RetrievedClause(
                clause_id=clause.id,
                title=clause.title,
                rule_type=clause.rule_type,
                text=clause.text,
                score=round(score, 4),
            )
            for clause, score in hits
        ]
        logger.info(
            "retrieved %d clause(s) for query %r: %s",
            len(results), query[:60],
            ", ".join(f"{r.clause_id}:{r.score:.2f}" for r in results),
        )
        return results
