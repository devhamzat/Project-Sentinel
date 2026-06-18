"""Deterministic NLP path: spaCy NER as a validator (CLAUDE.md §4).

The hybrid reliability principle: the LLM *proposes* bibliographic fields
(authors, affiliations); a deterministic spaCy pass *validates* them against the
document so factual metadata is not at the mercy of LLM hallucination.

We deliberately use spaCy as a cross-check, not the primary extractor:
en_core_web_sm's generic PERSON/ORG NER is unreliable on academic author blocks,
but it is good enough to answer "does this proposed name appear as a PERSON / this
institution as an ORG anywhere in the text?". Candidates the model never grounds
are flagged as likely hallucinations.

The model is loaded lazily and cached; if it is not installed, validation
degrades gracefully (everything passes) rather than crashing the pipeline (§12).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

# spaCy is a declared dependency; the *model* (en_core_web_sm) is a separate
# download and may be absent. Both are handled lazily below.
try:  # pragma: no cover - import guard
    import spacy
    from spacy.language import Language
except Exception:  # pragma: no cover
    spacy = None  # type: ignore[assignment]
    Language = Any  # type: ignore[misc,assignment]

_MODEL_NAME = "en_core_web_sm"


@lru_cache
def _nlp() -> "Language | None":
    """Load and cache the spaCy model, or return None if unavailable."""
    if spacy is None:
        return None
    try:
        # Only the NER component is needed; disabling the rest is faster (§14).
        return spacy.load(_MODEL_NAME, disable=["lemmatizer", "textcat"])
    except Exception:
        return None


def model_available() -> bool:
    """True if the spaCy validator model can be loaded."""
    return _nlp() is not None


def _entities_by_label(text: str, labels: set[str]) -> set[str]:
    """Return the lowercased entity texts of the given NER labels found in text."""
    nlp = _nlp()
    if nlp is None:
        return set()
    doc = nlp(text)
    return {ent.text.strip().lower() for ent in doc.ents if ent.label_ in labels}


def _grounded(candidate: str, ner_texts: set[str]) -> bool:
    """True if a candidate name overlaps any detected entity (token-level).

    Academic names/affiliations rarely match an NER span exactly (markers,
    truncation), so we accept a match if any non-trivial token of the candidate
    appears within a detected entity span (or vice versa).
    """
    cand = candidate.strip().lower()
    if not cand:
        return False
    if any(cand in e or e in cand for e in ner_texts):
        return True
    cand_tokens = {t for t in cand.split() if len(t) > 2}
    for e in ner_texts:
        e_tokens = set(e.split())
        if cand_tokens & e_tokens:
            return True
    return False


def validate_people_orgs(
    text: str, authors: list[str], affiliations: list[str]
) -> dict[str, Any]:
    """Cross-check LLM authors/affiliations against spaCy PERSON/ORG entities.

    Returns a dict with the kept (grounded) lists and the dropped candidates,
    plus whether validation actually ran. If the model is unavailable, nothing
    is dropped (graceful degradation) and ``validated`` is False.
    """
    if not model_available():
        return {
            "validated": False,
            "authors": authors,
            "affiliations": affiliations,
            "dropped_authors": [],
            "dropped_affiliations": [],
        }

    persons = _entities_by_label(text, {"PERSON"})
    orgs = _entities_by_label(text, {"ORG", "FAC", "GPE"})

    kept_authors = [a for a in authors if _grounded(a, persons)]
    dropped_authors = [a for a in authors if a not in kept_authors]

    kept_affils = [a for a in affiliations if _grounded(a, orgs)]
    dropped_affils = [a for a in affiliations if a not in kept_affils]

    return {
        "validated": True,
        "authors": kept_authors,
        "affiliations": kept_affils,
        "dropped_authors": dropped_authors,
        "dropped_affiliations": dropped_affils,
    }
