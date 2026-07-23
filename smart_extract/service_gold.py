"""Gold-set labelling service — the shared logic behind the admin labelling UI.

This is *research* plumbing, not a product feature (§11): it reads and writes the
same ``data/gold/*.json`` files that ``scripts/label_gold`` and ``scripts/evaluate``
use, so the evaluation contract is unchanged. It merely lets a human confirm/fix
labels through the dashboard instead of the terminal. The human still decides
every value; nothing here auto-labels (that would grade the model against itself
and fabricate the result §13 forbids).

Functions are thin and I/O-focused so the API layer stays trivial and the same
logic is unit-testable offline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from smart_extract.config import settings
from smart_extract.evaluation.metrics import EVAL_FIELDS
from smart_extract.intake.base import IntakeError
from smart_extract.intake.pdf import read_pdf

# Fields a gold file carries beyond the scalar title/arxiv_id. Kept in sync with
# metrics.EVAL_FIELDS so the UI edits exactly what evaluate.py scores.
LIST_FIELDS = list(EVAL_FIELDS)
_MARKER = "_INSTRUCTIONS"


class GoldError(Exception):
    """Raised for a missing/invalid gold file or an out-of-scope path."""


def _gold_path(arxiv_id: str) -> Path:
    """Resolve a gold file path, refusing anything that escapes the gold dir."""
    stem = arxiv_id[:-5] if arxiv_id.endswith(".json") else arxiv_id
    path = (settings.gold_dir / f"{stem}.json").resolve()
    gold_dir = settings.gold_dir.resolve()
    if gold_dir not in path.parents:
        raise GoldError(f"path outside gold directory: {arxiv_id}")
    return path


def _source_text(arxiv_id: str) -> str | None:
    """Digital-lane text of a paper for grounding, or None if unavailable."""
    hits = sorted(settings.raw_dir.glob(f"{arxiv_id}*.pdf"))
    if not hits:
        return None
    try:
        return read_pdf(hits[0]).text
    except IntakeError:
        return None


def _occurrences(value: str, text: str, limit: int = 3) -> list[str]:
    """Short snippets of lines in ``text`` containing ``value`` (case-insensitive)."""
    needle = value.strip().lower()
    if not needle:
        return []
    snippets: list[str] = []
    for line in text.splitlines():
        idx = line.lower().find(needle)
        if idx == -1:
            continue
        start = max(0, idx - 25)
        end = min(len(line), idx + len(value) + 25)
        snippet = line[start:end].strip()
        snippets.append(("…" if start else "") + snippet + ("…" if end < len(line) else ""))
        if len(snippets) >= limit:
            break
    return snippets


def list_gold() -> list[dict[str, Any]]:
    """Summarise every gold file: id, title, labelled?, and per-field counts.

    ``labelled`` is True once the template marker is gone. ``datasets`` is
    surfaced separately because an empty USES relation is the easiest thing to
    leave unverified (§6) and the reviewer should see it at a glance.
    """
    out: list[dict[str, Any]] = []
    for path in sorted(settings.gold_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        counts = {f: len(data.get(f, []) or []) for f in LIST_FIELDS}
        out.append(
            {
                "arxiv_id": data.get("arxiv_id", path.stem),
                "title": data.get("title", ""),
                "labelled": _MARKER not in data,
                "counts": counts,
                "datasets": counts.get("datasets", 0),
            }
        )
    return out


def load_gold(arxiv_id: str) -> dict[str, Any]:
    """Load one gold paper with grounding evidence for every value.

    Each list field becomes a list of ``{value, in_paper, snippets}`` so the UI
    can pre-mark values found (✓) or not found (⚠) in the real paper text — the
    exact hint the terminal tool shows, but rendered beside the source.
    """
    path = _gold_path(arxiv_id)
    if not path.exists():
        raise GoldError(f"no gold file for {arxiv_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    aid = data.get("arxiv_id", path.stem)
    text = _source_text(aid)

    fields: dict[str, list[dict[str, Any]]] = {}
    for field in LIST_FIELDS:
        values = list(data.get(field, []) or [])
        annotated = []
        for v in values:
            snippets = _occurrences(v, text) if text else []
            annotated.append(
                {
                    "value": v,
                    "in_paper": bool(snippets) if text else None,
                    "snippets": snippets,
                }
            )
        fields[field] = annotated

    return {
        "arxiv_id": aid,
        "title": data.get("title", ""),
        "labelled": _MARKER not in data,
        "has_text": text is not None,
        "text": text or "",
        "fields": fields,
    }


def save_gold(arxiv_id: str, title: str, fields: dict[str, list[str]]) -> dict[str, Any]:
    """Persist a hand-corrected paper, stripping the template marker.

    Removing ``_INSTRUCTIONS`` marks the file as genuinely human-labelled and
    ready for ``evaluate``. We preserve any keys the gold file already had (e.g.
    ``year``) that the UI does not edit, and de-duplicate list values so a
    double-add cannot inflate a set.
    """
    path = _gold_path(arxiv_id)
    if not path.exists():
        raise GoldError(f"no gold file for {arxiv_id}")
    data = json.loads(path.read_text(encoding="utf-8"))

    data["title"] = title
    for field in LIST_FIELDS:
        incoming = fields.get(field, [])
        if not isinstance(incoming, list):
            raise GoldError(f"field '{field}' must be a list of strings")
        seen: dict[str, str] = {}
        for raw in incoming:
            v = str(raw).strip()
            if v and v.lower() not in seen:
                seen[v.lower()] = v
        data[field] = list(seen.values())

    data.pop(_MARKER, None)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "arxiv_id": data.get("arxiv_id", path.stem),
        "labelled": True,
        "counts": {f: len(data.get(f, []) or []) for f in LIST_FIELDS},
    }