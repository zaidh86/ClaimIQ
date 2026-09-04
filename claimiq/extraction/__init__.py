"""Gemini evidence extraction: raw claim documents -> validated structured facts.

This layer only establishes facts with provenance. It never decides claim
outcomes, never sees ground truth, and never invents values — anything a
document does not state comes back as null/unknown.
"""
