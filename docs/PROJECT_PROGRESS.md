# ClaimIQ — Project Progress and Engineering History

ClaimIQ is an evidence review assistant for motor insurance claims, built for
NexusTiQ 24, Track PS02 ("Insurance — Claims Evidence Review Assistant"). This
document records how the project was built, phase by phase, from the first
commit to the final polish pass before submission.

It is an engineering record, not a changelog and not a pitch. Every phase below
is tied to the repository evidence that supports it: commit hashes and
messages, the files each commit touched, and the number of tests collected at
each commit (measured by checking out every commit and running
`pytest --collect-only`). Where a fact comes from the development sessions
rather than from the repository — a timing measured during a phase, a bug that
was fixed before its phase was committed — it is labelled as such. Where
something could not be verified, it is either phrased cautiously or left out.

All twelve implementation commits carry the same date, 2026-09-05. The project
was built in a single concentrated effort, in thirteen phases, one of which
(Phase 10) was research only and produced no commit. This record itself was
added afterwards in a documentation-only commit.

## Phase map

| Phase | Name | Type | Commit | Tests collected after |
|---|---|---|---|---|
| 1 | Foundation | implementation | `5151b0f` | 5 |
| 2 | Policy + Synthetic Dataset | implementation | `90a0dff` | 22 |
| 3 | Gemini Extraction | implementation | `a230788` | 49 |
| 4 | Deterministic Review Engine | implementation | `a4445f8` | 77 |
| 5 | Grounded RAG + Formal Citations | implementation | `e4cee9f` | 106 |
| 6 | Functional MVP UI | implementation | `9ed8c70` | 124 |
| 7 | Investigator UX + Citation Interaction | implementation | `b0ec756` | 124 |
| 8 | Hardening + Judge Simulation | testing / hardening | `64e93f8` | 124 |
| 9 | Trust, Explainability & Human-Readable UX | implementation | `c698afc` | 124 |
| 10 | Competitive Research & Product Differentiation | research / strategy | none | 124 |
| 11 | The Adjudication Record | implementation | `a5611b1` | 199 |
| 12 | Caseload + Demo Armor | implementation | `7041d75` | 233 |
| 13 | Final UI Polish | polish | `0a251fc` | 233 |

The working rules that held for the whole project: the developer never
committed — every commit was inspected and made by the project owner after a
phase report; Gemini was the only external API allowed; the application had to
start with `python app.py` on port 8000 in the hackathon's Python 3.11 judge
environment with no build step and no second process; and the README's first
line had to be exactly `TRACK_ID=PS02`.

---

## Phase 1 — Foundation

**Status:** complete. **Commit:** `5151b0f` — *feat: initialize ClaimIQ PS02
foundation* (13 files, 475 insertions).

### Objective

Put in place the smallest application that satisfies the judging contract —
one Python entry point, one port, one requirements file, served frontend, a
health endpoint — so every later phase could be added without ever changing how
the application is run.

### What was built

- `app.py` — the single runnable entry point; calls `uvicorn.run` with the
  configured host and port and logs the URL to open.
- `claimiq/server.py` — a `create_app()` FastAPI application factory, kept
  separate from `app.py` so tests can build the application without starting a
  server. It registers the API router, serves `index.html` at `/`, mounts
  `/static`, and installs two global handlers: request-validation errors become
  JSON 422 responses and any unhandled exception becomes a JSON 500 with the
  exception type and message but no stack trace.
- `claimiq/api/routes.py` — initially only `GET /api/health`, which reports the
  application name, version, track ID, whether Gemini is configured and a UTC
  timestamp (the model name was added to the health response in Phase 3). It
  never returns the key itself. FastAPI's interactive API documentation is
  enabled at `/api/docs`.
- `claimiq/__init__.py` — the package name, version (`0.1.0`) and track ID that
  the health endpoint and the server report.
- `claimiq/config.py` — a frozen `Settings` dataclass built from the
  environment, plus a minimal `.env` loader so a judge can drop a key into a
  file without extra tooling. Real environment variables always win over the
  `.env` file. Recognised at this point: `GEMINI_API_KEY`, `HOST`, `PORT` and
  `LOG_LEVEL`; `GEMINI_MODEL` and `GEMINI_TIMEOUT_SECONDS` followed in Phase 3
  and `GEMINI_EMBEDDING_MODEL` in Phase 5.
- `claimiq/web/static/index.html` — a 99-line placeholder frontend served by
  the Python app.
- `requirements.txt` (pinned), `.env.example`, `.gitignore` (with `.env`
  listed first), `README.md` starting with `TRACK_ID=PS02`, and
  `tests/test_app.py`.

### Engineering decisions

- **Everything is served by the Python process.** The frontend is a static file
  the FastAPI app serves; there is no Node toolchain, no build step and no
  second server. This was a hackathon constraint, but it also kept the
  frontend honest for the rest of the project: it can only render what the
  backend sends.
- **The app must start without a Gemini key.** From the first commit,
  Gemini-dependent features were designed to degrade to a clear message rather
  than crash at boot. `/api/health` reports `gemini_configured` as a boolean.
- **Bind `0.0.0.0`, tell the user `localhost`.** The server binds all interfaces
  (overridable with `HOST`), while `app.py`, the startup log line and the README
  all point at `http://localhost:8000`, which is the address a judge actually
  opens. The log line prints the exact URL for that reason.
- **Python 3.11 is the target environment.** It is stated in the README and in
  the header of `requirements.txt`. No aliases, shell symlinks or OS-specific
  command sets are part of the project; the contract is the hackathon's stated
  Python 3.11 environment with `pip install -r requirements.txt` followed by
  `python app.py`.
- **Test dependencies live in the one requirements file** so that `pytest`
  works immediately after the single install a judge performs.

### Testing

Five tests: health endpoint, index served, unknown API routes answer with JSON
404, default port is 8000, README first line is the track ID.

### Issues

None recorded for this phase.

### Outcome

A skeleton that already behaved like the final product from the judge's side:
install, run, open the port.

---

## Phase 2 — Policy + Synthetic Dataset

**Status:** complete. **Commit:** `90a0dff` — *feat: add fictional policy and
synthetic claim dataset with ground truth* (15 files, 1,294 insertions).

### Objective

The hackathon provided no policy corpus and no claims dataset. Everything the
system would later reason about had to be created: a fictional but structurally
realistic motor policy, a corpus of claims with messy documents, and a
test-only description of what is true about each claim.

### What was built

**The policy.** `claimiq/data/policy.json` describes *Nimbus General Insurance
Co. Ltd. (fictional)*, product *NimbusMotor Secure - Private Vehicle Package
Policy*, version NMS/2025/1, in 17 clauses with stable IDs:

| ID | Rule type | Title |
|---|---|---|
| POL-01 | DEFINITION | Eligible Vehicles and Scope |
| POL-02 | COVERAGE | Cover A - Accidental Damage to the Insured Vehicle |
| POL-03 | COVERAGE | Cover B — Theft of the Insured Vehicle |
| POL-04 | LIMIT | Declared Vehicle Value (DVV) - Limit of Liability |
| POL-05 | CLAIM_WINDOW | Accident Claim Notification Window |
| POL-06 | CLAIM_WINDOW | Theft Claim Notification Window |
| POL-07 | REQUIRED_DOCUMENTS | Documents Required for Accident Claims |
| POL-08 | REQUIRED_DOCUMENTS | Documents Required for Theft Claims |
| POL-09 | CONDITION | Theft Claim Conditions - FIR and Keys |
| POL-10 | CONDITION | Valid Driving Licence and Driver Consistency |
| POL-11 | CONDITION | Policy Period |
| POL-12 | EXCLUSION | Exclusion - Driving Under the Influence |
| POL-13 | EXCLUSION | Exclusion - Commercial Use |
| POL-14 | EXCLUSION | Exclusion - Racing and Speed Trials |
| POL-15 | EXCLUSION | Exclusion - Wear, Tear and Breakdown |
| POL-16 | EXCLUSION | Exclusion - Theft of an Unsecured Vehicle |
| POL-17 | EXCLUSION | Exclusion - Deliberate Acts |

Every clause carries human-readable text and — with the single exception of
POL-11, whose `parameters` object is empty because the policy dates come from
the schedule — machine-readable `parameters` (for example `max_report_days`, `counted_from`, `required_documents`,
`fir_max_hours_after_discovery`, `keys_confirmation_required`,
`licence_required`, `applies_to`). The later engine reads its thresholds from
these parameters and hardcodes none of them.

