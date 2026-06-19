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


def ingest_paper(path: str | Path) -> dict[str, Any]:
    """Ingest one paper (PDF or photo) into the graph.

    Returns a summary dict: source kind, arxiv id, extracted entity counts, and
    what the deterministic guards filtered. Raises IntakeError / LLMError /
    Neo4j errors to the caller, which decides how to present them.
    """
    intake = read_any(path)
    paper = extract(intake.text)

    if not paper["title"] and not intake.arxiv_id:
        raise ValueError("Extraction produced no title and no arXiv id; nothing to store.")

    with open_store() as store:
        store.ensure_constraints()
        store.upsert_paper(paper, intake.arxiv_id)

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
    }


def answer_question(question: str) -> QueryResult:
    """Answer a natural-language question against the graph (NL -> Cypher)."""
    return ask(question)


def graph_summary() -> dict[str, int]:
    """Return node/relationship counts for the dashboard overview."""
    with open_store() as store:
        return store.counts()
