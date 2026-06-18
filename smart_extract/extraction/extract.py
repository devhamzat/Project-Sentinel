"""Run extraction on clean paper text and return a validated dict (CLAUDE.md §4).

The hybrid pipeline:
  1. LLM proposes all fields (interpretive content + bibliographic) via the seam.
  2. Deterministic guards make the result honest and evaluable:
     - the USES (paper->dataset) relation keeps only datasets whose name
       actually occurs in the text (grounded filter — the central contribution
       must be trustworthy for Chapter 4);
     - a spaCy NER pass cross-checks authors/affiliations and drops candidates
       it cannot ground in the document (validate, don't extract).

Output is a normalised dict matching the §6 schema, plus a ``_validation``
block recording what the deterministic layer dropped (useful for the writeup).
"""

from __future__ import annotations

from typing import Any

from smart_extract.extraction.llm import extract_json
from smart_extract.extraction.nlp import validate_people_orgs
from smart_extract.extraction.prompts import EXTRACTION_SYSTEM, extraction_prompt


def _as_str_list(value: Any) -> list[str]:
    """Coerce a model field into a clean list of unique, non-empty strings."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        s = str(item).strip()
        key = s.lower()
        if s and key not in seen:
            seen.add(key)
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
        "methods": _as_str_list(raw.get("methods")),
        "metrics": _as_str_list(raw.get("metrics")),
        "summary": str(raw.get("summary", "")).strip(),
    }


def ground_datasets(datasets: list[str], text: str) -> tuple[list[str], list[str]]:
    """Keep only datasets whose name occurs in the paper text (case-insensitive).

    Returns (kept, dropped). This is the deterministic guard on the USES
    relation — the project's central contribution — against the most common
    LLM hallucination: naming a plausible benchmark the paper never used.
    """
    haystack = text.lower()
    kept = [d for d in datasets if d.lower() in haystack]
    dropped = [d for d in datasets if d not in kept]
    return kept, dropped


def extract(text: str) -> dict[str, Any]:
    """Run the full hybrid extraction on clean paper text.

    Returns a normalised §6 dict with deterministic guards applied. A
    ``_validation`` key records what was dropped (not stored in the graph).
    Raises LLMError (from the seam) if the model call fails or returns
    unparseable output.
    """
    raw = extract_json(extraction_prompt(text), system=EXTRACTION_SYSTEM)
    paper = normalise(raw)

    # --- guard the USES relation: datasets must be grounded in the text ---
    kept_datasets, dropped_datasets = ground_datasets(paper["datasets"], text)
    paper["datasets"] = kept_datasets

    # --- spaCy validation of authors/affiliations ---
    checked = validate_people_orgs(text, paper["authors"], paper["affiliations"])
    paper["authors"] = checked["authors"]
    paper["affiliations"] = checked["affiliations"]

    paper["_validation"] = {
        "spacy_validated": checked["validated"],
        "dropped_datasets": dropped_datasets,
        "dropped_authors": checked["dropped_authors"],
        "dropped_affiliations": checked["dropped_affiliations"],
    }
    return paper
