"""Offline tests for semantic retrieval (no network / Neo4j / embeddings).

Cover the pure chunking logic and the index/search plumbing with the embedding
seam and graph store faked out. Live vector search is exercised via
scripts/spike_retrieve.py against the dev database.
"""

from __future__ import annotations

import pytest


# --- chunk_text: pure, deterministic ----------------------------------------

def test_chunk_text_empty_returns_nothing():
    from smart_extract.query.retrieve import chunk_text

    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_chunk_text_short_text_is_one_chunk():
    from smart_extract.query.retrieve import chunk_text

    text = "A short paragraph.\n\nAnd another one."
    chunks = chunk_text(text, target_chars=1200)
    assert len(chunks) == 1
    assert "A short paragraph." in chunks[0]
    assert "And another one." in chunks[0]


def test_chunk_text_is_deterministic():
    from smart_extract.query.retrieve import chunk_text

    text = "\n\n".join(f"Paragraph {i}. " + "word " * 40 for i in range(30))
    assert chunk_text(text) == chunk_text(text)


def test_chunk_text_respects_target_size():
    from smart_extract.query.retrieve import chunk_text

    text = "\n\n".join("word " * 60 for _ in range(40))
    chunks = chunk_text(text, target_chars=500, overlap_chars=80)
    assert len(chunks) > 1
    # Greedy packing may slightly exceed the target (one piece of slack), but
    # nothing should balloon far beyond it.
    assert all(len(c) <= 500 + 400 for c in chunks)


def test_chunk_text_hard_splits_oversized_paragraph():
    from smart_extract.query.retrieve import chunk_text

    text = "x" * 3000  # one giant "paragraph", no blank lines
    chunks = chunk_text(text, target_chars=1000, overlap_chars=100)
    assert len(chunks) >= 3
    assert all(len(c) <= 1400 for c in chunks)


def test_chunk_text_overlap_carries_tail():
    from smart_extract.query.retrieve import chunk_text

    paras = [f"P{i} " + "word " * 50 for i in range(10)]
    chunks = chunk_text("\n\n".join(paras), target_chars=400, overlap_chars=60)
    assert len(chunks) > 1
    # Each later chunk starts with the tail of its predecessor.
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt[:20] in prev


def test_chunk_text_no_duplicated_prefix_on_hard_split():
    from smart_extract.query.retrieve import chunk_text

    # A single giant paragraph (no blank lines) exercises the hard-split path;
    # packer tails must not re-prepend the overlap the windows already carry.
    text = " ".join(f"w{i}" for i in range(2000))
    chunks = chunk_text(text, target_chars=800, overlap_chars=120)
    for c in chunks:
        head = c[:60]
        assert c.count(head) == 1, f"duplicated opening text in chunk: {head!r}"


# --- looks_like_references ---------------------------------------------------

def test_bibliography_chunk_is_detected():
    from smart_extract.query.retrieve import looks_like_references

    refs = " ".join(
        f"[{i}] Author {i}, Another Author. Some Cited Paper Title {i}. "
        f"In Proceedings of the Conference, pages {i}0-{i}9, {2020 + i % 5}."
        for i in range(1, 7)
    )
    assert looks_like_references(refs)


def test_content_with_inline_citations_is_kept():
    from smart_extract.query.retrieve import looks_like_references

    content = (
        "Recent work [1] challenges agents to reproduce results, while other "
        "benchmarks [2] focus on code generation. We instead audit real "
        "repositories, extending ideas from prior studies [3] with a scalable "
        "pipeline that mines issue trackers for reproduction blockers."
    )
    assert not looks_like_references(content)


def test_plain_content_is_kept():
    from smart_extract.query.retrieve import looks_like_references

    assert not looks_like_references(
        "We evaluate on a held-out set of repositories and report accuracy. " * 5
    )


