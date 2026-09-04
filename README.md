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

Done so far:

- FastAPI app that starts with one command and serves everything on port 8000
- a fictional 17-clause motor policy (coverage, exclusions, claim windows,
  required documents, insured value) with stable clause IDs like `POL-05`, each
  carrying machine-readable parameters for the rule checks
- 8 synthetic claim bundles — each one keeps its documents as messy, realistic
  text (mixed date formats, blank fields, garage-estimate formatting) because
  that's what the extraction layer needs to be tested against
- ground truth for every claim plus tests that verify the dataset is coherent
  and the planted problems (contradictions, gaps) are really in the text

Being built next:

- Gemini extraction: turn the messy documents into structured facts, with
  unknowns marked as unknown
- a deterministic Python engine for the actual checks — document completeness,
  cross-document contradictions, date windows, insured value, exclusions —
  and the final APPROVE / REJECT / REQUEST_INFORMATION / ESCALATE call
- local retrieval over the policy clauses (`gemini-embedding-001`, precomputed
  embeddings, plain cosine similarity) so findings cite real clauses
- a simple review UI for walking through the evidence

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
  config.py             # env handling (.env loader, port, key)
  server.py             # FastAPI app factory + error handling
  api/routes.py         # endpoints (just /api/health for now)
  web/static/           # frontend served by the Python app
  data/
    policy.json         # the fictional policy (17 clauses)
    claims/             # 8 claim bundles, raw document text inside
    ground_truth.json   # expected facts/decisions, used only by tests
    schemas.py          # pydantic models shared by loader/engine/tests
    loader.py           # validated loading + dataset integrity checks
tests/
```

## Running locally

```text
pip install -r requirements.txt
python app.py
```

Then open http://localhost:8000. Python 3.11.

For the Gemini-powered parts (coming in later phases) set `GEMINI_API_KEY` —
copy `.env.example` to `.env` and fill it in. The app runs fine without a key;
AI features just report themselves as unavailable. Don't commit `.env`.

Tests:

```text
pytest
```
