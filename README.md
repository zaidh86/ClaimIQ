TRACK_ID=PS02

# ClaimIQ

My project for NexusTiQ 24 — an evidence review assistant for motor insurance
claims. When someone claims for a damaged or stolen bike/car, the insurer gets a
claim form, a repair estimate or FIR, and the customer's own version of events.
ClaimIQ reads those documents, checks them against a small fictional policy, and
shows an investigator what's missing, what contradicts what, and which policy
clauses actually apply — with every finding pointing back to the document and
clause it came from.

It's a review assistant, not an auto-decider. When the evidence doesn't support
a confident conclusion, it says so and escalates to a human instead of guessing.

## What it does

- FastAPI app that starts with one command and serves everything on port 8000
- a fictional 17-clause motor policy (coverage, exclusions, claim windows,
  required documents, insured value) with stable clause IDs like `POL-05`, each
  carrying machine-readable parameters for the rule checks
- 8 synthetic claim bundles — each one keeps its documents as messy, realistic
  text (mixed date formats, blank fields, garage-estimate formatting) because
  that's what the extraction layer needs to be tested against
- ground truth for every claim plus tests that verify the dataset is coherent
  and the planted problems (contradictions, gaps) are really in the text
- Gemini extraction: each document goes to Gemini separately (structured JSON
  output) and comes back as typed facts with a verbatim supporting quote per
  fact; quotes are re-checked against the source text in Python. Anything a
  document doesn't state is null — and when documents disagree, both versions
  are kept side by side instead of picking one
- the deterministic review engine: pure Python, no LLM anywhere in it. Eleven
  checks (document completeness, cross-document contradictions, timeline
  consistency, policy period, notification window, coverage, exclusions,
  driver/licence, theft requirements, insured value) read their thresholds
  from the policy's machine-readable parameters and emit structured findings,
  each tied to the documents, quotes and clause IDs behind it. The final
  APPROVE / REJECT / REQUEST_INFORMATION / ESCALATE call comes from fixed
  precedence rules over those findings — approval is never the default, and
  anything the evidence can't support gets escalated to a human

- the grounding layer: formal citations and a grounded explanation around the
  deterministic result. Document citations are built from the engine's own
  evidence references and validated against the stored extraction (a quote
  that was never verified stays visibly unverified); policy citations carry
  the exact clause text from `policy.json`. Policy clauses are embedded once
  with `gemini-embedding-001` (precomputed index committed to the repo — the
  app never generates embeddings at startup), and a small NumPy cosine
  retriever surfaces related clauses as context. Gemini
  (`gemini-3.5-flash-lite`) writes an investigator-facing explanation from
  *only* that grounded material — and a Python guard discards it if it
  mentions any clause or finding ID outside the supplied set. If Gemini or
  the index is unavailable, the review still completes with the
  deterministic rationale and a clear warning. Grounding can explain the
  decision; it structurally cannot change it

- the review UI: an investigator workbench served straight from the Python
  app. Pick one of the 8 sample claims, hit "Review claim", and walk through
  the decision, the findings with their verbatim quotes and verification
  marks, contradictions side by side, the cited policy clauses (clearly
  separated from merely-related retrieved context), and the grounded summary.
  If Gemini is down or unconfigured the UI says so and shows the
  deterministic rationale instead of breaking.

The split I'm sticking to throughout: Gemini only interprets text. All
verification, date/amount arithmetic, and decisions are plain Python. Nothing
gets stated without a citation.

## The sample claims

All data is made up — the insurer, policy wording, names, registrations, FIR
numbers, everything. The 8 cases are deliberately different:

- `CLM-001` — clean accident, should end in APPROVE
- `CLM-002` — claim form, statement and garage estimate disagree on the date,
  the driver and the registration → ESCALATE
- `CLM-003` — repair estimate never submitted → REQUEST_INFORMATION
- `CLM-004` — rider's own statement admits drinking before the crash → REJECT
- `CLM-005` — reported 24 days late against a 7-day window → REJECT
- `CLM-006` — repair estimate exceeds the declared vehicle value → ESCALATE
- `CLM-007` — theft claim, solid FIR, but key custody never addressed →
  REQUEST_INFORMATION
- `CLM-008` — laptop stolen *from* the car; no clause covers contents, so the
  system must not invent an answer → ESCALATE

