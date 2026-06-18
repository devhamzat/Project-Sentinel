"""Neo4j graph store: constraints + idempotent (MERGE) writes (CLAUDE.md §6).

Phase 1 writes the minimal thread: a Paper plus its Authors and the
AUTHORED_BY edges. Later phases extend this with Affiliation, Keyword, Dataset
and the USES relation.

Paper identity (per the developer's chosen dedup rule):
  1. If an arXiv id is known, MERGE the Paper on ``arxiv_id`` (most stable).
  2. Otherwise, if a Paper with the same title already exists, reuse it.
  3. Otherwise create a Paper keyed by (title, first author) so two distinct
     papers that share a title do not collide.

All writes use MERGE so re-ingesting a paper never duplicates nodes/edges.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from neo4j import Driver, GraphDatabase

from smart_extract.config import settings

# Uniqueness constraints. Author/Paper-title get constraints so MERGE is fast and
# safe; arXiv id is unique when present.
_CONSTRAINTS = [
    "CREATE CONSTRAINT paper_arxiv IF NOT EXISTS "
    "FOR (p:Paper) REQUIRE p.arxiv_id IS UNIQUE",
    "CREATE CONSTRAINT author_name IF NOT EXISTS "
    "FOR (a:Author) REQUIRE a.name IS UNIQUE",
]


class GraphStore:
    """Thin wrapper over the Neo4j driver for Phase-1 writes."""

    def __init__(self, driver: Driver | None = None) -> None:
        self._driver = driver or GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )

    def close(self) -> None:
        self._driver.close()

    def __enter__(self) -> "GraphStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- setup ---------------------------------------------------------------

    def ensure_constraints(self) -> None:
        """Create uniqueness constraints if they do not already exist."""
        with self._driver.session() as session:
            for stmt in _CONSTRAINTS:
                session.run(stmt)

    # --- writes --------------------------------------------------------------

    def upsert_paper(self, paper: dict[str, Any], arxiv_id: str | None) -> str:
        """MERGE a Paper + its Authors + AUTHORED_BY edges. Return the paper title.

        ``paper`` is the normalised extraction dict (see extraction.extract).
        """
        title = paper.get("title") or ""
        authors = paper.get("authors") or []
        if not title and not arxiv_id:
            raise ValueError("Cannot store a paper with neither a title nor an arXiv id.")

        first_author = authors[0] if authors else None

        with self._driver.session() as session:
            session.execute_write(
                self._write_paper, arxiv_id, title, paper, authors, first_author
            )
        return title

    @staticmethod
    def _write_paper(
        tx: Any,
        arxiv_id: str | None,
        title: str,
        paper: dict[str, Any],
        authors: list[str],
        first_author: str | None,
    ) -> None:
        # 1) MERGE the Paper on the best available key, then capture its
        #    internal element id so author edges attach to that exact node
        #    regardless of which key rule matched it.
        if arxiv_id:
            record = tx.run(
                """
                MERGE (p:Paper {arxiv_id: $arxiv_id})
                SET p.title = $title, p.year = $year, p.summary = $summary
                RETURN elementId(p) AS eid
                """,
                arxiv_id=arxiv_id, title=title, year=paper.get("year"),
                summary=paper.get("summary"),
            ).single()
        elif tx.run(
            "MATCH (p:Paper {title: $title}) RETURN p LIMIT 1", title=title
        ).single() is not None:
            # A same-title Paper already exists: reuse it.
            record = tx.run(
                """
                MATCH (p:Paper {title: $title})
                SET p.year = $year, p.summary = $summary
                RETURN elementId(p) AS eid
                """,
                title=title, year=paper.get("year"), summary=paper.get("summary"),
            ).single()
        else:
            # No arXiv id and no existing title: key by (title, first author)
            # so two distinct papers sharing a title do not collide.
            record = tx.run(
                """
                MERGE (p:Paper {title: $title, first_author: $first_author})
                SET p.year = $year, p.summary = $summary
                RETURN elementId(p) AS eid
                """,
                title=title, first_author=first_author,
                year=paper.get("year"), summary=paper.get("summary"),
            ).single()

        eid = record["eid"]

        # 2) MERGE each Author and the AUTHORED_BY edge onto that exact Paper.
        for name in authors:
            tx.run(
                """
                MATCH (p:Paper) WHERE elementId(p) = $eid
                MERGE (a:Author {name: $name})
                MERGE (p)-[:AUTHORED_BY]->(a)
                """,
                eid=eid, name=name,
            )


@contextmanager
def open_store() -> Iterator[GraphStore]:
    """Context-managed GraphStore using settings-configured connection."""
    store = GraphStore()
    try:
        yield store
    finally:
        store.close()
