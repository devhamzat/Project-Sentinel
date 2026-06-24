"""Natural-language querying: translate a question to Cypher and run it (§5, §10).

An LLM turns the user's plain-English question into a Cypher query against the
fixed §6 schema (the schema + examples are few-shot in the prompt), we verify
the query is read-only, run it, and return both the Cypher and the rows.

Returning the generated Cypher (not just the answer) is deliberate: it is
transparent for the user and gives Chapter 4 concrete translation examples.

Safety: the LLM output is never trusted blindly. ``is_read_only`` rejects any
query containing a write/admin clause before it ever touches the database.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from smart_extract.extraction.llm import LLMError, complete
from smart_extract.graph.store import GraphStore, open_store

# Clauses that mutate or administer the graph. A generated query containing any
# of these (as a whole word) is refused — the NL query path is read-only.
_FORBIDDEN = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD\s+CSV|CALL\s+db\.|"
    r"CALL\s+apoc\.\w+\.(?:create|delete|remove)|FOREACH)\b",
    re.IGNORECASE,
)

# The schema we expose to the model, mirroring CLAUDE.md §6.
SCHEMA_DESCRIPTION = """\
Graph schema (Neo4j):
Nodes:
  (:Paper {arxiv_id, title, year, summary})
  (:Author {name})
  (:Affiliation {name})
  (:Keyword {term})
  (:Dataset {name})
Relationships:
  (:Paper)-[:AUTHORED_BY]->(:Author)
  (:Author)-[:AFFILIATED_WITH]->(:Affiliation)
  (:Paper)-[:HAS_KEYWORD]->(:Keyword)
  (:Paper)-[:USES]->(:Dataset)
"""

_FEW_SHOT = """\
Examples (note: always match strings with WHERE ... CONTAINS, never with an
inline {property: "..."} map, since stored values may differ in length/case):
Q: Which papers use the SQuAD dataset?
Cypher: MATCH (p:Paper)-[:USES]->(d:Dataset) WHERE toLower(d.name) CONTAINS 'squad' RETURN p.title AS paper

Q: Who wrote "Variable-Width Transformers"?
Cypher: MATCH (p:Paper)-[:AUTHORED_BY]->(a:Author) WHERE toLower(p.title) CONTAINS 'variable-width transformers' RETURN a.name AS author

Q: Which datasets does the ReproRepo paper use?
Cypher: MATCH (p:Paper)-[:USES]->(d:Dataset) WHERE toLower(p.title) CONTAINS 'reprorepo' RETURN d.name AS dataset

Q: What datasets are used most often?
Cypher: MATCH (:Paper)-[:USES]->(d:Dataset) RETURN d.name AS dataset, count(*) AS uses ORDER BY uses DESC

Q: Which author has the most papers?
Cypher: MATCH (p:Paper)-[:AUTHORED_BY]->(a:Author) RETURN a.name AS author, count(p) AS papers ORDER BY papers DESC LIMIT 1

