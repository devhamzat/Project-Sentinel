"""Phase 0: prove the LLM extraction works end-to-end on ONE paper.

Run from the repo root:
    python -m smart_extract.scripts.spike data/raw/2401.01234.pdf
    python -m smart_extract.scripts.spike            # uses first PDF in data/raw/

This is a throwaway-ish proof of concept: read a PDF's text layer, send it
through the shared extraction prompt and the LLM seam, and print the parsed
JSON. It deliberately reuses extraction.prompts so the spike and the real
Phase-3 pipeline share the same prompt (CLAUDE.md §9). The proper intake module
arrives in Phase 1 (intake/pdf.py); here we extract text inline.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import fitz  # PyMuPDF

from smart_extract.config import settings
from smart_extract.extraction.llm import LLMError, extract_json
from smart_extract.extraction.prompts import EXTRACTION_SYSTEM, extraction_prompt


def _read_pdf_text(path: Path) -> str:
    """Extract the text layer from a born-digital PDF (no OCR — §13)."""
    with fitz.open(path) as doc:
        return "\n".join(page.get_text() for page in doc)


def _pick_default_pdf() -> Path | None:
    pdfs = sorted(settings.raw_dir.glob("*.pdf"))
    return pdfs[0] if pdfs else None


def run(pdf_path: Path) -> int:
    if not pdf_path.exists():
        print(f"FAILED - no such file: {pdf_path}")
        return 1

    print(f"Reading text from {pdf_path.name} ...")
    text = _read_pdf_text(pdf_path)
    if not text.strip():
        print("FAILED - no text layer found (is this a scanned image? OCR is Phase 2).")
        return 1
    print(f"  extracted {len(text)} chars; sending to LLM ({settings.llm_model}) ...")

    try:
        result = extract_json(
            extraction_prompt(text),
            system=EXTRACTION_SYSTEM,
        )
    except LLMError as exc:
        print(f"FAILED - {exc}")
        return 1

    print("\n--- extracted JSON ---")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    if len(sys.argv) > 1:
        pdf_path = Path(sys.argv[1])
    else:
        pdf_path = _pick_default_pdf()
        if pdf_path is None:
            print(
                "No PDF given and none found in data/raw/.\n"
                "Run the downloader first: python -m smart_extract.scripts.download_arxiv"
            )
            return 1
        print(f"No path given; using {pdf_path}")
    return run(pdf_path)


if __name__ == "__main__":
    sys.exit(main())
