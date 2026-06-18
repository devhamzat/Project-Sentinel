"""Offline smoke tests for the Phase-0 scaffold.

These must NOT touch the network, the LLM, or Neo4j (CLAUDE.md §12). They check
that the package imports, config loads, the prompt is well-formed, and the LLM
seam's JSON recovery / error handling behave — using a monkeypatched client.
"""

from __future__ import annotations

import json

import pytest


def test_package_imports():
    import smart_extract

    assert smart_extract.__version__


def test_settings_load_and_paths():
    from smart_extract.config import settings

    # Defaults exist even without a .env file present.
    assert settings.neo4j_uri
    assert settings.llm_model
    # Derived paths resolve under the data dir.
    assert settings.raw_dir.name == "raw"
    assert settings.gold_dir.name == "gold"
    assert settings.raw_dir.parent == settings.data_path


def test_extraction_prompt_contains_schema_and_text():
    from smart_extract.extraction.prompts import EXTRACTION_SYSTEM, extraction_prompt

    prompt = extraction_prompt("Hello world paper about BERT on SQuAD.")
    # Mentions the key schema fields from CLAUDE.md §6.
    for key in ("title", "authors", "datasets", "summary"):
        assert key in prompt
    assert "BERT on SQuAD" in prompt
    assert "JSON" in EXTRACTION_SYSTEM


def test_extraction_prompt_truncates_long_text():
    from smart_extract.extraction.prompts import extraction_prompt

    body = "Q" * 50_000  # a char that does not appear in the schema block
    prompt = extraction_prompt(body, max_chars=1000)
    # The paper body is truncated to max_chars; the full 50k must not survive.
    assert prompt.count("Q") == 1000


def test_llm_extract_json_recovers_from_fenced_output(monkeypatch):
    """If the model wraps JSON in prose/fences, extract_json should recover it."""
    from smart_extract.extraction import llm

    noisy = 'Sure! Here you go:\n```json\n{"title": "T", "authors": ["A"]}\n```'
    monkeypatch.setattr(llm, "_chat", lambda *a, **k: noisy)

    result = llm.extract_json("prompt")
    assert result == {"title": "T", "authors": ["A"]}


def test_llm_extract_json_raises_on_unparseable(monkeypatch):
    from smart_extract.extraction import llm

    monkeypatch.setattr(llm, "_chat", lambda *a, **k: "no json at all here")
    with pytest.raises(llm.LLMError):
        llm.extract_json("prompt")


def test_llm_complete_passes_through(monkeypatch):
    from smart_extract.extraction import llm

    monkeypatch.setattr(llm, "_chat", lambda prompt, system, **k: f"echo:{prompt}")
    assert llm.complete("hi") == "echo:hi"


def test_extract_json_object_helper():
    from smart_extract.extraction.llm import _extract_json_object

    assert _extract_json_object('prefix {"a": 1} suffix') == {"a": 1}
    assert _extract_json_object("no braces") is None
    # A bare JSON array is not an object -> None.
    assert _extract_json_object("[1, 2, 3]") is None
