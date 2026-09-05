"""Extraction service: ClaimBundle -> validated ClaimEvidence.

One Gemini call per document (never one anonymous blob), so provenance is
structural: a fact extracted from the FIR can only have come from the FIR.
The extractor receives ONLY the claim's submitted documents — never ground
truth, expected decisions, or planted-contradiction metadata.

Cached extractions are never trusted on their word: whatever comes back from
the cache is re-validated against the schema and every quote is re-verified
against the actual document text. Verification can therefore only ever be
downgraded by the cache, never upgraded — a hand-edited or stale cache entry
cannot assert that an absent quote appears in the document.

Where each document's facts came from is recorded in
`evidence.document_sources` ("live" / "runtime_cache" / "seed_cache") so the
UI can describe extraction provenance truthfully.

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
    quote_appears_in,
)

logger = logging.getLogger(__name__)

_QUOTELESS_FIELDS = ("incident_summary", "risk_mentions")


class ExtractionError(Exception):
    """No usable evidence could be extracted for the claim."""


def reverify_quotes(facts: DocumentFacts, document_text: str) -> DocumentFacts:
    """Recompute every quote_verified flag against the real document text.

    Applied to anything served from a cache. A stored `true` for a quote that
    does not appear in the document becomes `false`; verification is never
    taken on trust and never upgraded by cached data.
    """
    data = facts.model_dump()
    for name, value in data.items():
        if name in _QUOTELESS_FIELDS or not isinstance(value, dict):
            continue
        if "quote" in value:
            value["quote_verified"] = quote_appears_in(
                value.get("quote") or "", document_text
            )
    for mention in data.get("risk_mentions", []):
        mention["quote_verified"] = quote_appears_in(
            mention.get("quote") or "", document_text
        )
    return DocumentFacts.model_validate(data)


def _extract_document(
    client: GeminiClient, claim_id: str, doc: ClaimDocument, use_cache: bool
) -> tuple[DocumentFacts, str]:
    """Return this document's facts and where they came from."""
    key = cache.cache_key(client.model, PROMPT_VERSION, doc.doc_type.value, doc.text)
    if use_cache:
        hit = cache.lookup(key)
        if hit is not None:
            try:
                facts = DocumentFacts.model_validate(hit.payload["facts"])
                facts = reverify_quotes(facts, doc.text)
                logger.info(
                    "%s hit for %s/%s", hit.source, claim_id, doc.doc_type.value
                )
                return facts, hit.source
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning(
                    "%s entry for %s/%s invalid (%s) — extracting live",
                    hit.source, claim_id, doc.doc_type.value, exc,
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
    return facts, "live"


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
            facts, source = _extract_document(
                client, bundle.claim_id, doc, use_cache
            )
            evidence.documents[doc.doc_type.value] = facts
            evidence.document_sources[doc.doc_type.value] = source
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
