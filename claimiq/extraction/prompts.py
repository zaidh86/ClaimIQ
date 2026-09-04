"""Prompt construction for per-document evidence extraction.

PROMPT_VERSION participates in the cache key: bumping it invalidates every
cached extraction, so prompt changes can never serve stale results.
"""

from __future__ import annotations

from claimiq.data.schemas import DocType

PROMPT_VERSION = "1"

_DOC_TYPE_LABELS = {
    DocType.CLAIM_FORM: "the insurer's motor claim form filled in by the claimant",
    DocType.REPAIR_ESTIMATE: "a garage/workshop repair estimate or job card",
    DocType.FIR: "a police FIR or police complaint copy",
    DocType.INCIDENT_DESCRIPTION: "the customer's own written description of the incident",
}

_RULES = """You are the evidence-extraction step of ClaimIQ, an insurance claim review tool.
You are given ONE document from a motor insurance claim file. Report only facts
that THIS document itself states, in the JSON schema provided.

Hard rules:
1. If this document does not state a fact, use null for it. Never guess, never
   infer from what is typical, never fill fields from general knowledge.
2. A form field that exists but is left blank means the fact is NOT stated: null.
3. Every "quote" must be copied verbatim, character-for-character, from the
   document (keep each under ~200 characters).
4. Normalize formatting only — never content:
   - Dates: output YYYY-MM-DD. These documents write dates day-first
     (18/02/2026 means 18 February 2026) or in words (14th February 2026).
   - Registration numbers: uppercase, remove spaces and hyphens.
   - Amounts: whole rupees as an integer, commas and "Rs." removed.
   Never "correct" digits, spellings, or apparent typos — report exactly the
   characters the document contains, even if they look wrong.
5. If an amount is stated non-numerically ("as per declared value", "to follow"),
   put that statement in claimed_amount_note and leave claimed_amount null.
6. Report this document's own version of events even if you suspect it is
   inaccurate. Do not reconcile anything with other documents.
7. risk_mentions: quote any statement about driver alcohol/drug consumption,
   commercial use, racing/speed trials, or the vehicle being left unlocked or
   with keys in it. Empty list if none.
8. incident_summary: one or two sentences on what THIS document says happened."""


def build_document_prompt(doc_type: DocType, text: str) -> str:
    label = _DOC_TYPE_LABELS.get(doc_type, "a claim document")
    return (
        f"{_RULES}\n\n"
        f"Document type: {doc_type.value} ({label})\n"
        f"--- DOCUMENT START ---\n"
        f"{text}\n"
        f"--- DOCUMENT END ---"
    )
