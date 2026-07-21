"""Offline tests for PDF-intake text cleaning (no real PDF needed).

The page-cleaning helpers are pure functions over per-page text, so we exercise
the running-header and page-number stripping directly. Reading an actual PDF is
covered by the spike/manual runs, not here (keeps these tests offline per §12).
"""

from __future__ import annotations


def test_clean_pages_strips_running_header_and_page_numbers():
    from smart_extract.intake.pdf import _clean_pages

    header = "My Paper Title: A Study of Things"
    pages = [
        f"{header}\nBody of page {i} with real unique content here.\n{i}"
        for i in range(1, 7)
    ]
    cleaned = _clean_pages(pages)
    joined = "\n".join(cleaned)
    # The repeated header appears on every page -> stripped everywhere.
    assert header not in joined
    # Bare page-number lines are gone.
    assert not any(ln.strip() == "3" for ln in joined.splitlines())
    # Unique body text survives untouched.
    assert "Body of page 3 with real unique content here." in joined


def test_clean_pages_keeps_body_that_only_looks_like_a_header():
    from smart_extract.intake.pdf import _clean_pages

    # A line that appears on only one page is body content, not a running
    # header, and must be kept even if short.
    pages = [
        "Running Head Repeated\nIntroduction paragraph one.\n1",
        "Running Head Repeated\nA Unique Section Heading\nmore text.\n2",
        "Running Head Repeated\nConclusion paragraph.\n3",
    ]
    cleaned = "\n".join(_clean_pages(pages))
    assert "Running Head Repeated" not in cleaned      # on all 3 pages -> stripped
    assert "A Unique Section Heading" in cleaned        # on 1 page -> kept


def test_drop_page_numbers_matches_common_forms():
    from smart_extract.intake.pdf import _drop_page_numbers

    page = "Real sentence here.\n12\nPage 13\nAnother sentence."
    out = _drop_page_numbers(page)
    assert "Real sentence here." in out
    assert "Another sentence." in out
    assert "12" not in out.splitlines()
    assert "Page 13" not in out.splitlines()
