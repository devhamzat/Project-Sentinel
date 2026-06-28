"""Phase 4: interactive helper for hand-correcting the gold set (§11, §13).

Run from the repo root:
    python -m smart_extract.scripts.label_gold              # all uncorrected files
    python -m smart_extract.scripts.label_gold 2606.18246   # one specific paper
    python -m smart_extract.scripts.label_gold --progress   # status only, no editing

This walks each gold file that is still an uncorrected template (it carries the
``_INSTRUCTIONS`` marker) field by field. For each pre-filled value it shows the
lines of the *real* paper where that value does or does not occur, so you can
confirm or fix it against the source without leaving the terminal. You decide
every value — this is a labelling AID, never an auto-labeller. Auto-labelling
would grade the model against itself and fabricate the result §13 forbids.

When you finish a file, the helper strips the ``_INSTRUCTIONS`` key, marking it
genuinely hand-labelled and ready for ``evaluate``. Already-corrected files
(no marker) are left untouched unless you name one explicitly.

Controls per field: type the value numbers to DROP (e.g. ``2 4``), ``a`` to add
new values, Enter to keep all, ``s`` to skip the field unchanged. At end of a
paper: ``w`` write, ``q`` write-and-quit, ``x`` discard this paper's edits.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from smart_extract.config import settings
from smart_extract.evaluation.metrics import EVAL_FIELDS
from smart_extract.intake.base import IntakeError
from smart_extract.intake.pdf import read_pdf

# Editable fields, plus title/year which also live in a gold file.
_LIST_FIELDS = EVAL_FIELDS
_CONTEXT_CHARS = 90  # how much of a matching line to show around a hit


def _source_text(arxiv_id: str) -> str | None:
    """Read the digital-lane text of a paper, or None if no PDF / unreadable."""
    hits = sorted(settings.raw_dir.glob(f"{arxiv_id}*.pdf"))
    if not hits:
        return None
    try:
        return read_pdf(hits[0]).text
    except IntakeError:
        return None


def _find_occurrences(value: str, text: str) -> list[str]:
    """Return short snippets of every line in ``text`` containing ``value``.

    Case-insensitive substring search. Returned snippets are trimmed around the
    first hit on each line so a long line does not flood the terminal.
    """
    needle = value.strip().lower()
    if not needle:
        return []
    snippets: list[str] = []
    for line in text.splitlines():
        low = line.lower()
        idx = low.find(needle)
        if idx == -1:
            continue
        start = max(0, idx - 25)
        end = min(len(line), idx + len(value) + 25)
        snippet = line[start:end].strip()
        snippets.append(("…" if start else "") + snippet + ("…" if end < len(line) else ""))
        if len(snippets) >= 3:  # a couple of examples is enough to verify
            break
    return snippets


def _show_field(field: str, values: list[str], text: str | None) -> None:
    """Print the field's current values with grounding evidence from the paper."""
    print(f"\n  --- {field} ({len(values)}) ---")
    if not values:
        print("    (empty)")
    for i, value in enumerate(values, 1):
        if text is None:
            print(f"    {i}. {value}")
            continue
        hits = _find_occurrences(value, text)
        if hits:
            print(f"    {i}. {value}   [in paper]")
            for h in hits:
                print(f"          · {h}")
        else:
            print(f"    {i}. {value}   [NOT FOUND in paper text — likely wrong]")


def _prompt(msg: str) -> str:
    try:
        return input(msg).strip()
    except EOFError:
        return "q"


def _edit_list_field(field: str, values: list[str], text: str | None) -> list[str]:
    """Interactively keep/drop/add values for one list field. Returns new list."""
    while True:
        _show_field(field, values, text)
        choice = _prompt(
            "    drop #s (e.g. '1 3'), 'a' add, Enter keep, 's' skip: "
        ).lower()
        if choice in ("", "s"):
            return values
        if choice == "a":
            added = _prompt("    new value(s), comma-separated: ")
            for v in (x.strip() for x in added.split(",")):
                if v and v.lower() not in {x.lower() for x in values}:
                    values.append(v)
            continue
        # otherwise interpret as indices to drop
        try:
            drop = {int(tok) for tok in choice.split()}
        except ValueError:
            print("    ? expected numbers, 'a', 's', or Enter.")
            continue
        kept = [v for i, v in enumerate(values, 1) if i not in drop]
        dropped = [v for i, v in enumerate(values, 1) if i in drop]
        if dropped:
            print(f"    dropped: {', '.join(dropped)}")
        values = kept


def _edit_scalar(name: str, current: Any) -> Any:
    """Let the user keep or replace a scalar field (title, year)."""
    shown = current if current not in (None, "") else "(empty)"
    new = _prompt(f"\n  {name} = {shown}\n    Enter to keep, or type new value: ")
    if new == "":
        return current
    if name == "year":
        return int(new) if new.isdigit() else current
    return new


