"""Phase 0: download and FREEZE a corpus of cs.CL papers from arXiv.

Run from the repo root:
    python -m smart_extract.scripts.download_arxiv            # default ~60 papers
    python -m smart_extract.scripts.download_arxiv --count 20

Downloads PDFs into ``data/raw/`` and writes ``data/raw/manifest.json`` listing
the arXiv ids + metadata. Re-running is idempotent: papers already on disk are
skipped, so the frozen set stays reproducible (CLAUDE.md §4).

Uses only the public arXiv API (Atom feed) + the declared ``requests`` dep.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlencode

import requests

from smart_extract.config import settings

ARXIV_API = "http://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
# arXiv asks for a descriptive User-Agent and a delay between calls.
HEADERS = {"User-Agent": "smart-extract/0.1 (final-year project; akinolaseun004@gmail.com)"}
POLITE_DELAY_S = 3.0


def _query_listing(count: int) -> list[dict[str, str]]:
    """Query the arXiv API for the newest ``count`` cs.CL papers."""
    params = {
        "search_query": "cat:cs.CL",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "start": 0,
        "max_results": count,
    }
    url = f"{ARXIV_API}?{urlencode(params)}"
    resp = requests.get(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    papers: list[dict[str, str]] = []
    for entry in root.findall(f"{ATOM}entry"):
        raw_id = entry.findtext(f"{ATOM}id", "")  # e.g. http://arxiv.org/abs/2401.01234v1
        arxiv_id = raw_id.rsplit("/", 1)[-1]
        title = " ".join((entry.findtext(f"{ATOM}title") or "").split())
        published = entry.findtext(f"{ATOM}published", "")
        authors = [
            (a.findtext(f"{ATOM}name") or "").strip()
            for a in entry.findall(f"{ATOM}author")
        ]
        pdf_url = ""
        for link in entry.findall(f"{ATOM}link"):
            if link.get("title") == "pdf":
                pdf_url = link.get("href", "")
                break
        if not pdf_url and arxiv_id:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
        papers.append(
            {
                "arxiv_id": arxiv_id,
                "title": title,
                "published": published,
                "authors": authors,
                "pdf_url": pdf_url,
            }
        )
    return papers


def _download_pdf(pdf_url: str, dest: Path) -> None:
    resp = requests.get(pdf_url, headers=HEADERS, timeout=120)
    resp.raise_for_status()
    dest.write_bytes(resp.content)


def download(count: int = 60) -> int:
    """Download up to ``count`` cs.CL papers into data/raw/. Return # on disk."""
    raw_dir = settings.raw_dir
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = raw_dir / "manifest.json"

    print(f"Querying arXiv for the newest {count} cs.CL papers ...")
    try:
        listing = _query_listing(count)
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED - could not query arXiv: {exc}")
        return 0

    if not listing:
        print("FAILED - arXiv returned no entries.")
        return 0

    manifest: list[dict[str, str]] = []
    for i, paper in enumerate(listing, start=1):
        arxiv_id = paper["arxiv_id"]
        safe_id = arxiv_id.replace("/", "_")
        dest = raw_dir / f"{safe_id}.pdf"
        record = {**paper, "filename": dest.name}
        manifest.append(record)

        if dest.exists():
            print(f"[{i}/{len(listing)}] skip (exists): {dest.name}")
            continue

        print(f"[{i}/{len(listing)}] downloading {arxiv_id} -> {dest.name}")
        try:
            _download_pdf(paper["pdf_url"], dest)
        except Exception as exc:  # noqa: BLE001
            print(f"    WARN - failed to download {arxiv_id}: {exc}")
        time.sleep(POLITE_DELAY_S)  # be kind to arXiv

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    on_disk = len(list(raw_dir.glob("*.pdf")))
    print(f"Done. {on_disk} PDF(s) in {raw_dir}. Manifest: {manifest_path.name}")
    return on_disk


def main() -> int:
    parser = argparse.ArgumentParser(description="Download a frozen cs.CL corpus from arXiv.")
    parser.add_argument("--count", type=int, default=60, help="number of papers (default 60)")
    args = parser.parse_args()
    n = download(args.count)
    return 0 if n > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
