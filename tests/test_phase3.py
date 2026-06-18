"""Tests for Phase-3 full extraction: content entities, USES grounding,
deterministic validation. Pure logic — no LLM, no Neo4j.
"""

from __future__ import annotations

import pytest


# --- normalisation: new content-entity fields ------------------------------

def test_normalise_includes_methods_and_metrics():
    from smart_extract.extraction.extract import normalise

    out = normalise({"title": "T", "methods": ["BERT"], "metrics": ["F1", "BLEU"]})
    assert out["methods"] == ["BERT"]
    assert out["metrics"] == ["F1", "BLEU"]
    # All §6 keys present.
    for key in ("authors", "affiliations", "keywords", "datasets", "summary"):
        assert key in out


def test_normalise_dedupes_case_insensitively():
    from smart_extract.extraction.extract import normalise

    out = normalise({"title": "T", "keywords": ["NLP", "nlp", " NLP ", "graphs"]})
    assert out["keywords"] == ["NLP", "graphs"]


# --- USES grounding: the central-relation guard ----------------------------

def test_ground_datasets_keeps_only_mentioned():
    from smart_extract.extraction.extract import ground_datasets

    text = "We evaluate on SQuAD and the GLUE benchmark."
    kept, dropped = ground_datasets(["SQuAD", "GLUE", "ImageNet"], text)
    assert set(kept) == {"SQuAD", "GLUE"}
    assert dropped == ["ImageNet"]


def test_ground_datasets_is_case_insensitive():
    from smart_extract.extraction.extract import ground_datasets

    kept, dropped = ground_datasets(["squad"], "Trained on SQuAD dataset.")
    assert kept == ["squad"]
    assert dropped == []


def test_ground_datasets_empty():
    from smart_extract.extraction.extract import ground_datasets

    assert ground_datasets([], "anything") == ([], [])


# --- spaCy validation: graceful + correct ----------------------------------

def test_validate_degrades_gracefully_without_model(monkeypatch):
    from smart_extract.extraction import nlp

    monkeypatch.setattr(nlp, "model_available", lambda: False)
    out = nlp.validate_people_orgs("some text", ["Ada Lovelace"], ["MIT"])
    assert out["validated"] is False
    # Nothing dropped when validation can't run.
    assert out["authors"] == ["Ada Lovelace"]
    assert out["affiliations"] == ["MIT"]


def test_validate_drops_ungrounded_when_model_present(monkeypatch):
    from smart_extract.extraction import nlp

    monkeypatch.setattr(nlp, "model_available", lambda: True)
    # Fake NER: only "ada lovelace" is a PERSON, only "mit" is an ORG.
    monkeypatch.setattr(
        nlp, "_entities_by_label",
        lambda text, labels: ({"ada lovelace"} if "PERSON" in labels else {"mit"}),
    )
    out = nlp.validate_people_orgs(
        "text", ["Ada Lovelace", "Fake McHallucination"], ["MIT", "Nowhere Institute"]
    )
    assert out["validated"] is True
    assert out["authors"] == ["Ada Lovelace"]
    assert out["dropped_authors"] == ["Fake McHallucination"]
    assert out["affiliations"] == ["MIT"]
    assert out["dropped_affiliations"] == ["Nowhere Institute"]


def test_grounded_token_overlap_helper():
    from smart_extract.extraction.nlp import _grounded

    # Matches on a shared significant token even without an exact span match.
    assert _grounded("Yoon Kim", {"kim"}) is True
    assert _grounded("Totally Unseen", {"kim", "mit"}) is False