def label_file(path: Path) -> bool:
    """Walk one gold file with the user. Returns True if it was saved corrected."""
    data = json.loads(path.read_text(encoding="utf-8"))
    arxiv_id = data.get("arxiv_id", path.stem)
    text = _source_text(arxiv_id)

    print("\n" + "=" * 70)
    print(f"Labelling {path.name}  (arxiv {arxiv_id})")
    if text is None:
        print("  ! No readable PDF found — grounding hints unavailable for this paper.")
    else:
        print(f"  paper text loaded ({len(text):,} chars). [in paper] tags below are real.")

    data["title"] = _edit_scalar("title", data.get("title", ""))
    if "year" in data:
        data["year"] = _edit_scalar("year", data.get("year"))

    for field in _LIST_FIELDS:
        values = list(data.get(field, []) or [])
        data[field] = _edit_list_field(field, values, text)

    while True:
        action = _prompt(
            "\n  End of paper. [w]rite & next, [q]uit (write), [x] discard: "
        ).lower()
        if action in ("w", "q"):
            data.pop("_INSTRUCTIONS", None)  # mark as genuinely hand-labelled
            path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print(f"  saved {path.name} (marker removed).")
            if action == "q":
                raise KeyboardInterrupt
            return True
        if action == "x":
            print(f"  discarded edits to {path.name}.")
            return False
        print("    ? expected 'w', 'q', or 'x'.")


def _targets(papers: list[str]) -> list[Path]:
    """Resolve which gold files to label from CLI args (or all uncorrected)."""
    gold_dir = settings.gold_dir
    if papers:
        out: list[Path] = []
        for arg in papers:
            stem = arg[:-5] if arg.endswith(".json") else arg
            p = gold_dir / f"{stem}.json"
            if p.exists():
                out.append(p)
            else:
                print(f"  ! no gold file for '{arg}' ({p.name})")
        return out
    # default: every file that still carries the template marker
    todo: list[Path] = []
    for p in sorted(gold_dir.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        if "_INSTRUCTIONS" in data:
            todo.append(p)
    return todo


def show_progress() -> int:
    """Print a labelling status table and return the count still uncorrected.

    A file is 'labelled' once the _INSTRUCTIONS marker is gone. We also flag
    empty 'datasets' (the central USES relation) since an empty list there is
    easy to leave unverified — it may be correct, or a missed extraction.
    """
    gold_dir = settings.gold_dir
    files = sorted(gold_dir.glob("*.json"))
    if not files:
        print(f"No gold files in {gold_dir}.")
        return 0

    labelled = uncorrected = 0
    print(f"\nGold labelling status ({gold_dir}):\n")
    print(f"  {'file':22} {'status':12} datasets")
    for p in files:
        data = json.loads(p.read_text(encoding="utf-8"))
        is_template = "_INSTRUCTIONS" in data
        n_datasets = len(data.get("datasets", []) or [])
        if is_template:
            uncorrected += 1
            status = "TEMPLATE"
        else:
            labelled += 1
            status = "labelled"
        flag = "  <- empty USES" if n_datasets == 0 else ""
        print(f"  {p.name:22} {status:12} {n_datasets}{flag}")

    total = labelled + uncorrected
    bar_len = 24
    filled = round(bar_len * labelled / total) if total else 0
    bar = "#" * filled + "-" * (bar_len - filled)
    print(f"\n  [{bar}] {labelled}/{total} labelled, {uncorrected} to go.")
    if uncorrected:
        print("  Label them:  python -m smart_extract.scripts.label_gold")
    return uncorrected


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hand-correct the gold set (or report labelling progress)."
    )
    parser.add_argument(
        "papers", nargs="*",
        help="specific arxiv id(s) to label; default is all uncorrected files",
    )
    parser.add_argument(
        "--progress", action="store_true",
        help="show labelled-vs-template status and exit (no editing)",
    )
    args = parser.parse_args()

    if args.progress:
        show_progress()
        return 0

    targets = _targets(args.papers)
    if not targets:
        print("Nothing to label: no uncorrected gold templates found in "
              f"{settings.gold_dir}. (Files without the _INSTRUCTIONS marker are "
              "already hand-labelled.)")
        return 0

    print(f"{len(targets)} file(s) to label. Verify every value against the paper.")
    done = 0
    try:
        for path in targets:
            if label_file(path):
                done += 1
    except KeyboardInterrupt:
        print("\nStopped (current file saved).")
    print(f"\nCorrected {done} file(s) this session.")
    show_progress()
    return 0


if __name__ == "__main__":
    sys.exit(main())