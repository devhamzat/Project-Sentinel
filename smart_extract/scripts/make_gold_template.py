"""Phase 4: pre-fill gold-label templates for hand-correction (§11).

Run from the repo root:
    python -m smart_extract.scripts.make_gold_template --limit 20

For each corpus PDF, this runs the digital-lane extraction and writes a JSON
file to data/gold/<arxiv_id>.json containing the model's guess. YOU then open
each file and CORRECT it to the true labels (fix authors, datasets, etc.).

This is a labour-saver, NOT a label generator: the saved file is the model's
proposal so you are correcting rather than typing from scratch. The committed
gold set must reflect YOUR corrections — never trust the pre-fill as truth, or
the evaluation measures the model against itself (§13: do not fabricate results).
"""

from __future__ import annotations

import argparse
import json
import sys

from smart_extract.config import settings
from smart_extract.evaluation.metrics import EVAL_FIELDS
from smart_extract.extraction.extract import extract
from smart_extract.intake.pdf import read_pdf


def make_templates(limit: int, overwrite: bool) -> int:
    gold_dir = settings.gold_dir
    gold_dir.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(settings.raw_dir.glob("*.pdf"))[:limit]
    if not pdfs:
        print(f"No PDFs in {settings.raw_dir}. Run download_arxiv first.")
        return 0

    written = 0
    for pdf in pdfs:
        intake = read_pdf(pdf)
        arxiv_id = intake.arxiv_id or pdf.stem
        out_path = gold_dir / f"{arxiv_id}.json"
        if out_path.exists() and not overwrite:
            print(f"  skip (exists): {out_path.name}")
            continue
        try:
            paper = extract(intake.text)
        except Exception as exc:  # noqa: BLE001
            print(f"  WARN - extraction failed for {arxiv_id}: {exc}")
            continue

        template = {
            "arxiv_id": arxiv_id,
            "title": paper["title"],
            "_INSTRUCTIONS": "Correct every field below to the TRUE labels, then "
                             "delete this key. Lists are sets; order does not matter.",
            **{field: paper.get(field, []) for field in EVAL_FIELDS},
        }
        out_path.write_text(json.dumps(template, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        print(f"  wrote {out_path.name} (CORRECT IT BY HAND)")
        written += 1

    print(f"Done. {written} template(s) in {gold_dir}. Hand-correct them before evaluating.")
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-fill gold-label templates.")
    parser.add_argument("--limit", type=int, default=20, help="max papers (default 20)")
    parser.add_argument("--overwrite", action="store_true",
                        help="overwrite existing gold files (loses corrections!)")
    args = parser.parse_args()
    return 0 if make_templates(args.limit, args.overwrite) > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
