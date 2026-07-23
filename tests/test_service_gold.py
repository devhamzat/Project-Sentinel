"""Offline tests for the gold-labelling service (smart_extract.service_gold).

These exercise list/load/save without touching the real data dir: we point
settings.data_dir at a tmp dir holding a fabricated gold file. No network, no
Neo4j, no PDF needed (grounding just reports has_text=False when no PDF).
"""

from __future__ import annotations

import json

import pytest

from smart_extract import service_gold as g
from smart_extract.config import settings


@pytest.fixture
def gold_tmp(tmp_path, monkeypatch):
    """Redirect settings.data_dir to a tmp tree with one template gold file."""
    (tmp_path / "gold").mkdir()
    (tmp_path / "raw").mkdir()
    template = {
        "arxiv_id": "1234.5678",
        "title": "A Template Paper",
        "_INSTRUCTIONS": "correct me",
        "authors": ["Ada Lovelace", "Ada Lovelace"],  # dup on purpose
        "affiliations": ["Analytical Engine Co."],
        "keywords": ["compiling"],
        "datasets": [],
        "methods": [],
        "metrics": [],
    }
    (tmp_path / "gold" / "1234.5678.json").write_text(
        json.dumps(template), encoding="utf-8"
    )
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    return tmp_path


def test_list_reports_template_as_unlabelled(gold_tmp):
    rows = g.list_gold()
    assert len(rows) == 1
    row = rows[0]
    assert row["arxiv_id"] == "1234.5678"
    assert row["labelled"] is False
    assert row["datasets"] == 0
    assert row["counts"]["authors"] == 2


def test_load_annotates_values_without_pdf(gold_tmp):
    detail = g.load_gold("1234.5678")
    assert detail["has_text"] is False
    assert detail["labelled"] is False
    authors = detail["fields"]["authors"]
    assert [a["value"] for a in authors] == ["Ada Lovelace", "Ada Lovelace"]
    # No PDF -> grounding is unknown (None), not a false claim of "not found".
    assert all(a["in_paper"] is None for a in authors)


def test_save_strips_marker_and_dedups(gold_tmp):
    res = g.save_gold(
        "1234.5678",
        "Corrected Title",
        {
            "authors": ["Ada Lovelace", "ada lovelace", "Charles Babbage"],
            "affiliations": ["Analytical Engine Co."],
            "keywords": ["compiling"],
            "datasets": ["  MNIST  "],
            "methods": [],
            "metrics": [],
        },
    )
    assert res["labelled"] is True
    assert res["counts"]["authors"] == 2  # case-insensitive dedup
    assert res["counts"]["datasets"] == 1

    on_disk = json.loads(
        (gold_tmp / "gold" / "1234.5678.json").read_text(encoding="utf-8")
    )
    assert "_INSTRUCTIONS" not in on_disk
    assert on_disk["title"] == "Corrected Title"
    assert on_disk["datasets"] == ["MNIST"]  # trimmed


def test_load_after_save_reports_labelled(gold_tmp):
    g.save_gold(
        "1234.5678",
        "T",
        {f: [] for f in g.LIST_FIELDS},
    )
    assert g.load_gold("1234.5678")["labelled"] is True
    assert g.list_gold()[0]["labelled"] is True


def test_missing_paper_raises(gold_tmp):
    with pytest.raises(g.GoldError):
        g.load_gold("0000.0000")


def test_path_traversal_rejected(gold_tmp):
    with pytest.raises(g.GoldError):
        g.load_gold("../../etc/passwd")


def test_save_rejects_non_list_field(gold_tmp):
    with pytest.raises(g.GoldError):
        g.save_gold("1234.5678", "T", {"authors": "not a list"})


# --- API endpoint layer (admin-guarded research routes) ---

def test_gold_endpoints_require_admin():
    """A tester hitting the admin guard must be refused (403)."""
    from fastapi import HTTPException
    from smart_extract.auth import User
    from smart_extract.api.main import require_admin

    with pytest.raises(HTTPException) as exc_info:
        require_admin(User(id="w", email="t@example.com", role="tester"))
    assert exc_info.value.status_code == 403


def test_gold_get_endpoint_delegates(gold_tmp):
    from smart_extract.auth import User
    from smart_extract.api import main as api

    admin = User(id="w", email="a@example.com", role="admin")
    detail = api.gold_get("1234.5678", admin)
    assert detail["arxiv_id"] == "1234.5678"
    assert detail["labelled"] is False


def test_gold_save_endpoint_marks_labelled(gold_tmp):
    from smart_extract.auth import User
    from smart_extract.api import main as api

    admin = User(id="w", email="a@example.com", role="admin")
    req = api.GoldSaveRequest(
        title="Done", fields={f: [] for f in g.LIST_FIELDS}
    )
    res = api.gold_save("1234.5678", req, admin)
    assert res["labelled"] is True


def test_gold_get_missing_returns_404(gold_tmp):
    from fastapi import HTTPException
    from smart_extract.auth import User
    from smart_extract.api import main as api

    admin = User(id="w", email="a@example.com", role="admin")
    with pytest.raises(HTTPException) as exc_info:
        api.gold_get("9999.9999", admin)
    assert exc_info.value.status_code == 404