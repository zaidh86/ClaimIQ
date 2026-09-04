TRACK_ID=PS02

# ClaimIQ — Insurance Claims Evidence Review Assistant

**NexusTiQ 24 · Track PS02**

ClaimIQ reviews motor insurance claims (two-wheelers and cars — accident damage or theft)
by checking the submitted evidence — claim form, repair estimate or FIR, and the customer's
incident description — against the insurer's policy. It reports document completeness,
surfaces contradictions between documents instead of smoothing them over, cites the exact
policy clauses behind every finding, and recommends **approve / reject / request
information**, escalating to a human investigator whenever the evidence does not support a
confident conclusion.

**Core principle:** AI interprets evidence. Python verifies evidence. Policy rules determine
what the evidence supports. The system cites its sources. Humans make the final judgement
when uncertainty remains.

## Quick start

Requires **Python 3.11**.

```bash
pip install -r requirements.txt
python app.py
```

Then open **http://localhost:8000**

## Configuration

| Variable | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | For AI features | Gemini API key (LLM extraction + embeddings) |
| `PORT` | No | Server port (default `8000`) |
| `HOST` | No | Bind address (default `0.0.0.0`) |
| `LOG_LEVEL` | No | `debug` / `info` / `warning` (default `info`) |

Set the key via environment variable or copy `.env.example` to `.env` and fill it in.
The app starts and serves without a key — Gemini-dependent features report their
unavailability gracefully instead of crashing. **Never commit `.env`.**

## Project structure

```
app.py                    # Entry point — python app.py serves everything on :8000
requirements.txt
claimiq/
  config.py               # Environment/config handling (.env loader, settings)
  server.py               # FastAPI app factory, error handlers, static serving
  api/routes.py           # API endpoints (/api/health, review endpoints later)
  web/static/index.html   # Frontend served by the Python app
tests/                    # pytest suite (run: pytest)
```

## Architecture (planned)

```
Claim documents ──► Gemini structured extraction ──► Deterministic review engine
                        (interpretation only)          (completeness, contradictions,
                                                        policy rules, decision)
Policy clauses  ──► Local embeddings + retrieval ──► Cited, grounded review output
                    (gemini-embedding-001,             APPROVE / REJECT /
                     precomputed, NumPy cosine)        REQUEST_INFORMATION / ESCALATE
```

Gemini never decides outcomes — it extracts and explains. All decisions, arithmetic,
contradiction detection, and citation validation are deterministic Python.

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Foundation — app skeleton, config, health, frontend serving | ✅ done |
| 2 | Fictional policy + claim bundles + ground truth | planned |
| 3 | Gemini structured extraction | planned |
| 4 | Deterministic claim review engine | planned |
| 5 | Local RAG + citations + grounded narrative | planned |
| 6 | Complete MVP integration + UI | planned |

## Tests

```bash
pytest
```