**The claims.** Eight bundles in `claimiq/data/claims/`, each with a trusted
policy schedule (policyholder, vehicle, registration, declared value, policy
period) and two or three submitted documents kept as raw, messy text: day-first
dates, dates written in words, blank form fields, garage-estimate formatting,
emails and written statements. Six are accident claims and two are theft
claims; document types are claim form, repair estimate, FIR and incident
description.

| Claim | Filed as | Documents | Scenario the file was written to exercise |
|---|---|---|---|
| CLM-001 | accident | form, estimate, description | a clean, consistent file |
| CLM-002 | accident | form, estimate, description | documents disagree on the incident date, the driver and the registration; the garage received the vehicle before the form's incident date |
| CLM-003 | accident | form, description | the repair estimate was never submitted; the amount is "to follow" |
| CLM-004 | accident | form, estimate, description | the rider's own statement admits drinking before the crash |
| CLM-005 | accident | form, estimate, description | reported 24 days after the incident against a 7-day window |
| CLM-006 | accident | form, estimate, description | the repair estimate exceeds the declared vehicle value |
| CLM-007 | theft | form, FIR, description | a solid FIR, but the claim form's keys field is blank and no other document mentions the keys at all |
| CLM-008 | theft | form, FIR, description | a laptop stolen *from* the car; the vehicle itself was not taken and no clause covers contents |

**Ground truth.** `claimiq/data/ground_truth.json` records, per claim, the true
facts, the planted contradictions, the missing information, the applicable and
violated clauses and the expected decision. It is validated through the same
pydantic schemas as the rest of the dataset so tests and engine can never
drift apart — but it is **test-only**. Only the dataset loader knows how to
read it; no engine, extraction, RAG or API module calls that loader function,
no production code path invokes the dataset integrity check that uses it, and
no API endpoint serves it. The claim bundles' internal `scenario` authoring
tag is never exposed either. The ground-truth separation is asserted by tests
from Phase 3 onward; non-exposure of the `scenario` tag is asserted from
Phase 6 onward, once an API existed that could leak it.

**Schemas and loader.** `claimiq/data/schemas.py` defines the vocabulary
(`RuleType`, `DocType`, `ClaimType`, `Decision`, `PolicyClause`, `Policy`,
`ClaimDocument`, `PolicySchedule`, `ClaimBundle`, `GroundTruth`), with
validators for unique clause IDs and unique document types per bundle.
`claimiq/data/loader.py` loads and validates everything with cached loaders
and a `validate_dataset()` integrity check that fails loudly on malformed
data.

The README was rewritten in this phase in a plain, first-person voice at the
owner's request, replacing the Phase 1 version.

### Engineering decisions

- **Policy rules are data, not prose to be interpreted by a model.** Putting
  numbers and document lists in `parameters` is what later allowed the
  decision engine to be deterministic and the UI to show the exact rule value
  a check used.
- **Documents stay messy on purpose.** Clean, pre-structured data would have
  tested nothing about extraction.
- **Ground truth never duplicates the final answer as an application
  feature.** It exists to prove the dataset is coherent and that the planted
  problems really are in the text.

### Testing

Seventeen dataset tests (22 total): cross-file integrity, policy size and
rule-category coverage, required documents for both claim types, unique and
complete claims, every referenced clause exists, all decision categories
appear, documents are realistic raw text, and one test per scenario proving
the planted condition is present — the clean case is clean, the contradiction
case has material contradictions, the window case really breaches the window,
the theft case's keys are genuinely unknown, the contents-theft case is out of
scope.

### Issues

None recorded for this phase.

### Outcome

A self-consistent fictional world that the rest of the project could be tested
against without any external data.

---

## Phase 3 — Gemini Extraction

**Status:** complete. **Commit:** `a230788` — *feat: add Gemini evidence
extraction with provenance* (13 files, 1,263 insertions).

### Objective

Turn each submitted document into typed, quoted facts using Gemini — and make
that the *only* thing Gemini is trusted to do. Extraction reads; it does not
decide.

### What was built

- `claimiq/extraction/gemini_client.py` — the only module in the codebase that
  talks to Gemini. The key is read from settings, never logged. Structured
  output is requested with a pydantic response schema and
  `response_mime_type="application/json"`. Failures surface as three typed
  errors: `GeminiUnavailableError` (no key or SDK), `GeminiRequestError` (call
  failed after one retry), `GeminiResponseError` (output invalid after one
  repair attempt, in which the validation error is appended to the prompt).
  Markdown code fences that some models wrap around JSON are stripped before
  parsing.
- `claimiq/extraction/schemas.py` — two deliberately separate layers. The wire
  layer (`WireDocumentFacts`) is exactly what Gemini must return for one
  document: about two dozen optional fields, each a value plus a verbatim
  supporting quote, and a list of `risk_mentions` (alcohol/drugs, commercial
  use, racing, vehicle left unlocked). The domain layer (`DocumentFacts`,
  `ClaimEvidence`) is validated and typed: ISO strings become `date` objects,
  registrations are normalised to uppercase without spaces or hyphens (never
  "corrected"), and every quote is checked against the source text.
- `quote_appears_in()` — the verification rule: a quote counts as verified if
  it appears in the document after collapsing whitespace and case-folding both
  sides. A quote that does not appear keeps its value but is marked
  `quote_verified: false`; verification is never assumed.
- `ClaimEvidence.observations()` — flattens per-document facts into
  comparable observations while keeping each document's version separate.
  Contested facts are not resolved here.
- `claimiq/extraction/prompts.py` — one prompt per document with a
  `PROMPT_VERSION` (currently `"1"`) that participates in the cache key, so
  bumping it invalidates every cached extraction — including, from Phase 12
  on, all 23 committed seed entries. The rules tell the
  model that blank form fields mean null, quotes must be verbatim, dates are
  day-first, and it must report *this document's* version of events without
  reconciling it against any other.
- `claimiq/extraction/cache.py` — a content-hash cache keyed on
  `sha256(model | prompt version | doc type | document text)`, stored under
  the git-ignored `.cache/extraction/`. Any change to the document, the prompt
  or the model is a miss.
- `claimiq/extraction/extractor.py` — one Gemini call per document, never one
  anonymous blob, so provenance is structural: a fact extracted from the FIR
  can only have come from the FIR. One failed document is recorded in
  `failed_documents` and the others continue; if every document fails an
  `ExtractionError` is raised.
- `scripts/extract_claim.py` — a development tool to run live extraction and
  inspect the result (`--no-cache` forces a live call).
- `claimiq/config.py` gained the model name (`GEMINI_MODEL`, default
  `gemini-3.5-flash-lite`) and a request timeout, and its `.env` loader was
  hardened (see below). `tests/test_config.py` was added.

### Engineering decisions

- **Gemini extracts; it does not decide.** Each prompt is built from one
  document's type and text alone — the ground truth, the expected decision and
  the bundle's `scenario` authoring tag are never placed in a prompt (the
  extractor function takes the bundle, but only document text reaches Gemini)
  — and a test reads the source of the extraction modules to assert the words
  `ground_truth` do not appear.
- **Every fact carries a quote, and Python checks the quote.** This is the
  foundation of everything later: citations, click-to-source highlighting, the
  provenance strip and the correspondence artifacts all rest on the fact that a
  "verified" quote was independently confirmed to exist in the document.
- **Unknown stays unknown.** A blank field is null, not a negative finding.
  This matters most for CLM-007, whose blank keys field must never become "no
  keys".
- **Contradictions are preserved, not smoothed.** Each document's version of a
  fact is kept side by side for the engine to compare.

### Issues found and fixed during the phase

- **The `.env` file that "wasn't there".** The owner reported a valid key in
  `.env` while the app reported no key configured. The file turned out to be
  zero bytes on disk (an unsaved editor buffer) — reported honestly rather than
  "fixed". Investigating it, however, exposed a real latent bug: a UTF-8 BOM at
  the start of the file would have produced an environment variable whose name
  began with the BOM character rather than `GEMINI_API_KEY`. The loader was
  hardened to read `utf-8-sig`, fall back to UTF-16, strip a stray BOM per
  line and accept `export KEY=value` lines, with eight tests covering these
  cases. This hardening is in the Phase 3 commit.
- **Model availability.** During the phase the initial default model returned
  an error stating it was no longer available to new users. The default was
  switched to `gemini-3.5-flash-lite` before the phase was committed, and the
  sampling override (`temperature=0`) was removed because newer models restrict
  or ignore it. Git history contains no trace of the earlier default; the
  committed default has always been `gemini-3.5-flash-lite`.
- **Thinking-model noise.** The SDK warned on every response about non-text
  `thought_signature` parts. The client joins the text parts of the first
  candidate directly and keeps the SDK's logger at ERROR, so real failures
  still raise while the benign warning is silenced.

### Testing

