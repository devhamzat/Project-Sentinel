"""Image/photo intake: OpenCV preprocessing + Tesseract OCR (CLAUDE.md §5).

This is the *image* lane — the counterpart to the digital PDF lane. It takes a
photographed or scanned page, cleans it up with OpenCV (grayscale, denoise,
threshold, deskew), runs Tesseract via pytesseract, and returns the same
``IntakeResult`` the PDF lane does (with ``source_kind="photo"``).

Why preprocess: OCR accuracy on phone photos degrades with skew, noise, and
uneven lighting. The steps here are standard, lightweight, and CPU-friendly
(§14) — no trained layout model (§13).
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytesseract

from smart_extract.config import settings
from smart_extract.intake.base import (
    IntakeError,
    IntakeResult,
    arxiv_id_from_name,
)

# Image extensions this lane accepts.
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


class ImageIntakeError(IntakeError):
    """Raised when an image cannot be read or OCR yields no usable text."""


def _configure_tesseract() -> None:
    """Point pytesseract at the configured/auto-detected Tesseract binary."""
    cmd = settings.resolved_tesseract_cmd
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd


def preprocess(image: np.ndarray) -> np.ndarray:
    """Clean a page image to improve OCR accuracy.

    Grayscale -> denoise -> adaptive threshold -> deskew. Returns a binarised,
    deskewed single-channel image ready for Tesseract.
    """
    # 1) Grayscale.
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image

    # 2) Denoise (median blur removes speckle without smearing edges much).
    gray = cv2.medianBlur(gray, 3)

    # 3) Adaptive threshold -> crisp black text on white, robust to uneven light.
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
    )

    # 4) Deskew using the minimum-area rectangle of the dark (text) pixels.
    return _deskew(binary)


def _deskew(binary: np.ndarray) -> np.ndarray:
    """Rotate the image so text lines are horizontal.

    Estimates the skew angle from the foreground pixels; small angles only, so
    a clean scan is essentially untouched.
    """
    # Foreground (text) is dark; invert so text pixels are non-zero.
    coords = np.column_stack(np.where(binary < 128))
    if coords.size == 0:
        return binary  # blank image; nothing to deskew

    angle = cv2.minAreaRect(coords)[-1]
    # minAreaRect angle is in [-90, 0); normalise to a small correction.
    if angle < -45:
        angle = 90 + angle
    if abs(angle) < 0.5:
        return binary  # already straight enough; avoid needless interpolation

    (h, w) = binary.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(
        binary, matrix, (w, h),
        flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE,
    )


def ocr_image(image: np.ndarray, *, lang: str = "eng") -> str:
    """Run Tesseract on an already-loaded image array and return raw text."""
    _configure_tesseract()
    try:
        return pytesseract.image_to_string(image, lang=lang)
    except pytesseract.TesseractError as exc:
        raise ImageIntakeError(f"Tesseract OCR failed: {exc}") from exc
    except pytesseract.TesseractNotFoundError as exc:
        raise ImageIntakeError(
            "Tesseract engine not found. Install it and/or set TESSERACT_CMD in .env."
        ) from exc


def read_image(path: str | Path, *, lang: str = "eng") -> IntakeResult:
    """OCR a photographed/scanned page into the shared clean-text representation.

    Raises ImageIntakeError if the file is missing/unreadable or OCR yields no
    text at all.
    """
    path = Path(path)
    if not path.exists():
        raise ImageIntakeError(f"No such file: {path}")

    image = cv2.imread(str(path))
    if image is None:
        raise ImageIntakeError(
            f"Could not read image {path.name} (unsupported or corrupt format)."
        )

    cleaned = preprocess(image)
    text = ocr_image(cleaned, lang=lang).strip()
    if not text:
        raise ImageIntakeError(
            f"OCR produced no text for {path.name}. The image may be blank or too "
            "low quality to read."
        )

    return IntakeResult(
        text=text,
        source_path=path,
        arxiv_id=arxiv_id_from_name(path),
        source_kind="photo",
    )