## Project structure

```
app.py                  # entry point — python app.py runs everything
requirements.txt
claimiq/
  config.py             # env handling (.env loader, port, key, model)
  server.py             # FastAPI app factory + error handling
  api/routes.py         # /api/health, /api/claims, /api/claims/{id}, .../review
  web/static/           # frontend served by the Python app
  data/
    policy.json         # the fictional policy (17 clauses)
    claims/             # 8 claim bundles, raw document text inside
    ground_truth.json   # expected facts/decisions, used only by tests
    extraction_seed/    # committed extractions for the sample claims (facts only)
    schemas.py          # pydantic models shared by loader/engine/tests
    loader.py           # validated loading + dataset integrity checks
  extraction/
    gemini_client.py    # the only module that talks to Gemini; typed failures
    schemas.py          # wire schema for Gemini + validated evidence models
    prompts.py          # per-document extraction prompt (versioned for cache)
    extractor.py        # extract_claim_evidence(bundle) -> ClaimEvidence
    cache.py            # sha256-keyed cache: .cache/ (local) + the committed seed
  engine/
    checks.py           # the eleven deterministic checks + field consensus views
    engine.py           # review_claim(bundle, evidence) -> decision + findings
    schemas.py          # Finding, severities, effects, ClaimReview
  rag/
    index.py            # precomputed clause-embedding index + staleness hash
    retriever.py        # query embedding + NumPy cosine top-k
    citations.py        # document/policy citations, built and validated in Python
    grounded.py         # GroundedReview: citations + context + guarded explanation
  record/
    correspondence.py   # the decision's artifact: letter, rationale or handoff memo
    matrix.py           # evidence reconciliation grid across documents
    timeline.py         # chronology of the dates the file actually states
    hints.py            # what evidence could resolve a contradiction
  data/policy_index.json  # committed embeddings (gemini-embedding-001)
scripts/
  extract_claim.py      # dev tool: run live extraction and inspect evidence
  review_claim.py       # dev tool: extraction + engine, full review printout
  grounded_review.py    # dev tool: the full grounded pipeline for a claim
  build_policy_index.py # regenerates the policy index (only after policy edits)
  seed_extraction_cache.py  # regenerates the committed extraction seed
tests/
```

The split between the two layers is strict: Gemini reads documents, Python
decides. The engine never calls the network, never sees ground truth, and
produces the identical review every time for the same evidence.

## How extraction works

Gemini's only job is reading: each submitted document is sent in its own call
and must return facts as strict JSON — value plus a verbatim quote — validated
through pydantic (one repair retry, then a typed failure). Python then
re-verifies every quote against the actual document text and marks it
verified/unverified. Extraction never sees the ground truth and never makes
claim decisions; the approve/reject logic lives entirely in the deterministic
engine. Results are cached locally by content hash so re-running reviews
doesn't burn API calls; delete `.cache/` to invalidate. The model is
configurable via `GEMINI_MODEL` (default `gemini-3.5-flash-lite`).

If no API key is set, the app still runs — extraction reports itself
unavailable with a clear message instead of crashing.

## Running locally

```text
pip install -r requirements.txt
python app.py
```

Then open http://localhost:8000. Python 3.11.

The whole app (API + UI) is served by that one command. The workflow in the
browser: pick a claim from the left rail → "Review claim" → read the decision
banner, then work down through the summary, contradictions, findings, evidence
quotes, and policy clauses. The sample claims ship with a committed extraction seed, so a review takes a
few seconds (mostly the Gemini grounding step); a claim whose documents are
not seeded is extracted live first, which can take ~15–30 seconds.
API endpoints, if you want them directly: `GET /api/claims`,
`GET /api/claims/{id}`, `POST /api/claims/{id}/review`, `GET /api/health`.

Live reviews need a Gemini API key: set `GEMINI_API_KEY` in the environment,
or copy `.env.example` to `.env` and fill it in. The app starts and serves
fine without one — reviews then report Gemini as unavailable with a clear
message instead of crashing. The policy embedding index ships precomputed in
the repo, so nothing needs to be generated before first run. Don't commit `.env`.

Tests:

```text
pytest
```

Development history, phase by phase: [docs/PROJECT_PROGRESS.md](docs/PROJECT_PROGRESS.md).
