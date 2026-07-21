"""Neo4j graph store: constraints + idempotent (MERGE) writes (CLAUDE.md §6).

Writes the full  model: Paper{title, year, summary} plus Author, Affiliation,
Keyword and Dataset nodes, with AUTHORED_BY, AFFILIATED_WITH, HAS_KEYWORD and
USES relationships (USES being the project's central contribution).

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

# Uniqueness constraints make MERGE fast and prevent duplicate entities.
# arXiv id is unique when present; the other entity keys are their names/terms.
_CONSTRAINTS = [
    "CREATE CONSTRAINT paper_arxiv IF NOT EXISTS "
    "FOR (p:Paper) REQUIRE p.arxiv_id IS UNIQUE",
    "CREATE CONSTRAINT author_name IF NOT EXISTS "
    "FOR (a:Author) REQUIRE a.name IS UNIQUE",
    "CREATE CONSTRAINT affiliation_name IF NOT EXISTS "
    "FOR (x:Affiliation) REQUIRE x.name IS UNIQUE",
    "CREATE CONSTRAINT keyword_term IF NOT EXISTS "
    "FOR (k:Keyword) REQUIRE k.term IS UNIQUE",
    "CREATE CONSTRAINT dataset_name IF NOT EXISTS "
    "FOR (d:Dataset) REQUIRE d.name IS UNIQUE",
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

    # --- reads ---------------------------------------------------------------

    def run_read(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        """Run a read query and return rows as plain dicts.

        Used by the NL->Cypher query path. The caller is responsible for
        ensuring ``cypher`` is read-only (see query.nl2cypher.is_read_only).
        """
        with self._driver.session() as session:
            result = session.run(cypher, **params)
            return [record.data() for record in result]

    def run_write(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        """Run a write/DDL query (used by the retrieval spike: index + chunks).

        Kept separate from ``run_read`` because the NL->Cypher path must only
        ever call ``run_read`` (its read-only guard depends on that). This method
        is for trusted internal Cypher (vector index creation, chunk writes), not
        for model-generated queries.
        """
        with self._driver.session() as session:
            result = session.run(cypher, **params)
            return [record.data() for record in result]

    def counts(self) -> dict[str, int]:
        """Return node/relationship counts for the dashboard summary."""
        out: dict[str, int] = {}
        with self._driver.session() as session:
            for label in ("Paper", "Author", "Affiliation", "Keyword", "Dataset"):
                out[label] = session.run(
                    f"MATCH (x:`{label}`) RETURN count(x) AS n"
                ).single()["n"]
            for rel in ("AUTHORED_BY", "AFFILIATED_WITH", "HAS_KEYWORD", "USES"):
                out[rel] = session.run(
                    f"MATCH ()-[r:`{rel}`]->() RETURN count(r) AS n"
                ).single()["n"]
        return out

    def sample_values(self, limit: int = 12) -> dict[str, list[str]]:
        """Return a few real values per entity type to ground the NL->Cypher prompt.

        Giving the model the actual dataset/author/keyword names that exist helps
        it map a vague question to what is really in the graph (fewer empty
        results from name/casing mismatches).
        """
        plan = {
            "datasets": ("Dataset", "name"),
            "keywords": ("Keyword", "term"),
            "authors": ("Author", "name"),
            "affiliations": ("Affiliation", "name"),
            "paper_titles": ("Paper", "title"),
        }
        out: dict[str, list[str]] = {}
        with self._driver.session() as session:
            for key, (label, prop) in plan.items():
                rows = session.run(
                    f"MATCH (x:`{label}`) WHERE x.`{prop}` IS NOT NULL "
                    f"RETURN x.`{prop}` AS v LIMIT $limit",
                    limit=limit,
                )
                out[key] = [r["v"] for r in rows]
        return out

    # --- writes --------------------------------------------------------------

    def upsert_paper(self, paper: dict[str, Any], arxiv_id: str | None) -> str:
        """MERGE a Paper and all its entities/relations. Return the paper title.

        Writes the full §6 model: Paper + Author (AUTHORED_BY) + Affiliation
        (AFFILIATED_WITH) + Keyword (HAS_KEYWORD) + Dataset (USES). ``paper`` is
        the normalised extraction dict (see extraction.extract).
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
        affiliations = paper.get("affiliations") or []
        keywords = paper.get("keywords") or []
        datasets = paper.get("datasets") or []

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

        # 3) Affiliations: (:Author)-[:AFFILIATED_WITH]->(:Affiliation), per §6.
        #    The LLM gives authors and affiliations as separate lists without a
        #    per-author mapping, so we link every listed author to every listed
        #    affiliation. This is exact for single-institution papers (the common
        #    case) and an over-approximation otherwise — a documented limitation,
        #    not a silent guess. Refining the mapping is future work.
        for affiliation in affiliations:
            for name in authors:
                tx.run(
                    """
                    MATCH (a:Author {name: $name})
                    MERGE (x:Affiliation {name: $affiliation})
                    MERGE (a)-[:AFFILIATED_WITH]->(x)
                    """,
                    name=name, affiliation=affiliation,
                )

        # 4) Keywords: (:Paper)-[:HAS_KEYWORD]->(:Keyword).
        for term in keywords:
            tx.run(
                """
                MATCH (p:Paper) WHERE elementId(p) = $eid
                MERGE (k:Keyword {term: $term})
                MERGE (p)-[:HAS_KEYWORD]->(k)
                """,
                eid=eid, term=term,
            )

        # 5) Datasets: (:Paper)-[:USES]->(:Dataset) — the central relation.
        for dataset in datasets:
            tx.run(
                """
                MATCH (p:Paper) WHERE elementId(p) = $eid
                MERGE (d:Dataset {name: $dataset})
                MERGE (p)-[:USES]->(d)
                """,
                eid=eid, dataset=dataset,
            )


@contextmanager
def open_store() -> Iterator[GraphStore]:
    """Context-managed GraphStore using settings-configured connection."""
    store = GraphStore()
    try:
        yield store
    finally:
        store.close()
