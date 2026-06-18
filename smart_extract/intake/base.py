"""Shared intake types: the one clean-text representation both lanes produce.

Per CLAUDE.md §5, the digital-PDF lane and the image/OCR lane converge on a
single clean-text object so everything downstream (extract, store) is
lane-agnostic. ``source_kind`` records which lane produced the text, which is
exactly the field the Phase-2 robustness evaluation groups by (digital vs photo).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# arXiv ids look like 2606.18237 or 2606.18237v1. We accept the new-style form.
_ARXIV_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")

SourceKind = Literal["digital", "photo"]


class IntakeError(RuntimeError):
    """Base error for any intake lane (PDF read, OCR, etc.)."""


@dataclass
class IntakeResult:
    """The clean-text representation both intake lanes converge on."""

    text: str
    source_path: Path
    arxiv_id: str | None       # parsed from the filename when present
    source_kind: SourceKind    # "digital" (PDF text layer) or "photo" (OCR)


def arxiv_id_from_name(path: Path) -> str | None:
    """Return the arXiv id embedded in a filename, dropping any version suffix.

    e.g. ``2606.18237v1.pdf`` -> ``2606.18237``. Returns None if absent.
    """
    m = _ARXIV_RE.search(path.stem)
    return m.group(1) if m else None
