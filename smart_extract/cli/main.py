"""Command-line interface — a thin door onto the backend (CLAUDE.md §4).

Phase 1 exposes a single command:

    smart-extract ingest <path-to.pdf>
    # or, without the console script:
    python -m smart_extract.cli.main ingest <path-to.pdf>

It ties the digital lane together: intake (read PDF text) -> extract (LLM) ->
store (MERGE Paper + Authors into Neo4j). Done when a paper + its authors land
in the graph.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from smart_extract.extraction.extract import extract
from smart_extract.extraction.llm import LLMError
from smart_extract.graph.store import open_store
from smart_extract.intake import IntakeError, read_any


def ingest(path: str) -> int:
    """Ingest one paper (PDF or photo) into the graph. Return an exit code."""
    src_path = Path(path)
    try:
        intake = read_any(src_path)
    except IntakeError as exc:
        print(f"FAILED - {exc}")
        return 1

    label = intake.arxiv_id or src_path.name
    print(
        f"Read {len(intake.text)} chars from {src_path.name} "
        f"({intake.source_kind} lane, id: {label})."
    )
    print("Extracting structured fields via LLM ...")
    try:
        paper = extract(intake.text)
    except LLMError as exc:
        print(f"FAILED - {exc}")
        return 1

    if not paper["title"] and not intake.arxiv_id:
        print("FAILED - extraction produced no title and no arXiv id; nothing to store.")
        return 1

    print(f"  title:   {paper['title'] or '(none)'}")
    print(f"  authors: {len(paper['authors'])} found")

    try:
        with open_store() as store:
            store.ensure_constraints()
            store.upsert_paper(paper, intake.arxiv_id)
    except Exception as exc:  # noqa: BLE001 - surface Neo4j errors clearly
        print(f"FAILED - could not write to Neo4j: {exc}")
        return 1

    print(
        f"OK - stored Paper '{paper['title'] or label}' with "
        f"{len(paper['authors'])} author(s) in the graph."
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smart-extract",
        description="Smart Data Extraction — ingest papers into a Neo4j knowledge graph.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_ingest = sub.add_parser("ingest", help="ingest a digital PDF into the graph")
    p_ingest.add_argument("path", help="path to a born-digital PDF")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "ingest":
        return ingest(args.path)
    return 1  # argparse 'required=True' makes this unreachable, but be explicit.


if __name__ == "__main__":
    sys.exit(main())