Q: List all papers and their publication year.
Cypher: MATCH (p:Paper) RETURN p.title AS paper, p.year AS year ORDER BY year
"""

_SYSTEM = (
    "You translate natural-language questions into a single read-only Cypher "
    "query for the given graph schema. Output ONLY the Cypher query, no prose, "
    "no markdown fences, no explanation. Never write, update, or delete data. "
    "For matching titles, author names, dataset names, etc., ALWAYS use a "
    "case-insensitive partial match (toLower(x) CONTAINS toLower('...')), never "
    "exact string equality, because stored values may be longer or differently "
    "cased than the user's phrasing. "
    "If you ORDER BY or filter on an aggregate like count(...), that aggregate "
    "MUST also appear in the RETURN clause with an alias; never ORDER BY "
    "count(*) unless count(*) is also returned. Prefer counting with "
    "count(node) grouped by the RETURN keys rather than self-joins."
)


class QueryError(RuntimeError):
    """Raised when a question cannot be answered safely."""


@dataclass
class QueryResult:
    question: str
    cypher: str
    rows: list[dict[str, Any]]
    answer: str = ""  # natural-language phrasing of the rows


# System prompt for turning result rows into a plain-English answer.
_ANSWER_SYSTEM = (
    "You answer a user's question using ONLY the provided query results from a "
    "knowledge graph of academic papers. Write one or two natural sentences. "
    "If the results are empty, say plainly that the graph contains nothing "
    "matching, and (if helpful) mention what kinds of things it does contain. "
    "Never invent data that is not in the results. Be concise."
)


def is_read_only(cypher: str) -> bool:
    """True if the query contains no write/admin clauses."""
    return _FORBIDDEN.search(cypher) is None


def _clean_cypher(raw: str) -> str:
    """Strip markdown fences / stray prose the model may wrap around the query."""
    text = raw.strip()
    if text.startswith("```"):
        # remove the opening fence (optionally ```cypher) and the closing fence
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    # If the model still added a leading label like "Cypher:", drop it.
    text = re.sub(r"^\s*cypher\s*:\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


def _finalise(raw: str) -> str:
    """Clean LLM output and enforce the read-only guard. Raises QueryError."""
    cypher = _clean_cypher(raw)
    if not cypher:
        raise QueryError("The model returned an empty query.")
    if not is_read_only(cypher):
        raise QueryError(
            "Refused to run a non-read-only query generated by the model:\n"
            f"{cypher}"
        )
    return cypher


def _sample_block(samples: dict[str, list[str]] | None) -> str:
    """Render real graph values into a prompt hint, or empty if none."""
    if not samples:
        return ""
    lines = ["Real values currently in the graph (match the user's wording to these):"]
    for key, values in samples.items():
        if values:
            shown = ", ".join(values[:12])
            lines.append(f"  {key}: {shown}")
    return "\n".join(lines) + "\n" if len(lines) > 1 else ""


def to_cypher(question: str, samples: dict[str, list[str]] | None = None) -> str:
    """Translate a question to Cypher via the LLM seam (no execution).

    ``samples`` are real values from the graph; including them helps the model
    map vague wording to entities that actually exist.
    """
    prompt = (
        f"{SCHEMA_DESCRIPTION}\n{_sample_block(samples)}{_FEW_SHOT}\n"
        f"Q: {question}\nCypher:"
    )
    try:
        raw = complete(prompt, system=_SYSTEM)
    except LLMError as exc:
        raise QueryError(f"Could not generate a query: {exc}") from exc
    return _finalise(raw)


def repair_cypher(question: str, bad_cypher: str, error: str) -> str:
    """Ask the LLM to fix a Cypher query that failed, given the DB error."""
    prompt = (
        f"{SCHEMA_DESCRIPTION}\n"
        "The following Cypher query failed. Fix it so it is valid and answers "
        "the question. Output ONLY the corrected read-only Cypher.\n\n"
        f"Question: {question}\n"
        f"Broken query: {bad_cypher}\n"
        f"Neo4j error: {error}\n"
        "Corrected Cypher:"
    )
    try:
        raw = complete(prompt, system=_SYSTEM)
    except LLMError as exc:
        raise QueryError(f"Could not repair the query: {exc}") from exc
    return _finalise(raw)


def phrase_answer(
    question: str, rows: list[dict[str, Any]], samples: dict[str, list[str]] | None
) -> str:
    """Turn result rows into a plain-English answer (graceful when empty)."""
    if rows:
        preview = rows[:30]
        body = f"Question: {question}\nResults (JSON): {json.dumps(preview, default=str)}"
    else:
        hint = _sample_block(samples).strip()
        body = (
            f"Question: {question}\nResults: (none)\n{hint}\n"
            "Tell the user nothing matched, and what the graph does contain."
        )
    try:
        return complete(body, system=_ANSWER_SYSTEM).strip()
    except LLMError:
        # Phrasing is a nicety; never fail the whole query because of it.
        return ""


def ask(question: str, store: GraphStore | None = None) -> QueryResult:
    """Answer a natural-language question against the graph.

    Pipeline: gather real sample values -> translate to Cypher (grounded in
    those values) -> run (with one self-healing repair pass on DB error) ->
    phrase the rows as a natural-language answer.
    """

    def _answer(s: GraphStore) -> QueryResult:
        try:
            samples = s.sample_values()
        except Exception:  # noqa: BLE001 - sampling is best-effort
            samples = None

        cypher = to_cypher(question, samples)
        try:
            rows = s.run_read(cypher)
        except Exception as first_exc:  # noqa: BLE001 - try one repair pass
            try:
                cypher = repair_cypher(question, cypher, str(first_exc))
                rows = s.run_read(cypher)
            except QueryError:
                raise
            except Exception:  # noqa: BLE001 - repair also failed
                raise QueryError(
                    f"The generated query failed to run:\n{cypher}\n\n{first_exc}"
                ) from first_exc

        answer = phrase_answer(question, rows, samples)
        return QueryResult(question=question, cypher=cypher, rows=rows, answer=answer)

    if store is not None:
        return _answer(store)
    with open_store() as s:
        return _answer(s)
