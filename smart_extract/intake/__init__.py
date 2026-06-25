"""Intake lanes: digital PDF (text layer) and image/photo (OCR).

Both lanes converge on one clean-text representation (``IntakeResult``). The
``read_any`` dispatcher picks the right lane by file extension so callers (e.g.
the CLI ``ingest`` command) can handle either a PDF or a photo transparently.
"""

from __future__ import annotations

from pathlib import Path

from smart_extract.intake.base import (
    IntakeError,
    IntakeResult,
    SourceKind,
    arxiv_id_from_name,
)
from smart_extract.intake.image import IMAGE_SUFFIXES, read_image
from smart_extract.intake.pdf import read_pdf

__all__ = [
    "IntakeError",
    "IntakeResult",
    "SourceKind",
    "arxiv_id_from_name",
    "read_any",
    "read_pdf",
    "read_image",
]


def read_any(path: str | Path) -> IntakeResult:
    """Read a file through the appropriate intake lane, chosen by extension.

    ``.pdf`` -> digital lane (text layer). Image suffixes -> photo lane (OCR).
    Raises IntakeError for unsupported extensions.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return read_pdf(path)
    if suffix in IMAGE_SUFFIXES:
        return read_image(path)
    raise IntakeError(
        f"Unsupported file type '{suffix}' for {path.name}. "
        f"Expected .pdf or one of {sorted(IMAGE_SUFFIXES)}."
    )
