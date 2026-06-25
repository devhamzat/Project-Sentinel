"""Command-line interface — a thin door onto the backend.

Commands:
    sentinel ingest <path>     # ingest a PDF or photo into the graph
    sentinel ask "<question>"  # natural-language query (NL -> Cypher)
    sentinel stats             # node/relationship counts

Or without the console script: python -m smart_extract.cli.main <command> ...

All commands call smart_extract.service, the shared backend logic the REST API
uses too — so every door behaves identically.
"""

from __future__ import annotations

import argparse
import sys

from smart_extract.extraction.llm import LLMError
from smart_extract.intake import IntakeError
from smart_extract.query.nl2cypher import QueryError
from smart_extract import service


def _cmd_ingest(path: str) -> int:
    try:
        result = service.ingest_paper(path)
    except IntakeError as exc:
        print(f"FAILED - {exc}")
        return 1
    except LLMError as exc:
        print(f"FAILED - {exc}")
        return 1
    except ValueError as exc:
        print(f"FAILED - {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - surface Neo4j errors clearly
        print(f"FAILED - could not write to Neo4j: {exc}")
        return 1

    c = result["counts"]
    label = result["arxiv_id"] or result["title"] or result["source_path"]
    print(f"Read {result['source_kind']} source (id: {label}).")
    print(f"  title:    {result['title'] or '(none)'}")
    print(f"  authors:  {c['authors']}   affiliations: {c['affiliations']}")
    print(f"  keywords: {c['keywords']}   datasets: {c['datasets']} (USES)   "
          f"methods: {c['methods']}")

    v = result.get("validation", {})
    if not v.get("spacy_validated", True):
        print("  note: spaCy model not installed; author/affiliation validation skipped.")
    for field in ("dropped_datasets", "dropped_authors", "dropped_affiliations"):
        if v.get(field):
            print(f"  filtered {field.replace('dropped_', '')}: {v[field]}")

    print(
        f"OK - stored Paper '{result['title'] or label}' with "
        f"{c['authors']} author(s), {c['datasets']} dataset(s)."
    )
    return 0


def _cmd_ask(question: str) -> int:
    try:
        result = service.answer_question(question)
    except QueryError as exc:
        print(f"FAILED - {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED - {exc}")
        return 1

    if result.answer:
        print(result.answer + "\n")
    print(f"Cypher: {result.cypher}")
    if not result.rows:
        print("(no rows)")
        return 0
    print()
    for row in result.rows:
        print("  " + ", ".join(f"{k}={v}" for k, v in row.items()))
    print(f"\n{len(result.rows)} row(s).")
    return 0


def _cmd_stats() -> int:
    try:
        counts = service.graph_summary()
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED - {exc}")
        return 1
    for key, n in counts.items():
        print(f"  {key:16} {n}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sentinel",
        description="Smart Data Extraction - papers into a Neo4j knowledge graph.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="ingest a PDF or photo into the graph")
    p_ingest.add_argument("path", help="path to a born-digital PDF or a page image")

    p_ask = sub.add_parser("ask", help="ask a natural-language question (NL -> Cypher)")
    p_ask.add_argument("question", help="the question, in quotes")

    sub.add_parser("stats", help="show node/relationship counts")
    return parser


def _force_utf8_output() -> None:
    """Make stdout/stderr UTF-8 so printing non-Latin-1 metadata never crashes.

    On Windows the console defaults to cp1252; a paper whose title or author
    name contains an accented or non-Latin character would otherwise raise
    UnicodeEncodeError at print() time (after extraction, before the graph
    write), silently dropping the paper. ``errors="replace"`` degrades an
    unrepresentable glyph to '?' rather than ever failing.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # already detached / not reconfigurable
                pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    args = build_parser().parse_args(argv)
    if args.command == "ingest":
        return _cmd_ingest(args.path)
    if args.command == "ask":
        return _cmd_ask(args.question)
    if args.command == "stats":
        return _cmd_stats()
    return 1


if __name__ == "__main__":
    sys.exit(main())
