"""Extraction service: ClaimBundle -> validated ClaimEvidence.

One Gemini call per document (never one anonymous blob), so provenance is
structural: a fact extracted from the FIR can only have come from the FIR.
The extractor receives ONLY the claim's submitted documents — never ground
truth, expected decisions, or planted-contradiction metadata.

Failure behaviour:
- key missing            -> GeminiUnavailableError (raised immediately)
- one document fails     -> recorded in evidence.failed_documents, others continue
- every document fails   -> ExtractionError
"""

from __future__ import annotations

import logging

from claimiq.data.schemas import ClaimBundle, ClaimDocument
from claimiq.extraction import cache
from claimiq.extraction.gemini_client import (
    GeminiClient,
    GeminiError,
    GeminiUnavailableError,
)
from claimiq.extraction.prompts import PROMPT_VERSION, build_document_prompt
from claimiq.extraction.schemas import (
    ClaimEvidence,
    DocumentFacts,
    WireDocumentFacts,
)

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    """No usable evidence could be extracted for the claim."""


def _extract_document(
    client: GeminiClient, claim_id: str, doc: ClaimDocument, use_cache: bool
) -> DocumentFacts:
    key = cache.cache_key(client.model, PROMPT_VERSION, doc.doc_type.value, doc.text)
    if use_cache:
        cached = cache.get(key)
        if cached is not None:
            try:
                facts = DocumentFacts.model_validate(cached["facts"])
                logger.info("cache hit for %s/%s", claim_id, doc.doc_type.value)
                return facts
            except (KeyError, ValueError):
                logger.warning(
                    "cache entry for %s/%s invalid — refetching",
                    claim_id, doc.doc_type.value,
                )

    prompt = build_document_prompt(doc.doc_type, doc.text)
    facts = client.generate_validated(
        prompt,
        response_schema=WireDocumentFacts,
        parse=lambda raw: DocumentFacts.from_wire(
            WireDocumentFacts.model_validate_json(raw), document_text=doc.text
        ),
        context=f"{claim_id}/{doc.doc_type.value}",
    )
    if use_cache:
        cache.put(key, {"model": client.model, "facts": facts.model_dump(mode="json")})
    return facts


def extract_claim_evidence(
    bundle: ClaimBundle,
    client: GeminiClient | None = None,
    use_cache: bool = True,
) -> ClaimEvidence:
    """Extract validated, per-document evidence for one claim."""
    client = client or GeminiClient()
    if not client.available:
        raise GeminiUnavailableError(
            "GEMINI_API_KEY is not configured — evidence extraction is unavailable."
        )

    evidence = ClaimEvidence(claim_id=bundle.claim_id, model=client.model)
    for doc in bundle.documents:
        try:
            evidence.documents[doc.doc_type.value] = _extract_document(
                client, bundle.claim_id, doc, use_cache
            )
        except GeminiUnavailableError:
            raise
        except GeminiError as exc:
            logger.warning(
                "extraction failed for %s/%s: %s",
                bundle.claim_id, doc.doc_type.value, exc,
            )
            evidence.failed_documents[doc.doc_type.value] = str(exc)

    if not evidence.documents:
        raise ExtractionError(
            f"Extraction failed for every document of {bundle.claim_id}: "
            + "; ".join(
                f"{doc}: {err}" for doc, err in evidence.failed_documents.items()
            )
        )
    return evidence
