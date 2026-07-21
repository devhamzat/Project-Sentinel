"""Digital-PDF intake: extract the text layer from a born-digital PDF.

This is the *digital* lane (CLAUDE.md §5). It reads the real text layer with
PyMuPDF and never runs OCR (§13 — OCR is only for the image/photo lane in
Phase 2). The output is one clean-text string plus the arXiv id parsed from the
filename, ready for the shared extraction step.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import fitz  # PyMuPDF

from smart_extract.intake.base import (
    IntakeError,
    IntakeResult,
    arxiv_id_from_name,
)

# Re-export for any callers that imported these from intake.pdf historically.
__all__ = ["PdfIntakeError", "IntakeResult", "arxiv_id_from_name", "read_pdf"]

# A line that is nothing but a page number (optionally like "Page 12" or "12").
_PAGE_NUMBER_LINE = re.compile(r"^\s*(?:page\s+)?\d{1,4}\s*$", re.IGNORECASE)


class PdfIntakeError(IntakeError):
    """Raised when a PDF cannot be read or has no usable text layer."""


def _clean_pages(pages: list[str]) -> list[str]:
    """Remove running headers/footers and bare page-number lines from pages.

    Scanned/exported PDFs repeat the paper title (a running header) and a page
    number on most pages. Left in, these lines pollute chunks — a passage can
    open with a stray page number or the title, and the repeated header out-ranks
    real content on a title-shaped query. We detect a running header/footer as a
    short line that recurs verbatim near the top or bottom of many pages, and
    drop it along with any line that is only a page number. Body text (which does
    not repeat across pages) is untouched.
    """
    if len(pages) < 3:
        # Too few pages to tell a running header from a coincidental repeat.
        return [_drop_page_numbers(p) for p in pages]

    # A running header/footer recurs on many pages as the first/last non-empty
    # line. Count those candidate lines; treat any seen on >= half the pages as
    # boilerplate to strip wherever it appears.
    edge_lines: Counter[str] = Counter()
    for page in pages:
        nonempty = [ln.strip() for ln in page.splitlines() if ln.strip()]
        for ln in nonempty[:2] + nonempty[-2:]:  # top 2 + bottom 2 lines
            if len(ln) <= 120 and not _PAGE_NUMBER_LINE.match(ln):
                edge_lines[ln] += 1
    threshold = max(3, len(pages) // 2)
    boilerplate = {ln for ln, n in edge_lines.items() if n >= threshold}

    cleaned: list[str] = []
    for page in pages:
        kept = [
            ln for ln in page.splitlines()
            if ln.strip() not in boilerplate and not _PAGE_NUMBER_LINE.match(ln)
        ]
        cleaned.append("\n".join(kept))
    return cleaned


def _drop_page_numbers(page: str) -> str:
    """Drop lines that are only a page number (used when there are too few pages)."""
    return "\n".join(
        ln for ln in page.splitlines() if not _PAGE_NUMBER_LINE.match(ln)
    )


def read_pdf(path: str | Path) -> IntakeResult:
    """Extract clean text from a born-digital PDF.

    Raises PdfIntakeError if the file is missing, unreadable, or has no text
    layer (a likely sign it is a scan/photo — that belongs to the Phase-2 OCR
    lane, not here).
    """
    path = Path(path)
    if not path.exists():
        raise PdfIntakeError(f"No such file: {path}")

    try:
        with fitz.open(path) as doc:
            pages = [page.get_text() for page in doc]
    except Exception as exc:  # corrupt/encrypted/not-a-pdf
        raise PdfIntakeError(f"Could not read PDF {path.name}: {exc}") from exc

    # Strip running headers/footers and page numbers before anything downstream
    # sees the text, so chunks never open with a stray title or page number.
    pages = _clean_pages(pages)
    text = "\n".join(pages).strip()
    if not text:
        raise PdfIntakeError(
            f"{path.name} has no text layer. If this is a scan/photo, it needs "
            "the OCR lane (Phase 2), not the digital lane."
        )

    return IntakeResult(
        text=text,
        source_path=path,
        arxiv_id=arxiv_id_from_name(path),
        source_kind="digital",
        # Keep per-page text so chunks can record which page they came from; the
        # joined ``text`` above stays the source of truth for extraction.
        pages=pages,
    )
