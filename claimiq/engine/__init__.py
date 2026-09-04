"""Deterministic claim review engine.

Consumes validated ClaimEvidence (Phase 3) and the structured policy (Phase 2)
and produces structured findings plus a decision. Pure Python: no network, no
Gemini, no ground truth. Given the same evidence and policy it always produces
the same review.
"""
