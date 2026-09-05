"""Seed the committed extraction cache (development tool).

    python scripts/seed_extraction_cache.py            # fill in what's missing
    python scripts/seed_extraction_cache.py --check     # verify only, no writes
    python scripts/seed_extraction_cache.py --force     # re-extract everything live

Writes one validated extraction per (model, prompt version, document) into
claimiq/data/extraction_seed/, using the same content-hash key as the runtime
cache. A fresh clone can then review the sample claims without re-extracting
every document, while any change to a document, the prompt, or the model
misses the seed and falls back to live extraction.

For each document the seed is taken from, in order: an existing valid seed
entry, the local runtime cache (.cache/extraction/), or a live Gemini call
(needs GEMINI_API_KEY). Every candidate is schema-validated AND has its quotes
re-verified against the document text before being written, so an entry that
cannot be substantiated never reaches the repository.

Seeded files contain extracted facts only — no decisions, no expected
outcomes, no scenario labels, no ground truth, no keys, no local paths.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claimiq.data.loader import load_claims  # noqa: E402
from claimiq.data.schemas import ClaimBundle, ClaimDocument  # noqa: E402
from claimiq.extraction import cache  # noqa: E402
from claimiq.extraction.extractor import reverify_quotes  # noqa: E402
from claimiq.extraction.gemini_client import (  # noqa: E402
    GeminiClient,
    GeminiError,
)
from claimiq.extraction.prompts import PROMPT_VERSION, build_document_prompt  # noqa: E402
from claimiq.extraction.schemas import (  # noqa: E402
    DocumentFacts,
    WireDocumentFacts,
)

# Keys that must never appear in a committed seed artifact.
FORBIDDEN_KEYS = {
    "scenario", "expected_decision", "ground_truth", "decision",
    "api_key", "gemini_api_key", "notes",
}


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _validated(payload: dict, doc: ClaimDocument) -> DocumentFacts | None:
    """Schema-validate a candidate payload and re-verify its quotes."""
    try:
        facts = DocumentFacts.model_validate(payload["facts"])
    except (KeyError, TypeError, ValueError):
        return None
    return reverify_quotes(facts, doc.text)


def _seed_payload(
    model: str, claim: ClaimBundle, doc: ClaimDocument, facts: DocumentFacts
) -> dict:
    return {
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "claim_id": claim.claim_id,      # auditability only; never read at runtime
        "doc_type": doc.doc_type.value,  # auditability only; never read at runtime
        "facts": facts.model_dump(mode="json"),
    }


def _write_seed(key: str, payload: dict) -> None:
    cache.SEED_DIR.mkdir(parents=True, exist_ok=True)
    (cache.SEED_DIR / f"{key}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _extract_live(client: GeminiClient, claim_id: str, doc: ClaimDocument) -> DocumentFacts:
    return client.generate_validated(
        build_document_prompt(doc.doc_type, doc.text),
        response_schema=WireDocumentFacts,
        parse=lambda raw: DocumentFacts.from_wire(
            WireDocumentFacts.model_validate_json(raw), document_text=doc.text
        ),
        context=f"{claim_id}/{doc.doc_type.value}",
    )


def audit_seed_directory() -> list[str]:
    """Check every committed seed file for content that must not be there."""
    problems: list[str] = []
    for path in sorted(cache.SEED_DIR.glob("*.json")):
        raw = path.read_text(encoding="utf-8")
        lowered = raw.lower()
        for forbidden in FORBIDDEN_KEYS:
            if f'"{forbidden}"' in lowered:
                problems.append(f"{path.name}: contains forbidden key '{forbidden}'")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            problems.append(f"{path.name}: invalid JSON ({exc})")
            continue
        if set(payload) != {"model", "prompt_version", "claim_id", "doc_type", "facts"}:
            problems.append(f"{path.name}: unexpected top-level keys {sorted(payload)}")
        if path.stem != path.stem.lower() or len(path.stem) != 64:
            problems.append(f"{path.name}: filename is not a sha256 content hash")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify the seed is complete and valid; write nothing")
    parser.add_argument("--force", action="store_true",
                        help="ignore existing entries and re-extract live")
    args = parser.parse_args()

    client = GeminiClient()
    model = client.model
    claims = load_claims()
    total = sum(len(c.documents) for c in claims.values())
    print(f"Model: {model} · prompt version {PROMPT_VERSION} · "
          f"{len(claims)} claims / {total} documents")
    print(f"Seed directory: {cache.SEED_DIR}")

    kept = from_runtime = from_live = missing = invalid = 0

    for claim_id in sorted(claims):
        claim = claims[claim_id]
        for doc in claim.documents:
            key = cache.cache_key(model, PROMPT_VERSION, doc.doc_type.value, doc.text)
            label = f"{claim_id}/{doc.doc_type.value}"
            seed_path = cache.SEED_DIR / f"{key}.json"

            if not args.force and seed_path.is_file():
                payload = _read_json(seed_path)
                facts = _validated(payload, doc) if payload else None
                if facts is None:
                    print(f"  INVALID seed  {label} ({seed_path.name})")
                    invalid += 1
                else:
                    kept += 1
                continue

            if args.check:
                print(f"  MISSING       {label}")
                missing += 1
                continue

            runtime = None if args.force else _read_json(cache.CACHE_DIR / f"{key}.json")
            facts = _validated(runtime, doc) if runtime else None
            if facts is not None:
                _write_seed(key, _seed_payload(model, claim, doc, facts))
                print(f"  seeded (local cache)  {label}")
                from_runtime += 1
                continue

            if not client.available:
                print(f"  MISSING       {label} (no runtime cache and no GEMINI_API_KEY)")
                missing += 1
                continue
            try:
                facts = _extract_live(client, claim_id, doc)
            except GeminiError as exc:
                print(f"  FAILED        {label}: {exc}")
                missing += 1
                continue
            facts = reverify_quotes(facts, doc.text)
            _write_seed(key, _seed_payload(model, claim, doc, facts))
            print(f"  seeded (live Gemini)  {label}")
            from_live += 1

    print(
        f"\nValid existing: {kept} · from local cache: {from_runtime} · "
        f"live: {from_live} · missing/invalid: {missing + invalid}"
    )

    problems = audit_seed_directory()
    if problems:
        print("\nSeed audit FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    files = sorted(cache.SEED_DIR.glob("*.json"))
    size_kb = sum(p.stat().st_size for p in files) / 1024
    print(f"Seed audit passed: {len(files)} files, {size_kb:.0f} KB, facts only.")
    return 1 if (missing or invalid) else 0


if __name__ == "__main__":
    sys.exit(main())
