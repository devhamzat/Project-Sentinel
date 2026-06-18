"""Phase 2: produce 'photographed' copies of the frozen corpus.

Run from the repo root:
    python -m smart_extract.scripts.make_photos                 # all PDFs, page 1
    python -m smart_extract.scripts.make_photos --pages 2       # first 2 pages
    python -m smart_extract.scripts.make_photos --clean         # no degradation

For the digital-vs-photographed robustness evaluation (CLAUDE.md §11) we need
photo-like versions of the SAME papers. This renders each PDF page to an image
and applies a mild, deterministic 'phone photo' degradation (slight rotation,
blur, sensor noise, uneven brightness) so the OCR lane has realistic inputs and
the accuracy comparison is meaningful. Outputs go to data/photo/.

This is a controlled stand-in for literally re-photographing 60 papers by hand;
it is reproducible (fixed seed) and documented as such for Chapter 4.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import fitz  # PyMuPDF
import numpy as np

from smart_extract.config import settings

# Fixed seed so the generated photos are reproducible (a frozen eval input).
_RNG = np.random.default_rng(42)
_RENDER_DPI = 200  # high enough for legible OCR, low enough to stay fast


def _render_page(page: fitz.Page) -> np.ndarray:
    """Render one PDF page to a BGR image array at _RENDER_DPI."""
    pix = page.get_pixmap(dpi=_RENDER_DPI)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
    if pix.n == 4:  # RGBA -> RGB
        img = cv2.cvtColor(img, cv2.COLOR_RGBA2RGB)
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)


def _degrade(image: np.ndarray) -> np.ndarray:
    """Apply a mild, realistic 'phone photo' degradation to a clean render."""
    h, w = image.shape[:2]

    # 1) Slight rotation (skew), +/- ~2 degrees.
    angle = float(_RNG.uniform(-2.0, 2.0))
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    image = cv2.warpAffine(
        image, matrix, (w, h), borderMode=cv2.BORDER_REPLICATE
    )

    # 2) Mild Gaussian blur (focus softness).
    image = cv2.GaussianBlur(image, (3, 3), 0)

    # 3) Uneven brightness: multiply by a smooth gradient (lighting falloff).
    gradient = np.linspace(0.75, 1.05, w, dtype=np.float32)
    image = np.clip(image.astype(np.float32) * gradient[None, :, None], 0, 255)

    # 4) Sensor noise.
    noise = _RNG.normal(0, 8, image.shape).astype(np.float32)
    image = np.clip(image + noise, 0, 255).astype(np.uint8)
    return image


def make_photos(pages: int = 1, clean: bool = False) -> int:
    """Render (and optionally degrade) corpus PDFs into data/photo/. Return count."""
    raw_dir = settings.raw_dir
    out_dir = settings.photo_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(raw_dir.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs in {raw_dir}. Run download_arxiv first.")
        return 0

    written = 0
    for pdf_path in pdfs:
        try:
            with fitz.open(pdf_path) as doc:
                n = min(pages, doc.page_count)
                for i in range(n):
                    img = _render_page(doc[i])
                    if not clean:
                        img = _degrade(img)
                    out_path = out_dir / f"{pdf_path.stem}_p{i + 1}.png"
                    cv2.imwrite(str(out_path), img)
                    written += 1
            print(f"  {pdf_path.name} -> {n} page image(s)")
        except Exception as exc:  # noqa: BLE001
            print(f"  WARN - failed on {pdf_path.name}: {exc}")

    kind = "clean" if clean else "degraded"
    print(f"Done. Wrote {written} {kind} page image(s) to {out_dir}.")
    return written


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Make photographed copies of the corpus for OCR evaluation."
    )
    parser.add_argument("--pages", type=int, default=1, help="pages per PDF (default 1)")
    parser.add_argument(
        "--clean", action="store_true", help="render without photo degradation"
    )
    args = parser.parse_args()
    return 0 if make_photos(args.pages, args.clean) > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
