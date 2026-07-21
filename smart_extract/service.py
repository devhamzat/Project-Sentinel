"""Backend service layer — the single source of truth all doors call (§4).

The CLI, REST API, and (via the API) the web dashboard all go through these
functions, so business logic lives in exactly one place. Each function ties the
pipeline stages together and returns plain data (dicts/dataclasses) rather than
printing, so any door can present the result however it likes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from smart_extract.extraction.extract import extract
from smart_extract.graph.store import open_store
from smart_extract.intake import read_any
from smart_extract.query.nl2cypher import QueryResult, ask
from smart_extract.query.retrieve import RetrievalResult, index_paper, search


def ingest_paper(path: str | Path) -> dict[str, Any]:
    """Ingest one paper (PDF or photo) into the graph.

    Returns a summary dict: source kind, arxiv id, extracted entity counts, and
    what the deterministic guards filtered. Raises IntakeError / LLMError /
    Neo4j errors to the caller, which decides how to present them.

    Also chunk-indexes the paper's text for semantic search. That step is
    best-effort: the graph write has already succeeded, and embeddings may
    simply not be configured (LLM_EMBED_* unset), so a failure here is reported
    in the result (``chunks_error``) rather than raised.
    """
    intake = read_any(path)
    paper = extract(intake.text)

    if not paper["title"] and not intake.arxiv_id:
        raise ValueError("Extraction produced no title and no arXiv id; nothing to store.")

    chunks_indexed = 0
    chunks_error: str | None = None
    with open_store() as store:
        store.ensure_constraints()
        store.upsert_paper(paper, intake.arxiv_id)
        try:
            chunks_indexed = index_paper(
                store, intake.arxiv_id, paper["title"], intake.text
            )
        except Exception as exc:  # noqa: BLE001 - semantic index is an add-on
            chunks_error = str(exc)

    validation = paper.get("_validation", {})
    return {
        "source_path": str(intake.source_path),
        "source_kind": intake.source_kind,
        "arxiv_id": intake.arxiv_id,
        "title": paper["title"],
        "year": paper["year"],
        "summary": paper["summary"],
        "counts": {
            "authors": len(paper["authors"]),
            "affiliations": len(paper["affiliations"]),
            "keywords": len(paper["keywords"]),
            "datasets": len(paper["datasets"]),
            "methods": len(paper["methods"]),
            "metrics": len(paper["metrics"]),
        },
        "validation": validation,
        "chunks_indexed": chunks_indexed,
        "chunks_error": chunks_error,
    }


def answer_question(question: str) -> QueryResult:
    """Answer a natural-language question against the graph (NL -> Cypher)."""
    return ask(question)


def search_content(query: str, k: int = 5) -> RetrievalResult:
    """Semantic search over paper content: ranked passages + a grounded answer.

    The complement of answer_question: that one answers structured questions
    over extracted entities (NL -> Cypher); this one finds passages by meaning
    in the papers' text (vector search over chunks) and phrases a cited answer.
    """
    return search(query, k=k)


def graph_summary() -> dict[str, int]:
    """Return node/relationship counts for the dashboard overview."""
    with open_store() as store:
        return store.counts()
