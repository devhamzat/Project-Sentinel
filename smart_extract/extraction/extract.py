"""Run LLM extraction on clean paper text and return a validated dict.

Thin layer over the LLM seam (llm.py) and the shared prompt (prompts.py). It
keeps the Phase-1 surface small: in -> clean text, out -> a normalised dict
matching the §6 schema. Deterministic NLP enrichment (spaCy) is layered on in
Phase 3; here the LLM supplies everything so the end-to-end thread works.
"""

from __future__ import annotations

from typing import Any

from smart_extract.extraction.llm import extract_json
from smart_extract.extraction.prompts import EXTRACTION_SYSTEM, extraction_prompt


def _as_str_list(value: Any) -> list[str]:
    """Coerce a model field into a clean list of non-empty strings."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        s = str(item).strip()
        if s:
            out.append(s)
    return out


def _as_year(value: Any) -> int | None:
    """Coerce the year field to an int, or None if absent/unparseable."""
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def normalise(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise a raw LLM dict into the canonical schema shape (§6).

    Guarantees every expected key exists with the right type, so downstream
    graph writes never KeyError on a field the model happened to omit.
    """
    return {
        "title": str(raw.get("title", "")).strip(),
        "year": _as_year(raw.get("year")),
        "authors": _as_str_list(raw.get("authors")),
        "affiliations": _as_str_list(raw.get("affiliations")),
        "keywords": _as_str_list(raw.get("keywords")),
        "datasets": _as_str_list(raw.get("datasets")),
        "summary": str(raw.get("summary", "")).strip(),
    }


def extract(text: str) -> dict[str, Any]:
    """Extract structured fields from clean paper text via the LLM seam.

    Returns a normalised dict matching the §6 schema. Raises LLMError (from the
    seam) if the model call fails or returns unparseable output.
    """
    raw = extract_json(extraction_prompt(text), system=EXTRACTION_SYSTEM)
    return normalise(raw)
