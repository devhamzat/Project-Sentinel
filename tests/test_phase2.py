"""Tests for the Phase-2 image/OCR lane.

The preprocessing, dispatcher, and shared-type tests are pure (no engine). One
test exercises real OCR and is skipped automatically if Tesseract isn't
installed, so the offline suite stays green on machines without the engine.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest


# --- shared types & dispatcher (no engine needed) --------------------------

def test_intake_result_has_source_kind():
    from smart_extract.intake.base import IntakeResult

    r = IntakeResult(text="x", source_path=Path("a.pdf"), arxiv_id=None,
                     source_kind="digital")
    assert r.source_kind == "digital"


def test_read_any_rejects_unknown_suffix():
    from smart_extract.intake import IntakeError, read_any

    with pytest.raises(IntakeError):
        read_any("notes.docx")


def test_read_any_image_missing_file_raises():
    from smart_extract.intake import read_any
    from smart_extract.intake.image import ImageIntakeError

    with pytest.raises(ImageIntakeError):
        read_any("nope.png")


def test_image_suffixes_cover_common_formats():
    from smart_extract.intake.image import IMAGE_SUFFIXES

    assert {".png", ".jpg", ".jpeg"} <= IMAGE_SUFFIXES


# --- preprocessing (pure OpenCV, no engine) --------------------------------

def test_preprocess_returns_single_channel_binary():
    from smart_extract.intake.image import preprocess

    img = np.full((80, 200, 3), 255, np.uint8)
    out = preprocess(img)
    assert out.ndim == 2  # grayscale/binary
    # Adaptive threshold yields a (near-)binary image.
    assert set(np.unique(out)).issubset({0, 255})


def test_preprocess_handles_blank_without_error():
    from smart_extract.intake.image import preprocess

    out = preprocess(np.zeros((50, 50, 3), np.uint8))
    assert out.shape == (50, 50)


# --- config resolution ------------------------------------------------------

def test_tesseract_resolution_prefers_explicit_setting(monkeypatch):
    from smart_extract import config

    monkeypatch.setattr(config.settings, "tesseract_cmd", "/custom/tess", raising=False)
    assert config.settings.resolved_tesseract_cmd == "/custom/tess"


# --- real OCR round-trip (skipped if engine absent) ------------------------

def _engine_available() -> bool:
    import pytesseract
    from smart_extract.config import settings

    cmd = settings.resolved_tesseract_cmd
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _engine_available(), reason="Tesseract engine not installed")
def test_ocr_reads_rendered_text():
    import cv2

    from smart_extract.intake.image import ocr_image

    img = np.full((120, 640, 3), 255, np.uint8)
    cv2.putText(img, "Knowledge Graph", (15, 75),
                cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3)
    text = ocr_image(img).strip()
    assert "Knowledge" in text and "Graph" in text
