"""Digital-PDF intake: extract the text layer from a born-digital PDF.

This is the *digital* lane (CLAUDE.md §5). It reads the real text layer with
PyMuPDF and never runs OCR (§13 — OCR is only for the image/photo lane in
Phase 2). The output is one clean-text string plus the arXiv id parsed from the
filename, ready for the shared extraction step.
"""

from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

from smart_extract.intake.base import (
    IntakeError,
    IntakeResult,
    arxiv_id_from_name,
)

# Re-export for any callers that imported these from intake.pdf historically.
__all__ = ["PdfIntakeError", "IntakeResult", "arxiv_id_from_name", "read_pdf"]


class PdfIntakeError(IntakeError):
    """Raised when a PDF cannot be read or has no usable text layer."""


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
    )