def test_index_paper_skips_bibliography_chunks(fake_embed):
    from smart_extract.query.retrieve import index_paper

    body = "Real content about the method. " * 20
    refs = "\n\n" + " ".join(
        f"[{i}] Someone et al. A Paper. arXiv preprint arXiv:2401.0000{i}, "
        f"{2020 + i % 5}. doi: 10.1234/{i}."
        for i in range(1, 8)
    )
    store = FakeStore()
    n = index_paper(store, "2606.18237", "A Paper", body + refs)
    _, chunk_params = store.writes[2]
    texts = [r["text"] for r in chunk_params["rows"]]
    assert n == len(texts)
    assert all("arXiv preprint" not in t for t in texts)
    assert any("Real content" in t for t in texts)


# --- index/search plumbing with fakes ---------------------------------------

class FakeStore:
    """Records writes; returns canned rows for the vector read."""

    def __init__(self, read_rows=None, read_exc=None):
        self.writes: list[tuple[str, dict]] = []
        self._read_rows = read_rows or []
        self._read_exc = read_exc

    def run_write(self, cypher, **params):
        self.writes.append((cypher, params))
        return []

    def run_read(self, cypher, **params):
        if self._read_exc:
            raise self._read_exc
        return self._read_rows


@pytest.fixture
def fake_embed(monkeypatch):
    """Replace the embedding seam with a deterministic 3-dim fake."""
    from smart_extract.query import retrieve

    def _embed(texts):
        return [[1.0, 0.0, 0.0] for _ in texts]

    monkeypatch.setattr(retrieve, "embed", _embed)
    return _embed


def test_index_paper_writes_chunks_keyed_by_arxiv_id(fake_embed):
    from smart_extract.query.retrieve import index_paper

    store = FakeStore()
    n = index_paper(store, "2606.18237", "A Paper", "Some body text.")
    assert n == 1
    # constraint + vector index + chunk write + stale-chunk cleanup
    assert len(store.writes) == 4
    chunk_cypher, chunk_params = store.writes[2]
    assert "MERGE (c:Chunk" in chunk_cypher
    assert chunk_params["paper_key"] == "2606.18237"
    assert chunk_params["rows"][0]["embedding"] == [1.0, 0.0, 0.0]


def test_index_paper_falls_back_to_title_key(fake_embed):
    from smart_extract.query.retrieve import index_paper

    store = FakeStore()
    index_paper(store, None, "A Photographed Paper", "Body text here.")
    _, chunk_params = store.writes[2]
    # MERGE cannot key on null, so the title stands in for a missing arXiv id.
    assert chunk_params["paper_key"] == "A Photographed Paper"


def test_index_paper_deletes_stale_higher_index_chunks(fake_embed):
    from smart_extract.query.retrieve import index_paper

    store = FakeStore()
    n = index_paper(store, "2606.18237", "A Paper", "Some body text.")
    cleanup_cypher, cleanup_params = store.writes[-1]
    assert "DETACH DELETE" in cleanup_cypher
    assert cleanup_params == {"paper_key": "2606.18237", "n": n}


def test_index_paper_no_text_writes_nothing(fake_embed):
    from smart_extract.query.retrieve import index_paper

    store = FakeStore()
    assert index_paper(store, "2606.18237", "A Paper", "   ") == 0
    assert store.writes == []


def test_retrieve_ranks_rows_into_chunks(fake_embed):
    from smart_extract.query.retrieve import retrieve

    store = FakeStore(read_rows=[
        {"arxiv_id": "2606.18237", "title": "A Paper", "text": "passage",
         "chunk_index": 3, "score": 0.91},
    ])
    result = retrieve("what about things?", k=1, store=store)
    assert result.query == "what about things?"
    assert len(result.chunks) == 1
    assert result.chunks[0].paper_title == "A Paper"
    assert result.chunks[0].score == pytest.approx(0.91)


def test_retrieve_missing_index_raises_clear_error(fake_embed):
    from smart_extract.query.retrieve import RetrievalError, retrieve

    store = FakeStore(read_exc=RuntimeError("There is no such vector schema index"))
    with pytest.raises(RetrievalError, match="No content is indexed"):
        retrieve("anything", store=store)


# --- CLI parser --------------------------------------------------------------

def test_cli_parses_search_command():
    from smart_extract.cli.main import build_parser

    args = build_parser().parse_args(["search", "papers about hallucination", "-k", "3"])
    assert args.command == "search"
    assert args.query == "papers about hallucination"
    assert args.k == 3
