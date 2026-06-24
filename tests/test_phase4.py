"""Tests for Phase-4 pure logic: NL->Cypher safety guard and eval metrics.

No LLM / Neo4j here — the read-only guard and the metrics math are unit-tested
offline; live NL querying is exercised by running the CLI/API against the dev DB.
"""

from __future__ import annotations

import pytest


# --- NL->Cypher safety guard ------------------------------------------------

@pytest.mark.parametrize("cypher", [
    "MATCH (p:Paper) RETURN p.title",
    "MATCH (p:Paper)-[:USES]->(d:Dataset) RETURN d.name, count(*)",
    "MATCH (a:Author) WHERE a.name CONTAINS 'Kim' RETURN a",
])
def test_read_only_accepts_read_queries(cypher):
    from smart_extract.query.nl2cypher import is_read_only

    assert is_read_only(cypher) is True


@pytest.mark.parametrize("cypher", [
    "MATCH (p:Paper) DETACH DELETE p",
    "CREATE (p:Paper {title: 'x'})",
    "MATCH (p:Paper) SET p.title = 'x'",
    "MERGE (a:Author {name: 'x'})",
    "MATCH (p:Paper) REMOVE p.title",
    "DROP CONSTRAINT paper_arxiv",
])
def test_read_only_rejects_write_queries(cypher):
    from smart_extract.query.nl2cypher import is_read_only

    assert is_read_only(cypher) is False


def test_clean_cypher_strips_fences_and_labels():
    from smart_extract.query.nl2cypher import _clean_cypher

    assert _clean_cypher("```cypher\nMATCH (p) RETURN p\n```") == "MATCH (p) RETURN p"
    assert _clean_cypher("Cypher: MATCH (p) RETURN p") == "MATCH (p) RETURN p"


def test_to_cypher_refuses_write_query(monkeypatch):
    from smart_extract.query import nl2cypher

    monkeypatch.setattr(nl2cypher, "complete", lambda *a, **k: "MATCH (p) DELETE p")
    with pytest.raises(nl2cypher.QueryError):
        nl2cypher.to_cypher("delete everything")


class _FakeStore:
    """Fails the first query, succeeds on the (repaired) second."""

    def __init__(self):
        self.calls = 0

    def sample_values(self, limit=12):
        return {"datasets": ["CORE-Bench"]}

    def run_read(self, cypher, **params):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("SyntaxError: bad aggregation in ORDER BY")
        return [{"ok": 1}]


def test_ask_retries_on_failure(monkeypatch):
    from smart_extract.query import nl2cypher

    # complete() is called for: to_cypher, repair_cypher, then phrase_answer.
    replies = iter([
        "MATCH (p:Paper) RETURN p ORDER BY count(*)",   # initial -> store rejects
        "MATCH (p:Paper) RETURN count(p) AS n",          # repaired -> store ok
        "There is 1 paper.",                             # phrased answer
    ])
    monkeypatch.setattr(nl2cypher, "complete", lambda *a, **k: next(replies))

    store = _FakeStore()
    result = nl2cypher.ask("how many papers", store=store)
    assert store.calls == 2          # original failed, repair ran
    assert result.rows == [{"ok": 1}]
    assert "count(p)" in result.cypher
    assert result.answer == "There is 1 paper."


def test_ask_reports_error_when_repair_also_fails(monkeypatch):
    from smart_extract.query import nl2cypher

    monkeypatch.setattr(nl2cypher, "complete",
                        lambda *a, **k: "MATCH (p:Paper) RETURN p ORDER BY count(*)")

    class AlwaysFails:
        def sample_values(self, limit=12):
            return {}

        def run_read(self, cypher, **params):
            raise RuntimeError("still broken")

    with pytest.raises(nl2cypher.QueryError):
        nl2cypher.ask("q", store=AlwaysFails())


def test_phrase_answer_handles_empty_and_never_raises(monkeypatch):
    from smart_extract.query import nl2cypher

    # Even if phrasing the answer errors, it must degrade to "" not crash.
    def boom(*a, **k):
        raise nl2cypher.LLMError("model down")

    monkeypatch.setattr(nl2cypher, "complete", boom)
    assert nl2cypher.phrase_answer("q", [], {"datasets": ["X"]}) == ""


def test_sample_block_renders_real_values():
    from smart_extract.query.nl2cypher import _sample_block

    out = _sample_block({"datasets": ["CORE-Bench", "PaperBench"], "keywords": []})
    assert "CORE-Bench" in out and "datasets" in out
    assert _sample_block(None) == ""
    assert _sample_block({"datasets": []}) == ""


# --- evaluation metrics -----------------------------------------------------

def test_prf_basic():
    from smart_extract.evaluation.metrics import PRF

    prf = PRF(tp=8, fp=2, fn=2)
    assert prf.precision == 0.8
    assert prf.recall == 0.8
    assert prf.f1 == pytest.approx(0.8)


def test_prf_zero_division_safe():
    from smart_extract.evaluation.metrics import PRF

    empty = PRF(0, 0, 0)
    assert empty.precision == 0.0 and empty.recall == 0.0 and empty.f1 == 0.0


def test_score_field_is_set_and_case_insensitive():
    from smart_extract.evaluation.metrics import score_field

    prf = score_field(["SQuAD", "glue"], ["squad", "GLUE", "ImageNet"])
    assert prf.tp == 2  # squad, glue matched
    assert prf.fp == 0
    assert prf.fn == 1  # imagenet missed


def test_aggregate_micro_average():
    from smart_extract.evaluation.metrics import PRF, aggregate

    p1 = {f: PRF(1, 0, 0) for f in ("authors",)}
    p2 = {f: PRF(0, 1, 1) for f in ("authors",)}
    # Fill the rest of the required fields with zeros so aggregate keys line up.
    from smart_extract.evaluation.metrics import EVAL_FIELDS
    for d in (p1, p2):
        for f in EVAL_FIELDS:
            d.setdefault(f, PRF(0, 0, 0))

    agg = aggregate([p1, p2])
    assert agg["authors"].tp == 1 and agg["authors"].fp == 1 and agg["authors"].fn == 1
    assert "overall" in agg