Nineteen extraction tests and eight config tests (49 total), all offline
through a fake client that replaces only the network call so the real
validation-and-repair pipeline is exercised: empty responses mean everything
unknown; registration normalisation never corrects digits; bad dates fail
validation; fabricated quotes are marked unverified but the value is kept;
quote checking is whitespace- and case-insensitive; conflicting values from
different documents are both preserved; missing key is a clean error; one
repair attempt with error context; transient failures retried then fatal;
documents kept separate; partial failure recorded; cache round-trip and key
sensitivity; corrupt cache entries ignored; the extractor never sees ground
truth. Live verification against CLM-001, CLM-002 and CLM-007 confirmed the
contradictions survived extraction and CLM-007's keys came back unknown.

### Outcome

A reading layer whose output can be trusted exactly as far as it can be
verified — and no further.

---

## Phase 4 — Deterministic Review Engine

**Status:** complete. **Commit:** `a4445f8` — *feat: add deterministic claim
review engine* (9 files, 1,808 insertions).

### Objective

Decide claims in plain Python, from evidence plus policy, identically every
time, with no LLM anywhere in the path.

### What was built

- `claimiq/engine/schemas.py` — `Finding` (ID `FIND-###`, category, severity,
  effect, title, explanation, rule name, clause IDs, evidence references),
  `EvidenceRef` (source is a document, the policy schedule or claim metadata;
  field, value, quote, `quote_verified`), and `ClaimReview` (decision, the
  finding IDs that drove it, a deterministic rationale, all findings, the list
  of checks run, and the engine version, `1.0.0`). Twelve finding categories, four severities
  (INFO, MINOR, MATERIAL, CRITICAL) and four effects (NONE, BLOCK_REJECT,
  NEEDS_INFORMATION, NEEDS_ESCALATION).
- `claimiq/engine/checks.py` — `FieldView`, which looks at one field across
  all documents and classifies it as *unknown*, *established* or
  *conflicted* after per-field normalisation (typed dates, compacted
  identifiers, case-folded names with titles stripped, "SELF" resolved
  against the trusted schedule). Then eleven checks: document completeness,
  core facts, cross-document contradictions, temporal consistency, policy
  period, notification window, coverage, exclusions, driver and licence,
  theft requirements, amounts and insured value. Every threshold comes from
  the policy's parameters, and every clause attached to a finding is a real
  clause object, so a referenced clause always exists.
- `claimiq/engine/engine.py` — `review_claim(bundle, evidence)` runs every
  check inside a fail-safe wrapper (a check that raises produces a CRITICAL
  escalation finding rather than a crash) and derives the decision by fixed
  precedence.
- `policy.json` gained a `risk_type` parameter on four exclusion clauses so the
  exclusion check could match Gemini's risk-mention categories to clauses by
  data rather than by name.
- `tests/evidence_fixtures.py` — hand-built `ClaimEvidence` for all eight
  claims (CLM-001, 002 and 007 modelled directly on real extraction output), so
  the engine could be tested completely offline. `scripts/review_claim.py` was
  added as a development tool.

### The decision precedence

1. CRITICAL escalation findings (out-of-scope loss, an unestablishable core
   fact, an engine failure) → ESCALATE
2. Established policy violations (an exclusion engaged by a verified
   first-person statement, a breached notification window, an incident outside
   the policy period) → REJECT
3. Any other escalation finding (material contradictions, a total-loss
   referral under the limit clause) → ESCALATE
4. Fixable gaps (missing documents or information) → REQUEST_INFORMATION
5. Documents complete, coverage established, nothing adverse → APPROVE
6. Anything else → ESCALATE

Approval is never the fallback: tier 5 requires positive establishment, and
everything unclassifiable escalates. One deliberate deviation from the
"missing information before contradiction" ordering sometimes suggested:
material contradictions escalate even when information is also missing,
because requesting documents while the existing evidence contradicts itself
risks papering over the conflict.

### Engineering decisions

- **Gemini reads. Python decides.** The engine never calls the network, never
  sees ground truth, and produces the identical review for the same evidence.
  This became the project's one-line principle, and it appears in that form in
  the README and the UI.
- **Formatting differences are not contradictions.** "ROHAN MALHOTRA" and
  "Rohan Malhotra" never conflict; "14th February 2026" and "14/02/2026" are
  the same date. Comparison goes through normalisation, display keeps the
  original form.
- **Uncertainty escalates.** When the incident date cannot be established,
  when contested dates straddle the policy period, when a risk statement is
  hedged or its quote unverified, the engine refers the claim to a human
  instead of pretending to know.
- **Conflicts are surfaced with every version preserved.** A contradiction
  finding carries an evidence reference for each document's value; none is
  chosen as truth.
- **Only a verified, first-person statement can engage an exclusion
  automatically**, and only for alcohol/drugs, commercial use and racing.
  Security-state statements ("not sure I locked it") are investigated, never
  auto-rejected.
- **No payout is ever computed.** The insured-value check compares and refers;
  the amount is an assessment outcome.

### Testing

Twenty-eight engine tests (77 total). All eight sample claims reach the
expected decision from fixture evidence; approval rests on positive findings
only; capitalisation and spacing never become contradictions; the
contradiction claim preserves both versions of every conflict; a missing
document requests information citing the clause; an exclusion rejects on the
claimant's own verified statement while an *unverified* quote escalates
instead; a window violation rejects with the policy's arithmetic; an exceeded
insured value escalates without inventing a payout; unknown keys request
information; contents theft is out of scope; an unknown incident date
escalates; a mixed window outcome under contested dates escalates; an incident
outside the period rejects; no default approval when coverage cannot be
established; empty evidence escalates safely; every referenced clause exists;
the review is deterministic; the engine has no ground-truth dependency; a
crashing check fails safe to escalation; mismatched evidence and bundle are
rejected.

### Issues

None recorded for this phase.

### Outcome

The decision layer of the product, complete and frozen. Every subsequent
phase was required to leave its semantics untouched, and the regression
invariant — APPROVE, ESCALATE, REQUEST_INFORMATION, REJECT, REJECT, ESCALATE,
REQUEST_INFORMATION, ESCALATE for CLM-001 through CLM-008 — held through
Phase 13.

---

## Phase 5 — Grounded RAG + Formal Citations

**Status:** complete. **Commit:** `e4cee9f` — *feat: add grounded policy RAG
with validated citations and guarded explanation* (14 files, 1,221
insertions).

### Objective

Wrap the deterministic review in formal citations and a grounded explanation —
so the result can be explained and traced — without giving anything in that
layer any authority over the decision.

### What was built

- `claimiq/rag/index.py` — a precomputed embedding index over the 17 policy
  clauses, built once by `scripts/build_policy_index.py` with
  `gemini-embedding-001` and committed as `claimiq/data/policy_index.json`
  (3,072 dimensions, roughly 530 KB), so the application never generates
  embeddings at startup. The index stores a content hash over the clause
  content it represents; if the policy changes, loading fails with
  `PolicyIndexStaleError` rather than retrieving against stale vectors.
  Dimensions are inferred from the payload, not hardcoded.
- `claimiq/rag/retriever.py` — embeds a query with Gemini and ranks clauses by
  NumPy cosine similarity (default top-k 3, minimum score 0.45; grounding
  queries it for at most three decision-driving findings, two clauses each).
  Retrieval
  provides *related context for explanation only*: it never creates findings
  and never changes the decision; the clause IDs cited by the engine always
  outrank it.
- `claimiq/rag/citations.py` — `DocumentCitation` and `PolicyCitation`, built
  by Python from the engine's own evidence references and clause IDs, then
  validated: document citations against the stored extraction (value must
  match, quote must match), policy citations against the authoritative policy
  (text is taken verbatim from `policy.json`). Invalid references are kept and
  marked invalid with the reason, never silently dropped or repaired, and
  `quote_verified` is passed through untouched — false never becomes true.
- `claimiq/rag/grounded.py` — `GroundedReview`, which wraps the `ClaimReview`
  with citations, retrieved context, an explanation, its source (`gemini` or
  `deterministic_fallback`) and warnings. **It has no decision field of its
  own**, so nothing in this layer can change the outcome. The explanation
  prompt receives only grounded material (the fixed decision, the findings,
  the validated document citations with each quote labelled verified or
  UNVERIFIED, the cited clauses, and related context explicitly labelled as
  not part of the decision basis), and the explanation is requested as
  structured output — a summary, key points and an investigator note. A
  Python guard then checks the returned
  text: if it mentions any clause or finding ID outside the supplied set, the
  explanation is discarded and the deterministic rationale is used. Every
  failure — no key, retrieval down, stale index, bad model output — becomes a
  warning, never a broken review.
