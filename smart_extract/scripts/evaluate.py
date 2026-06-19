"""Phase 4: evaluate extraction accuracy against the gold set (§11).

Run from the repo root:
    python -m smart_extract.scripts.evaluate                 # digital lane
    python -m smart_extract.scripts.evaluate --lane photo    # photo/OCR lane
    python -m smart_extract.scripts.evaluate --compare       # both + comparison

For each hand-labelled paper in data/gold/, this re-runs extraction on the
matching source (PDF for digital, data/photo/<id>_p1.png for photo), scores
predictions vs gold with precision/recall/F1 per field, and prints a table.
``--compare`` runs both lanes so you can quantify how much OCR degrades accuracy
(a core Chapter-4 result). Numbers are saved to data/eval_results.json.

These are REAL numbers computed from YOUR gold labels — never fabricated (§13).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from smart_extract.config import settings
from smart_extract.evaluation.metrics import (
    EVAL_FIELDS,
    PRF,
    aggregate,
    score_paper,
)
from smart_extract.extraction.extract import extract
from smart_extract.intake.image import read_image
from smart_extract.intake.pdf import read_pdf


def _load_gold() -> list[dict[str, Any]]:
    """Load hand-corrected gold files (skip uncorrected templates)."""
    gold_dir = settings.gold_dir
    gold: list[dict[str, Any]] = []
    for path in sorted(gold_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if "_INSTRUCTIONS" in data:
            print(f"  skip (still a template, not corrected): {path.name}")
            continue
        gold.append(data)
    return gold


def _source_for(arxiv_id: str, lane: str) -> Path | None:
    """Locate the source file for a paper in the requested lane."""
    if lane == "digital":
        hits = list(settings.raw_dir.glob(f"{arxiv_id}*.pdf"))
        return hits[0] if hits else None
    hits = list(settings.photo_dir.glob(f"{arxiv_id}*_p1.png"))
    return hits[0] if hits else None


def _predict(source: Path, lane: str) -> dict[str, list[str]]:
    intake = read_pdf(source) if lane == "digital" else read_image(source)
    return extract(intake.text)


def evaluate_lane(lane: str, gold: list[dict[str, Any]]) -> dict[str, PRF]:
    """Score every gold paper for one lane; return aggregated per-field PRF."""
    per_paper: list[dict[str, PRF]] = []
    for g in gold:
        arxiv_id = g["arxiv_id"]
        source = _source_for(arxiv_id, lane)
        if source is None:
            print(f"  [{lane}] no source for {arxiv_id}; skipping")
            continue
        try:
            predicted = _predict(source, lane)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{lane}] extraction failed for {arxiv_id}: {exc}")
            continue
        per_paper.append(score_paper(predicted, g))
        print(f"  [{lane}] scored {arxiv_id}")
    return aggregate(per_paper)


def _print_table(title: str, scores: dict[str, PRF]) -> None:
    print(f"\n=== {title} ===")
    print(f"{'field':14} {'P':>7} {'R':>7} {'F1':>7}  (tp/fp/fn)")
    for field in [*EVAL_FIELDS, "overall"]:
        prf = scores[field]
        print(f"{field:14} {prf.precision:7.3f} {prf.recall:7.3f} {prf.f1:7.3f}  "
              f"({prf.tp}/{prf.fp}/{prf.fn})")


def _to_jsonable(scores: dict[str, PRF]) -> dict[str, Any]:
    return {field: prf.as_dict() for field, prf in scores.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate extraction vs the gold set.")
    parser.add_argument("--lane", choices=["digital", "photo"], default="digital")
    parser.add_argument("--compare", action="store_true",
                        help="evaluate both lanes and compare (OCR robustness)")
    args = parser.parse_args()

    gold = _load_gold()
    if not gold:
        print("No corrected gold files in data/gold/. Run make_gold_template, "
              "hand-correct the JSON files, then re-run.")
        return 1
    print(f"Loaded {len(gold)} hand-labelled paper(s).")

    results: dict[str, Any] = {}
    lanes = ["digital", "photo"] if args.compare else [args.lane]
    for lane in lanes:
        scores = evaluate_lane(lane, gold)
        _print_table(f"{lane} lane", scores)
        results[lane] = _to_jsonable(scores)

    if args.compare and "digital" in results and "photo" in results:
        d = results["digital"]["overall"]["f1"]
        p = results["photo"]["overall"]["f1"]
        print(f"\n=== OCR robustness ===")
        print(f"overall F1  digital={d:.3f}  photo={p:.3f}  "
              f"drop={d - p:+.3f}")

    out = settings.data_path / "eval_results.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nSaved numbers to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
