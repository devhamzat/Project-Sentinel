"""Offline tests for the Phase-1 digital thread (no network / Neo4j).

Cover the pure logic: arXiv id parsing, extraction normalisation, and the CLI
argument parser. The live Neo4j write is exercised separately by running the
CLI against the dev database (see README).
"""

from __future__ import annotations

from pathlib import Path

import pytest


# --- intake.pdf: arXiv id parsing ------------------------------------------

@pytest.mark.parametrize(
    "name,expected",
    [
        ("2606.18237v1.pdf", "2606.18237"),
        ("2606.18237.pdf", "2606.18237"),
        ("2401.01234v12.pdf", "2401.01234"),
        ("some-random-paper.pdf", None),
        ("notes.pdf", None),
    ],
)
def test_arxiv_id_from_name(name, expected):
    from smart_extract.intake.pdf import arxiv_id_from_name

    assert arxiv_id_from_name(Path(name)) == expected


def test_read_pdf_missing_file_raises():
    from smart_extract.intake.pdf import PdfIntakeError, read_pdf

    with pytest.raises(PdfIntakeError):
        read_pdf("does-not-exist.pdf")


# --- extraction.extract: normalisation -------------------------------------

def test_normalise_fills_missing_keys():
    from smart_extract.extraction.extract import normalise

    out = normalise({"title": "  A Paper  "})
    assert out["title"] == "A Paper"
    assert out["authors"] == []
    assert out["datasets"] == []
    assert out["year"] is None
    assert out["summary"] == ""


def test_normalise_coerces_types_and_strips():
    from smart_extract.extraction.extract import normalise

    out = normalise(
        {
            "title": "T",
            "year": "2023",
            "authors": ["  Ada  ", "", "Linus", 123],
            "keywords": ["nlp"],
            "datasets": ["SQuAD"],
        }
    )
    assert out["year"] == 2023
    # Empty strings dropped; ints coerced to str.
    assert out["authors"] == ["Ada", "Linus", "123"]
    assert out["keywords"] == ["nlp"]


def test_normalise_bad_year_becomes_none():
    from smart_extract.extraction.extract import normalise

    assert normalise({"title": "T", "year": "n/a"})["year"] is None
    assert normalise({"title": "T", "year": 2020})["year"] == 2020


# --- cli.main: parser -------------------------------------------------------

def test_cli_parser_requires_command():
    from smart_extract.cli.main import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_cli_parser_ingest():
    from smart_extract.cli.main import build_parser

    args = build_parser().parse_args(["ingest", "paper.pdf"])
    assert args.command == "ingest"
    assert args.path == "paper.pdf"