- The Gemini client gained an `embed()` method, `config.py` the
  `GEMINI_EMBEDDING_MODEL` setting (default `gemini-embedding-001`), and
  `scripts/grounded_review.py` was added.

### Engineering decisions

- **RAG grounds the explanation in the real policy; it does not let Gemini
  invent policy rules.** The clauses that determine an outcome are the ones the
  engine cited from `policy.json`. Retrieval only surfaces neighbours for
  reading.
- **Citations are constructed and validated in Python, never asked of the
  model.** A citation that cannot be validated is shown as invalid, which is
  more honest than hiding it.
- **The explanation is structurally powerless.** It is produced after the
  decision, from the decision, and can be thrown away without consequence.

### Testing

Twenty-nine RAG tests (106 total): index round-trip maps every clause;
inconsistent embedding dimensions rejected; a changed policy makes the index
stale; a missing clause makes it stale; a missing index file is a clean
error; cosine ranking is correct; the retriever returns valid clause IDs with
scores; retrieval failure is typed; document citations from a real review are
valid; policy citation text matches the policy; invalid references are marked,
not dropped; wrong values and missing documents are invalid; an unknown clause
ID is invalid; unverified quotes stay unverified; grounding preserves the
decision and findings for all eight claims; retrieval and explanation cannot
change the decision; the guard discards an explanation citing an unknown
clause; explanation failure falls back safely; a valid explanation is
accepted; a missing index degrades to a warning; empty-evidence grounding is
safe; the RAG modules never touch ground truth. Live verification covered
CLM-001, CLM-002 and CLM-008.

One test was rewritten during the phase when its premise turned out to be
wrong: CLM-001's single unverified observation never reaches a finding's
evidence, so the "unverified quotes stay unverified" test was rebuilt against
a path that really exists (CLM-004's risk mention with verification forced
off).

### Outcome

The review could now explain itself with citations that Python had checked,
and the design guaranteed that the explanation could never become the
decision.

---

## Phase 6 — Functional MVP UI

**Status:** complete. **Commit:** `9ed8c70` — *feat: add investigator
workbench UI and claim review API* (4 files, 840 insertions).

### Objective

Turn the backend pipeline into something an investigator can use in a browser,
served by the same Python process.

### What was built

- The API grew from one endpoint to four: `GET /api/health`, `GET /api/claims`
  (a summary list — the authoring `scenario` tag deliberately excluded),
  `GET /api/claims/{id}` (schedule plus documents with their raw text), and
  `POST /api/claims/{id}/review`, which runs extraction (cached) → the engine
  → grounding and returns the flattened grounded review plus extraction
  information and per-stage timings. Errors map to typed HTTP responses:
  Gemini not configured → 503, every document failed → 502, an engine input
  error → 500, unknown claim → 404, all as JSON with no stack traces or
  secrets.
- `index.html` became a single-file investigator workstation (no build step,
  no external requests): a claim rail on the left, claim overview and source
  documents, a "Review claim" button, truthful loading states (a ticker of the
  real pipeline stages and an elapsed counter, no fake progress bar), a
  decision banner restricted to the four real outcomes, findings, side-by-side
  contradictions rendered generically from evidence references (nothing
  hard-coded for CLM-002), an evidence view with verification status, the
  cited policy clauses clearly separated from merely-related retrieved
  context, and the grounded explanation with a visible fallback notice when
  Gemini's explanation was unavailable.
- Session behaviour: reviews are held in browser memory for the session,
  single-flight (a review cannot be started while one is running), and a
  re-run is possible.

### Engineering decisions

- **The frontend renders; it never decides.** Every decision word, finding,
  citation and verification mark on screen is data from the backend. This was
  stated as a rule in this phase and enforced in every later one.
- **Escape everything.** All backend text is HTML-escaped before insertion
  through a single `esc()` helper, and the API key has no path to the browser
  (only `gemini_configured: true/false` and the model name reach it). The
  dedicated `idsafe()` element-ID sanitiser arrived with the interactive
  citations in Phase 7.
- **Failures are shown, not hidden.** A missing key, a failed extraction or a
  degraded explanation is rendered as a clear message with the deterministic
  result still available.

### Testing

Eighteen API tests (124 total) through an `offline_pipeline` fixture that
substitutes the hand-built evidence fixtures for extraction and a keyless
client for grounding, so the whole route runs exactly as in production minus
the network: all eight claims list; no ground-truth or scenario leakage in the
list; detail includes schedule and documents; unknown claims are JSON 404s;
all eight review decisions match the regression expectations; the
contradiction case's response preserves both dates; reviews are idempotent;
no key → 503; extraction failure → 502; no secrets in any response; the served
frontend contains no key. The review flow was also exercised in a real
browser against the running application; the full eight-claim live decision
set is recorded as part of the Phase 8 hardening run.

### Issues

None recorded for this phase.

### Outcome

From here on the product existed as something a judge could click through.

---

## Phase 7 — Investigator UX + Citation Interaction

**Status:** complete. **Commit:** `b0ec756` — *feat: investigator UX with
interactive citations and decision-driven panels* (1 file, +372/−165).

### Objective

Make the review navigable the way an investigator works: from the decision to
the reason, from the reason to the evidence, from the evidence to the policy —
and make each outcome type feel like the right next step rather than a label.

### What was built (all in `index.html`)

- A decision header with a **next action** derived from backend data — the
  finding titles that drive the outcome become buttons that scroll to and
  flash the finding.
- Clickable evidence chips and clause chips on every finding, with a
  `reveal()` helper that opens the containing collapsible, scrolls, and
  flashes the target, and an `idsafe()` helper that sanitises the element IDs
  those links point at.
- A grouped extracted-evidence panel with three explicit states for every
  cited fact: verified, unverified (amber) and invalid citation (red, with the
  validator's reason).
- Badges on the policy split that Phase 6 had already drawn: directly cited
  clauses now carry a DIRECTLY CITED badge with the findings that cite them,
  and related-context clauses a CONTEXT ONLY badge and a dimmed style (the
  dashed border came in Phase 9), so the decision basis is never confused with
  retrieval neighbours.
- The Phase 6 side-by-side contradiction layout gained an explicit "VS"
  divider between two conflicting values, de-duplication of repeated
  references, and an anchor so the decision header's reason buttons can jump
  to it.
- A REQUEST_INFORMATION checklist listing exactly the missing items with their
  clause chips, and an ESCALATE "investigator review sheet" enumerating the
  unresolved findings — built from deterministic findings, with no AI
  decision.
- A restyled passed-checks summary (moved out of the findings card into its
  own collapsed list), new rail states ("Not reviewed" until a review actually
  runs), a reworked welcome panel listing the investigator steps, and a
  clearer warnings summary ("— the decision is unaffected").

### Engineering decisions

- **Investigator-first, not CRUD-first.** The layout follows the reading
  order Claim → Decision → Why → Evidence → Policy, and each decision type
  gets the panel that its next step needs.
- **Navigation is presentation.** The chips and reveals wire existing IDs
  together; they compute nothing.

### Testing

The test count stayed at 124 (no backend changes). Browser verification was
done with Playwright, kept as a development-only tool — it is deliberately not
in `requirements.txt` so the judge install stays small — with the layout
checked at 1366×768 and 1440×900. A security regression in the browser test
asserted that the page makes zero external requests and that the DOM contains
no key, ground truth, expected decision or scenario label. No count of browser
assertions was recorded for this phase.

### Issues

One test-harness adjustment, not a product defect: on an approved claim every
finding is INFO and lives inside the collapsed passed-checks list, so a
browser assertion that expected clause chips on a visible finding was moved to
CLM-002.

### Outcome

The UI stopped being a viewer of a JSON payload and became a workbench.

---

## Phase 8 — Hardening + Judge Simulation

**Status:** complete. **Commit:** `64e93f8` — *docs: fix stale phase references
in README after hardening pass* (1 file, +9/−9).

### Objective

Find out whether the application would survive a clean judge machine, and fix
only what was genuinely broken. This was a testing and hardening phase; the
only committed change was a README correction, which is itself the finding:
the code held up.

### What was validated (recorded in the Phase 8 session report)

- **Fresh clone in a new virtual environment**: install, start, open. Python
  3.11 was not installed on the development machine; rather than fake the
  test, the clone was run on a Python 3.13 environment *and* every pinned
  dependency was resolved for Python 3.11 on Windows with
  `pip download --only-binary=:all: --python-version 3.11 --platform
  win_amd64`, confirming that all 32 wheels exist for the judge environment.
  A physical Python 3.11 run was recommended before submission (and was later
  performed — see the clean-machine section).
- **Timings**: dependency install about 56 s, startup about 3.1 s, a cold
  (uncached) review 15.8 s, warm reviews 4.5–7.9 s — all inside the limits of
  10 minutes for install, 90 s for startup and 60 s per request.
- **Behaviour without a key**: the app starts, the health endpoint reports
  Gemini unconfigured, a review returns a clear 503.
- **Failure injection** across the pipeline: malformed and non-JSON Gemini
  responses, transient request failures, grounding failures, a stale, corrupt
  and missing policy index, a corrupt cache entry — each degrading to the
  documented warning or typed error rather than a crash.
- **API robustness**: wrong methods, unknown claims, path-traversal-style claim
  IDs (a claim ID from the URL is only ever looked up in the already-loaded
  dataset; it is never used to build a file path).
- **Secret scanning** of the working tree *and* the full git history, without
  printing any discovered value; both clean.
- **Concurrency**, **determinism** (byte-stable structured reviews across
  reruns), and a **grounding security audit** of the explanation guard.
- **Browser regression** and the **live decision set** for all eight claims.
- README read as a judge would read it, and repository hygiene (generated
  files git-ignored, the policy index intentionally committed).

### Engineering decisions

None — the phase's conclusion was that no code change was warranted.

### Outcome

The README's stale references to "coming in later phases" were corrected;
otherwise the application went into Phase 9 unchanged, which is what a
hardening phase should ideally conclude.

---

## Phase 9 — Trust, Explainability & Human-Readable UX

**Status:** complete. **Commit:** `c698afc` — *feat: add trust and
explainability layer* (3 files, +593/−126).

### Objective

Make the review legible to a non-developer and make its trustworthiness
visible — without adding a single new Gemini or embedding call, and without
moving any logic into the browser. Presentation only.

### What was built

- **Human-readable identity everywhere.** `CLM-002` reads as *Claim 02*,
  `FIND-004` as *Finding 04*, `POL-05` as *Policy Clause 05*; decisions read
  *Escalate for Review*, *Request Information*; effects read *Information
  needed*, *Investigator review needed*, *Grounds for rejection*. The raw IDs
  remain as secondary metadata for traceability. Centralised label helpers
  keep this consistent; the backend contract is untouched.
- **Click-to-source quote highlighting.** Clicking a verified quote opens the
  source document and highlights the exact passage. The naive approach —
  `indexOf(quote)` on the raw text — was rejected because the backend's
  verifier is whitespace-collapsed and case-insensitive, so a verified quote is
  not necessarily a literal substring. The frontend mirrors the verifier's
  normalisation with an offset map back to raw positions, escapes the text
  segment by segment around the mark, never highlights an unverified quote,
  and never manufactures a highlight: if a quote cannot be located it says so.
- **Decision trace.** The engine's six-tier precedence rendered as a ladder:
  the winning tier is lit and lists its driving findings, tiers above it show
  "no qualifying findings", tiers below show "not consulted". The tier is
  *labelled* from the backend's decision and reasons, never recomputed.
- **Provenance strip.** Documents → extraction → cited facts with the fraction
  of quotes verified in Python → deterministic checks → findings and
  decision-driving findings → decision, every number from the actual payload.
- **Determinism receipt.** Re-running a claim compares a structural signature
  of the two reviews (decision, reasons, finding IDs, categories, severities,
  effects, clauses, evidence — timestamps, timings and narrative excluded) and
  reports whether the structured review changed. It never claims
  "byte-identical" without a byte comparison.
- **Review scope.** Every one of the eleven checks with its outcome for this
  claim (checked — no issue, flagged, not applicable, failed safely), the INFO
  findings housed in a collapsible so the links have targets, and an honest
  "outside this review" list: document authenticity, licence validity against
  a registry, discretionary decisions, facts not in the file, market value.
- **Executable policy inspector.** Each cited clause shows its machine-readable
  parameters as plain language ("Maximum reporting window: 7 days", "Required
  documents: …") and which check used them. The only backend change in the
  phase was two lines in `citations.py` passing each clause's `parameters`
  verbatim from `policy.json` into the policy citation, so the values shown
  are the authoritative ones.
- A final micro-copy and security pass: short descriptions on the main cards,
  the welcome screen "ClaimIQ — Investigator Workbench / Gemini reads. Python
  decides." with a five-step guide, and a re-audit confirming the key is read
  once server-side, nothing sensitive is serialised, and the browser makes no
  external requests.

### Engineering decisions

- **The frontend must not become a second decision engine.** The trace labels
  the backend's precedence; the receipt compares payloads; the highlighter
  mirrors a verification rule rather than re-deciding verification. This
  boundary is the reason the phase could add so much without risk.
- **Every number on screen must be computable from the payload, or omitted.**

### Issues found and fixed

- Trace reason chips rendered unstyled because their CSS was scoped to the
  banner; the selector was un-scoped.
- Two Playwright pitfalls were learned and reused later: CSS
  `text-transform: uppercase` changes the text Playwright reads, so assertions
  on headings must be case-insensitive; and the Windows console needed
  `PYTHONIOENCODING=utf-8` to print check marks.
- A latent bug was *inherited* here and found in Phase 11: the display-only
  `prettyText` helper — introduced in Phase 7 (`b0ec756`) and unchanged in
  this phase — swaps document-type tokens for labels with a bare substring
  replace, so `fir` inside the word "confirmed" rendered as "conFIR / Police
  Complaintmed". Phase 9 widened its exposure by applying the helper to the
  new trace chips, narrative and warning text. See Phase 11.

### Testing

The count stayed at 124; one RAG test gained an assertion that the citation's
`parameters` equal the clause's. Live browser verification covered the
decision trace, provenance, receipt, scope, parameters, quote matching edge
cases (whitespace, case, punctuation, multi-line, HTML-like text, a missing
quote) and the security regression.

### Outcome

A review that a claims handler could read without a glossary, and whose
trust properties — verified quotes, deterministic precedence, reproducibility,
declared scope — were on the page rather than in a README.

---

## Phase 10 — Competitive Research & Product Differentiation

**Status:** complete. **Commit:** none — this phase was research and strategy
only, with an explicit instruction not to modify the repository. No code,
data or documentation file changed.

### Objective

Establish what ClaimIQ should *not* try to be, what it uniquely is, and which
of the candidate features for the remaining phases were worth building.

### What was done

Four parallel research passes over the public claims materials of nine Indian
motor insurers (ICICI Lombard, HDFC ERGO, Bajaj Allianz, Tata AIG, SBI
General, ACKO, Go Digit, United India, New India Assurance), the regulatory
layer (IRDAI's 2024 Master Circular on protection of policyholders' interests,
the Insurance Act's surveyor provisions, ombudsman annual reporting, relevant
case law), and the existing automation landscape. Findings were graded as
explicitly documented, indirectly implied, or not publicly documented in the
sources reviewed.

### Key findings

- **Claim intake and photo/video damage assessment are crowded.** Several
  insurers publicly operate live-video inspection, photo-based instant
  settlement for small own-damage claims, and claimant-facing tracking
  dashboards. Competing there would have offered no differentiation.
- **The adjudication-reasoning layer is publicly empty.** Across all nine
  insurers, contradiction handling as a workflow, clause-level reasoning shown
  at intermediate claim stages, and auditable decision trails were not
  publicly documented. At the same time the regulator requires repudiations to
  cite the specific policy terms in writing, and ombudsman reporting shows
  repudiation disputes dominating general-insurance complaints — evidence that
  clause-grounded, evidence-grounded decisions are exactly where the industry
  is weakest.
- **Research caveat, preserved deliberately.** "Not publicly documented" was
  never treated as "does not exist". Insurers may well have internal systems
  with these capabilities; the research only establishes that none of them
  demonstrates the layer publicly, and every claim of differentiation was
  phrased that way.

### Resulting positioning

ClaimIQ is the adjudication layer that turns a messy motor claim file into a
clause-cited, contradiction-aware, reproducible decision record — the artifact
regulation already demands and that none of the public claims workflows
reviewed is documented as producing.

### Feature decisions

| Verdict | Features |
|---|---|
| Build | decision correspondence and investigator handoff; evidence matrix; claims triage / review-all |
| Should build | claim timeline; seeded extraction cache with a truthful cached/live indicator; provenance polish (contradiction count); contradiction-resolution hints |
| Rejected | an "ask the file" chatbot; fraud or risk scores; claimant-portal duplication (tracking, intake); OCR or photo upload; analytics dashboards; authentication, databases and integrations; AI-generated policy rules; autonomous auto-approval |

The chatbot and the risk score were rejected on substance, not on effort: a
chatbot would move the product toward the crowded, trust-poor quadrant and add
a hallucination surface, and an unexplainable score is precisely the kind of
ungrounded suspicion that reviewers overturn.

### Testing

None — no code changed; the suite stayed at 124 collected tests.

### Outcome

A build list for Phases 11 and 12 and a positioning that the final product
matched.

---

## Phase 11 — The Adjudication Record

**Status:** complete. **Commit:** `a5611b1` — *feat: deterministic adjudication
record — correspondence pack, evidence matrix, resolution hints* (8 files,
1,615 insertions).

### Objective

Make the review usable as an actual investigator artifact: the letter, the
rationale, the handoff memo, and the reconciliation views a handler would
otherwise assemble by hand — generated deterministically from data the review
already contains.

### What was built

A new package, `claimiq/record/`:

- **`correspondence.py` — the Correspondence & Handoff Pack.** One artifact per
  decision, chosen by the decision: an *information request* letter for
  REQUEST_INFORMATION (neutral greeting to the scheduled policyholder, the
  documents received, one numbered item per needs-information finding with its
  clause basis, and an explicit statement that no outcome has been reached); a
  *decision rationale* for REJECT (numbered grounds with verified quotes, then
  the engaged clauses quoted verbatim from the policy); an *investigator
  handoff* for ESCALATE (established information, every conflict with all its
  versions, why human review is required, what would help resolve it, the
  applicable clauses, the review scope); and a short *approval record* for
  APPROVE. Each artifact is a structured set of sections for rich rendering
  *and* a canonical plain-text rendering produced by the same Python code.
- **`matrix.py` — the evidence matrix.** Fields as rows, documents as columns,
  plus a trusted policy-schedule column where comparable. Conflict flags are
  not recomputed: a row is flagged exactly when an engine contradiction finding
  references its field, so the matrix can never disagree with the engine's
  normalised comparison. A field no document states renders as "not stated";
  booleans render as Yes/No only when actually stated — CLM-007's blank keys
  field appears as a row *because the keys check ran*, with every cell "not
  stated", and never becomes "No".
- **`hints.py` — resolution hints.** A fixed mapping from a contested field to
  the records that could help establish it (a garage job card, the FIR entry,
  the original registration certificate, the driving licence of the stated
  driver, and so on), applied only to contradiction findings. The rule the
  module exists to keep: ClaimIQ identifies what evidence could resolve a
  contradiction; it does not decide which conflicting value is correct.
- Three additive keys on the review response: `correspondence`,
  `resolution_hints`, `evidence_matrix`. Record building is wrapped so that any
  failure becomes a warning and the review itself is unaffected.
- In the frontend: an *Adjudication record* card with Copy, Print (a light
  printable page built from the same escaped structure) and Download (.txt);
  the matrix table with clickable verified cells and conflict chips linking to
  findings; hints on each contradiction card under an explicit "suggestions
  only" heading; the provenance strip's "N unresolved contradictions" segment
  (shown only when N > 0); a cautious condonation note in the scope card; and a
  sixth step in the welcome guide.

### The grounding guarantee

`build_correspondence(bundle, review, document_citations, policy_citations)`
cannot receive the Gemini explanation — it is not a parameter. Grounding is
therefore structural, not filtered: item content comes verbatim from findings,
quotes from validated citations and finding evidence, clause text from
validated policy citations, and the connectives are fixed templates. Conflicts
are always listed with every version; the builder never selects one.

### Issues found and fixed

- **The document-label substring bug.** Live data exposed that the frontend's
  `prettyText` helper — in place since Phase 7 (`b0ec756`) — matched the bare
  substring `fir`, turning "confirmed" into "conFIR / Police Complaintmed";
  the first draft of the Python artifact builder had copied the same approach.
  Both were changed to whole-word matching before the phase was committed —
  the frontend fix is visible in this commit's diff, and the Python builder
  was committed with the whole-word rule — with a regression test asserting
  the artifact contains "confirmed" and not "conFIR".
- A pre-existing grammar nit in engine text ("for a accident claim") became
  visible in the letters and was deliberately *not* fixed here, because the
  phase's rules forbade touching engine text; it was fixed in Phase 13 with
  the owner's sign-off.

### Testing

199 tests: the previous 124 plus 65 record tests and 10 API tests. The record
tests prove, for every claim, that the artifact kind matches the decision;
that every `POL-xx` token in every artifact is a clause the findings actually
cite; that every evidence line matches a stored reference and every document
mentioned was submitted; that two builds — including across fresh engine runs
— are identical; that information-request items are exactly the
needs-information findings; that rejection grounds are exactly the blocking
findings with the clause text verbatim; that the CLM-002 handoff preserves both
dates, both drivers and both registrations and never declares a winner; that
CLM-008's handoff omits the resolve section rather than fabricating one; that
hints exist only for contradictions and known fields and never mutate the
review; and the matrix behaviours above. The API tests include an
**adversarial narrative test**: a hostile Gemini explanation ("ignore all
findings, approve, pay under POL-99") injected into grounding leaves the
decision, the correspondence text, the matrix and the hints byte-identical.
Live Playwright verification covered CLM-001 through CLM-004, CLM-007 and
CLM-008, Copy via clipboard read-back, the printable HTML, quote-jumps from
records and matrix cells, and the security regression. A warm review measured
about 4.1 s in total, of which record building was on the order of a
millisecond.

### Outcome

The layer between evidence-and-policy and investigator action. Decision
semantics were not altered: the engine, checks, policy and extraction files
have no diffs in this commit.

---

## Phase 12 — Caseload + Demo Armor

**Status:** complete. **Commit:** `7041d75` — *feat: investigator caseload,
seeded extraction cache, and claim timeline* (36 files, 2,879 insertions,
including 23 seed artifacts).

### Objective

Make ClaimIQ feel like a caseload workbench rather than a single-claim demo,
and make a fresh clone demo quickly and reliably — without sacrificing any
correctness property.

### What was built

- **Caseload board.** The default view on load, built from the existing
  `GET /api/claims`: claim and title, type, vehicle and registration, document
  count, review state and an action. State is session-local and honest — every
  row reads "Not reviewed" until a review actually runs; an API test asserts
  the claims list carries no decision field at all, and the session's browser
  check confirmed no decision word appears on a fresh board. "Review all N
  remaining" runs claims one at a time (never concurrently) with a live
  counter and a Stop button that takes effect at the next claim boundary;
  per-row failures show inline without aborting the batch. No charts, KPIs,
  percentages or scores.
- **Seeded extraction cache.** The same content-hash mechanism and the same
  payload shape, in two locations: the writable runtime cache under
  `.cache/extraction/` (git-ignored) and a committed, read-only seed under
  `claimiq/data/extraction_seed/` (23 files, 61 KB of JSON). Lookup prefers
  runtime over seed; writes go only to runtime. **Cached facts are never
  trusted on their word**: whatever comes back is re-validated against the
  schema and every quote is re-verified against the actual document text, so
  a cache can only *downgrade* verification, never upgrade it — a tampered
  seed asserting a quote is verified is corrected on load. Any change to a
  document, the prompt version or the model is a miss followed by live
  extraction. Each document records its source (`live`, `runtime_cache`,
  `seed_cache`) in a new `document_sources` field on `ClaimEvidence`,
  summarised on the response as `mode: cached | live | mixed`.
  `scripts/seed_extraction_cache.py` (`--check` verifies without writing,
  `--force` re-extracts live) regenerates the seed from an existing
  valid entry, the local runtime cache, or a live call, validates and
  re-verifies every candidate, and audits the directory for forbidden content
  (decisions, expectations, scenario labels, keys, unexpected keys).
- **Truthful extraction indicator.** The provenance strip's second segment now
  reads "Cached extraction", "Live Gemini extraction" or "N cached · M live
  extraction", with a tooltip stating that policy retrieval and the written
  explanation are a separate Gemini step. A cached extraction is never
  described as an offline review.
- **Claim timeline.** `claimiq/record/timeline.py` builds a chronology from
  extracted date facts only (incident, discovery, FIR, garage receipt,
  document date), each with its source document and verbatim quote, plus the
  insurer's own record of when the claim was reported, labelled as such and
  carrying no quote. Contested dates appear as separate events, flagged and
  linked to their contradiction finding using the same `conflicted_fields()`
  the matrix uses. On CLM-002 this makes the impossible sequence visible: the
  garage received the car on 15 February, before the claim form's 18 February
  incident date.
- **Resolution-hint polish**: schedule-based records added (the driver details
  on the claim form and policy schedule; the registration on the policy
  schedule).
- **Scope wording rewritten** so it can never be read as ClaimIQ granting
  discretion: it applies the policy's windows and document requirements
  exactly as written, does not excuse late notification, missing documents or
  procedural defects, and states that condonation is an investigator and
  policy decision taken outside the review.
- The README's project-structure listing was updated (it had been missing the
  Phase 11 `record/` package).

### Engineering decisions

- **One cache format, two locations.** A second format would have meant a
  second validation path. The seed is simply the runtime cache's format, shipped.
- **Re-verify on load.** A committed artifact can be edited by anyone; the
  cost of re-checking quotes is string operations, and it turns the seed from
  something trusted into something checked.
- **The seed is keyed to the default model.** If a judge sets `GEMINI_MODEL`
  to anything else, every document misses the seed and extracts live — correct
  and honest, at the cost of the speed advantage.

### Testing

233 tests (34 new): the shipped seed covers all 23 sample documents and every
stored `quote_verified` flag matches a fresh check; the seed contains facts
only; the seed serves extraction with a client that raises on any network
call; runtime takes precedence over seed; a changed document, prompt or model
is a miss; a malformed seed entry falls back to live extraction; a tampered
verification flag is downgraded; provenance modes are truthful; the claims
list carries everything the board shows and nothing it must not; the timeline
is evidence-backed, chronological, keeps contradictory dates apart, has no
conflicts on a clean claim, omits dates no document states, and is pure.
A fresh-clone simulation run during the session (empty runtime cache, a
client that raises on any network call — the committed seed test itself
exercises CLM-002): all eight claims extracted and decided from the seed in
0.04 s with zero Gemini calls, reproducing every expected decision. The live path was
also exercised end to end: with both caches empty, CLM-003 extracted live in
10.6 s and reported `mode: live`; the second run served from the runtime cache
in 0.02 s with identical facts and reported `mode: cached`. Live browser
verification: fresh board honesty, review-all (seven claims in 25.7 s), timeline
navigation and quote-jump, the cached indicator on every claim, re-review
receipt, and all Phase 9 and 11 interactions. Measured: startup 2.12 s; cached
reviews 2.8–5.9 s wall time with a maximum request of 7.97 s, of which
extraction was 0.01 s and grounding the remainder.

### Issues

Two during development, neither a product defect. The first seed test missed
the seed because the offline fake client reported a different model name from
the one the seed is keyed to; the fake was parameterised. And the live
extraction check exercised the Phase 3 repair loop for real: the model
returned `accident damage` for a field that accepts only `accident` or
`theft`, validation rejected it, and the single repair attempt produced valid
output.

### Outcome

A caseload that can be reviewed end to end in under half a minute on a fresh
clone, with extraction provenance stated truthfully. Nothing was deferred from
the Phase 12 list; the timeline was implemented because the evidence model
already contained enough quoted dates to build it safely.

---

## Phase 13 — Final UI Polish

**Status:** complete. **Commit:** `0a251fc` — *polish: neutral claim titles,
decision-first layout, and wording fixes* (10 files, +28/−17).

### Objective

A deliberately small pass to make the existing UI calm and demo-ready: no new
features, no dependencies, no decision-logic, policy or architecture changes.

### What changed

- **Claim titles no longer announce the verdict.** Every one of the eight
  titles carried a suffix that gave the outcome away before the review ran
  ("… - rider admits drinking (exclusion)", "… - clean accident claim",
  "… - reported 24 days late"). Only the presentation label changed, to a
  neutral description of the incident ("Motorcycle hit road barrier",
  "Two-wheeler hit road divider", "Car rear-ended at signal"); every underlying
  fact still reaches the investigator through the evidence and findings. The
  extraction seed was unaffected, since cache keys are derived from document
  text, not titles.
- **Decision before provenance.** The provenance strip had sat above the
  decision banner; the order was swapped so the answer comes first and the
  pipeline that produced it follows.
- **Grammar in engine text**: "for a accident claim" became "for an accident
  claim" via a tiny article helper (`_a`), so "for a theft claim" also stays
  correct. This is the one backend edit, sanctioned explicitly, and it changes
  no logic.
- **Developer wording removed** from investigator-facing text: the raw
  extraction category `alcohol_or_drugs` now renders as "Alcohol or drugs" in
  the evidence card, and the policy inspector's label "from policy.json" became
  "read from the policy".
- **Overview wording**: the claim-overview description had promised a
  "coverage position" the card does not show; it now describes what is
  actually there.

### Left alone, deliberately

"Exclusion engaged: Exclusion - Driving Under the Influence" reads redundantly,
but the duplication comes from the clause title itself and fixing it would
mean altering policy text or engine finding titles. ISO dates in the evidence
panel and matrix were kept because precise comparison is the point of those
views and the timeline already provides the readable form. At 1366×768 the
decision banner's last button row ends a few pixels below the fold; the
decision word is fully visible, and closing the gap would have required
restructuring the header.

### Testing

233 tests, unchanged. Both browser suites (Phase 11 and Phase 12) passed
against the live application with all eight decisions unchanged; CLM-001,
002, 003, 004 and 007 were inspected visually along with the board, timeline,
matrix, correspondence, evidence, policy and scope cards; no horizontal
overflow at 1440×900, 1366×768 or 900 px; no external requests; no key,
ground truth, expected decision or scenario label in the DOM or payloads.

### Issues

No product defects. Two assertions in the development-only Phase 11 browser
suite had gone stale — they still expected the pre-Phase-12 welcome screen and
the condonation wording Phase 12 deliberately rewrote — and were updated; the
repository's own test suite needed no change.

### Outcome

The product as submitted for demo preparation.

---

## Final clean-machine / judge validation

Two clean-environment validations were performed, at different points.

**During Phase 8 (development machine, Windows).** A fresh clone was installed
and run in a new virtual environment. Because Python 3.11 was not installed
locally, the clone ran on Python 3.13 and, separately, every pinned dependency
was resolved as a pre-built wheel for Python 3.11 on Windows, proving the judge
install would not need to compile anything. Measured then: install about 56 s,
startup about 3.1 s, cold review 15.8 s, warm reviews 4.5–7.9 s, all eight
decisions as expected.

**Immediately before demo preparation (clean MacBook, as recorded by the
project owner).** Python 3.11.16 was installed; `python3.11 -m pip install -r
requirements.txt` completed in approximately 6 seconds on the initial install,
and a subsequent `pip install -r requirements.txt` in approximately 1 second;
`python app.py` started in approximately 1.5–2 seconds; the application was
accessible on `localhost:8000`. The machine did not initially expose `python`
or `pip` as unversioned commands, and environment-specific symlinks were
created *during the test* so that the literal judge commands could be
exercised. Those symlinks are a property of that test environment, not of
ClaimIQ: the project's setup contract remains the hackathon's specified Python
3.11 judge environment, `pip install -r requirements.txt`, then
`python app.py`. No OS-specific command sets, aliases or interpreter
requirements were added to the project as a result, and `requirements.txt`
lists Python packages only.

Across both validations the judge-facing properties held: one Python process,
port 8000, no frontend build step, no second terminal, no virtual-environment
activation step imposed by the application, and the eight sample claims
behaving as expected.

---

## Current architecture

```
Submitted documents (claim form, repair estimate, FIR, incident description)
        │
        ▼
Gemini extraction — one structured call per document
        │
        ▼
Python verification — schema validation, quote verification against the
source text, normalisation; cached by content hash, re-verified on load
        │
        ▼
Deterministic policy engine — eleven checks over per-field consensus views,
thresholds read from policy.json, fixed six-tier precedence
        │
        ▼
Decision + findings — APPROVE / REJECT / REQUEST_INFORMATION / ESCALATE,
each finding tied to evidence references and clause IDs
        │
        ▼
Grounding — Python-built, Python-validated document and policy citations;
related clauses by local cosine retrieval; a guarded Gemini explanation
that can be discarded without consequence
        │
        ▼
Adjudication record — correspondence / handoff artifact, evidence matrix,
timeline, resolution hints, all pure transformations of the above
        │
        ▼
Investigator workbench — caseload board, decision trace, provenance,
click-to-source, copy / print / download
```

### Responsibility boundaries

**Gemini** understands messy language: it extracts facts with quotes from each
document, embeds text for policy-clause retrieval, and writes the grounded
explanation from material Python hands it.

**Python** verifies evidence and normalises values; evaluates the policy;
detects contradictions and temporal impossibilities; applies claim windows,
coverage, exclusions, driver and theft conditions and the insured-value limit;
decides; builds and validates citations; guards the explanation; builds the
correspondence, the evidence matrix, the resolution guidance and the timeline;
validates and reports cache provenance.

**The frontend** presents, navigates and interacts. It renders backend data,
labels backend results in human terms, mirrors the backend's quote-matching
rule to highlight text, and compares two payloads for the determinism receipt.
It determines no decision and computes no conflict.

Module map: `claimiq/extraction/` (client, schemas, prompts, cache,
extractor), `claimiq/engine/` (schemas, checks, engine), `claimiq/rag/`
(index, retriever, citations, grounded), `claimiq/record/` (correspondence,
matrix, timeline, hints), `claimiq/api/routes.py`, `claimiq/server.py`,
`claimiq/web/static/index.html`, and `claimiq/data/` (policy, claims, test-only
ground truth, the committed policy index and extraction seed).

---

## Key product principles

These held from the phase in which they were first stated to the end.

1. **Gemini reads. Python decides.** No LLM output is ever a decision input.
2. **Evidence must be traceable.** Every finding names its documents, fields,
   values, quotes and clauses; every artifact is built from those references.
3. **Quotes must be verified against source documents**, in Python, and a
   quote that fails stays visibly unverified.
4. **Contradictions are preserved, not silently resolved.** Every version is
   kept, labelled and shown; the system never picks a winner.
5. **Unknown is different from negative.** A blank field is "not stated",
   never "no".
6. **Policy rules are authoritative data, not generated text.** Thresholds and
   document lists come from `policy.json` parameters; the UI shows the values
   it used.
7. **Human review is a valid outcome.** Escalation is the deliberate result
   when the evidence cannot support a decision; approval is never the default.
8. **Generated explanations must not alter deterministic decisions.** The
   grounded review has no decision field; the explanation is guarded and
   disposable; the correspondence builder cannot even receive it.
9. **The frontend is not the decision engine.**
10. **Security and provenance are part of the product.** The key never leaves
    the server, test-only data never reaches the API, the browser makes no
    external requests, and the page states where its facts came from.
11. **Reproducibility matters.** Same evidence in, same review out — and the
    receipt proves it on screen.
12. **ClaimIQ is an investigator aid, not an autonomous adjudicator.**

---

## Test and validation milestones

| Point | Tests collected | What was added |
|---|---|---|
| Phase 1 (`5151b0f`) | 5 | health, index, JSON 404, port, track ID |
| Phase 2 (`90a0dff`) | 22 | 17 dataset integrity and scenario tests |
| Phase 3 (`a230788`) | 49 | 19 extraction tests, 8 `.env` loader tests |
| Phase 4 (`a4445f8`) | 77 | 28 engine tests incl. all eight decisions and fail-safe |
| Phase 5 (`e4cee9f`) | 106 | 29 RAG, citation and explanation-guard tests |
| Phase 6 (`9ed8c70`) | 124 | 18 API tests through the offline pipeline |
| Phases 7–10 | 124 | browser and hardening validation; no new unit tests |
| Phase 11 (`a5611b1`) | 199 | 65 record tests, 10 API tests incl. the adversarial narrative |
| Phase 12 (`7041d75`) | 233 | 34 seed-cache, provenance, board and timeline tests |
| Phase 13 (`0a251fc`) | 233 | none; regression only |

Current distribution: `test_api.py` 47, `test_app.py` 5, `test_config.py` 8,
`test_dataset.py` 17, `test_engine.py` 28, `test_extraction.py` 27,
`test_rag.py` 29, `test_record.py` 72. The whole suite runs offline in a few
seconds.

The live scenarios used for validation throughout, each with its expected
outcome held as a regression invariant in the tests: a clean approval
(CLM-001), contradiction escalation (CLM-002), missing information (CLM-003),
exclusion rejection on the claimant's own statement (CLM-004), late-reporting
rejection (CLM-005), insured-value escalation (CLM-006), theft with missing
information (CLM-007), and out-of-scope escalation (CLM-008).

---

## Major issues and lessons

- **Generated explanations must have no path to the outcome.** The design
  choice that `GroundedReview` has no decision field, and later that the
  correspondence builder cannot receive the explanation, is what let an
  adversarial "approve and pay" narrative be tested and shown to change
  nothing. Guarding text is good; making the text structurally powerless is
  better.
- **Blank fields are not negative findings.** CLM-007 was the constant test:
  a blank keys field had to stay "unknown" through extraction, the engine, the
  matrix and the letter, and never become "no keys".
- **A verified quote is not a literal substring.** The backend verifier
  collapses whitespace and case; the frontend highlighter had to mirror that
  rule with an offset map rather than call `indexOf`, or verified quotes would
  have failed to highlight.
- **Normalised comparison is what makes contradiction detection honest.**
  Without it, "Rohan Malhotra" versus "ROHAN MALHOTRA" would have been a
  contradiction and the tool would have cried wolf.
- **Caches must fail safely and be re-checked.** A corrupt entry is ignored, a
  stale key is a miss, and a shipped seed is re-validated and re-verified on
  every load so it cannot assert what the document does not contain.
- **Clean-machine validation catches environment assumptions.** The zero-byte
  `.env` episode found a BOM bug that would have bitten a Windows judge; the
  missing local Python 3.11 was handled by resolving wheels for the judge
  platform rather than by pretending the test had been run.
- **Human-readable presentation is a feature of an investigator tool**, and
  it has to be done without moving logic into the browser. Labels, traces and
  receipts were all built as views over backend data.
- **A deterministic artifact beats another generated paragraph.** The letter,
  the rationale and the handoff memo are trusted precisely because they are
  transformations of findings, not prose about them.
- **Preserving a contradiction is better than silently choosing a winner** —
  in the finding, in the matrix, in the timeline and in the memo.
- **Substring replacement on display text is a bug waiting to happen.** The
  `fir`-inside-"confirmed" defect was invisible on fixture data and appeared
  only on live extraction output.
- **Titles that announce the verdict undermine the demonstration.** The
  product's whole story is that Python reaches the outcome from evidence;
  the caseload must not reach it first.

---

## Current state

As of `0a251fc`, ClaimIQ is a working motor-claims investigator workbench for
the NexusTiQ 24 PS02 problem. It can:

- load a caseload of eight synthetic motor claims and review them one at a
  time or all in sequence;
- extract structured evidence from each submitted document with Gemini, from
  a validated local seed when the document is unchanged, or live otherwise;
- verify every extracted quote against the source document and show its
  status;
- compare the evidence against a 17-clause machine-readable policy through
  eleven deterministic checks, detect contradictions and impossible timelines,
  and reach APPROVE, REJECT, REQUEST_INFORMATION or ESCALATE by fixed
  precedence;
- cite documents and policy clauses, validated in Python, and show the
  policy's own rule values;
- show the source documents with click-to-source highlighting, the decision
  trace, provenance (including whether extraction was cached or live and how
  many contradictions remain unresolved), the review scope, an evidence
  matrix, a claim timeline and contradiction-resolution guidance;
- generate a deterministic information-request letter, rejection rationale,
  investigator handoff memo or approval record, and copy, print or download
  it;
- run as one Python process on port 8000, serving the API and the frontend,
  with no build step.

**Test status:** 233 tests passing offline; both Playwright suites passing
against the live application.

**Runtime status (last measured):** startup about 2 s; cached reviews roughly
3–6 s, dominated by the Gemini grounding step; a live extraction of a
two-document claim about 10–11 s; a fresh clone reproduces all eight decisions
from the seed without a network call.

**Known limitations:** the policy and data are fictional; extraction is
text-only (no OCR, images or PDFs); a Gemini key is required to run a review
at all — without one the review endpoint returns a 503 before extraction, even
when the committed seed covers every document, because the extractor checks
for a configured client before consulting any cache; with a key present, the
grounded explanation and policy retrieval can still fail (network, stale
index, bad model output), in which case the review completes with the
deterministic rationale and a warning; the extraction seed is keyed to the
default model; review state lives in the browser session; no external
registry, surveyor or payment data exists.

**Intentionally deferred ideas** (documented, not built): an investigator
case-note field; regulatory turnaround-time awareness, which would need
processing-stage dates the data model does not have.

**Submission state:** feature-complete after Phase 12, polished in Phase 13,
validated on a clean Python 3.11 machine, ready for demo preparation.

---

## Known limitations and deliberate non-goals

These were scope decisions for the hackathon problem, taken in Phase 10 and
held to, not omissions:

- no chatbot or general "ask the file" interface;
- no fraud or risk scoring;
- no photo or video damage assessment, no OCR, no file upload;
- no claimant-facing portal or status tracking;
- no analytics dashboard, charts or KPIs;
- no authentication, accounts or database;
- no external insurer, registry or payment integrations;
- no AI-generated policy rules;
- no autonomous final claims adjudication — every outcome is a recommendation
  with its record, and escalation to a human is a first-class result;
- synthetic policy and claim data rather than real insurer production data.

---

*Sources for this record: the git history of the repository (twelve commits,
inspected individually, with tests collected at each one), the README, the
current code and tests, the policy and claim data, and the phase reports
produced during development for the measurements and bug narratives that the
repository itself cannot show.*
