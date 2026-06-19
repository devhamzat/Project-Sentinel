# CLAUDE.md — Project Context

This file is the single source of truth for Claude Code working on this project.
Read it fully before making changes. It encodes decisions that are already
settled; do not relitigate them without the developer explicitly asking.

---

## 1. What this project is

A **hybrid NLP + Large Language Model system that extracts structured entities
and relationships from academic research papers and stores them in a queryable
Neo4j knowledge graph.** Papers come in as either born-digital PDFs or
photographed/scanned images; the system extracts bibliographic and content
entities, the dataset-usage relationship, and a summary, builds a graph, and
lets the user ask questions in plain English (translated to Cypher by an LLM).

This is a **final-year undergraduate project** (B.Sc. Computer Science, Crescent
University Abeokuta). The registered topic is *"Smart Data Extraction for
Unstructured Data."* Academic papers are framed as a **representative form of
unstructured data** — keep that framing; do not drift the title or scope away
from it. The full title is: *"Smart Data Extraction for Unstructured Data: A
Hybrid NLP and Large Language Model System for Extracting Structured Entities
and Relationships from Academic Research Papers into a Queryable Knowledge
Base."*

The written project (Chapters 1–3) is done and describes this exact design.
**Chapter 4 will report what the built system actually does — real screenshots
and real precision/recall/F1 numbers — so the code must produce genuine,
evaluable outputs. Never fabricate results.**

## 2. Who the user is

A single primary user: a **student or early-career researcher** organising their
own collection of papers (some clean PDFs, some photographed/printed) — e.g. for
a literature review. The tool is personal-scale, not enterprise. Every design
decision serves that one user. There is no admin actor.

## 3. Scope (strict — stay inside this)

**In scope:** academic research papers in English, drawn from a single field
(computer science, arXiv `cs.CL`), supplied as digital PDFs *or* photographed/
scanned images; a fixed entity set; metadata relationships plus the single
semantic relationship "paper USES dataset"; per-paper summaries; a Neo4j
knowledge graph; a natural-language query interface; an evaluation of accuracy
and of digital-vs-photographed robustness.

**Out of scope:** other document types (web pages, emails, business documents),
non-English papers, training new foundation models, open-ended extraction of
arbitrary facts, richer relationship types beyond USES (these are "future work"
only). Do not expand scope to chase generality — finishability matters.

## 4. Locked design decisions (do not change without being asked)

- **Development model:** iterative / incremental. Build a thin end-to-end thread
  first on the easy path, then deepen. Work phase by phase (see §10).
- **Storage:** Neo4j (graph database), queried in Cypher. Not relational/SQL.
- **Interfaces:** one Python application backend (FastAPI), exposed through three
  thin doors — a web dashboard, a REST API, and a CLI. The REST API and CLI are
  Python and call the same backend logic. Do NOT introduce a second language for
  the CLI or backend logic.
  - **DEVIATION (Phase 4, developer-approved 2026-06-18):** the *web dashboard*
    is built as a separate **React** frontend instead of server-rendered Python.
    This consciously overrides the original "all three doors are Python" rule for
    the dashboard only. The React app is a **thin presentation layer**: it holds
    NO business logic and talks only to the FastAPI REST API. The *system* is
    still Python; React merely renders. Note for Chapter 4: Chapters 1-3 describe
    an all-Python system, so the writeup must frame React as the presentation
    layer over the Python REST API. The CLI and API remain Python.
- **Natural-language query:** an LLM translates the user's question into a Cypher
  query against the fixed schema (few-shot the schema + examples in the prompt),
  runs it, returns the answer.
- **LLM:** model-agnostic via an OpenAI-compatible endpoint (see §9). The dev
  machine is **CPU-only (no GPU)**, so prefer a fast hosted API (e.g. Groq free
  tier) for development; a small local model via Ollama is the offline/privacy
  fallback. The architecture must not depend on which is used.
- **Hybrid reliability principle:** deterministic NLP (spaCy / a PDF metadata
  parser) handles predictable bibliographic fields; the LLM handles interpretive
  fields (content entities, USES relation, summary). Keep these paths separate so
  factual metadata is not at the mercy of LLM hallucination.
- **Corpus:** download ~60 `cs.CL` papers from arXiv once and **freeze the set**
  for reproducibility.

## 5. Architecture & data flow

Two intake lanes converge on one clean-text representation, then a shared
pipeline:

```
            ┌─ digital PDF ──► extract text layer (PyMuPDF/pdfplumber) ─┐
input ──────┤                                                           ├─► clean text
            └─ image/photo ──► preprocess (OpenCV) ► OCR (Tesseract) ───┘
                                                                            │
 clean text ► NLP/NER (bibliographic entities)  +  LLM (content entities,  │
              USES relation, summary)  ► build/update Neo4j graph ◄─────────┘

 user question (NL) ► LLM ► Cypher ► run on Neo4j ► answer
```

The ingestion path and the query path are separate: papers accumulate over time;
questions run against whatever is in the graph.

## 6. Knowledge graph data model (Neo4j)

Nodes: `Paper{title, year, summary}`, `Author{name}`, `Affiliation{name}`,
`Dataset{name}`, `Keyword{term}`.
Relationships:
- `(:Paper)-[:AUTHORED_BY]->(:Author)`
- `(:Author)-[:AFFILIATED_WITH]->(:Affiliation)`
- `(:Paper)-[:HAS_KEYWORD]->(:Keyword)`
- `(:Paper)-[:USES]->(:Dataset)`  ← the project's central contribution

Use `MERGE` (not `CREATE`) when writing nodes/edges so re-ingesting a paper does
not duplicate entities. Match papers by a stable id (arXiv id) where possible.

## 7. Tech stack

Python 3.10+. PyMuPDF/pdfplumber (digital text), GROBID optional for richer
metadata, OpenCV + Tesseract via pytesseract (OCR), spaCy + `en_core_web_sm`
(NER), an OpenAI-compatible LLM client (extraction/summary/NL→Cypher), the
`neo4j` driver, FastAPI + uvicorn (backend/API), a simple web frontend, and a
Python CLI. Dependencies are in `pyproject.toml` / `requirements.txt`.

## 8. Repository layout (current state)

The Phase 0 scaffold already exists:

```
smart_extract/
  config.py            settings from .env (Neo4j + LLM_* + data dir)
  intake/              (empty — Phase 1-2)
  extraction/
    llm.py             model-agnostic LLM seam (DONE)
    prompts.py         shared extraction prompt, matches §6 schema (DONE)
  graph/               (empty — Phase 1, 4)
  query/               (empty — Phase 4)
  api/                 (empty — Phase 4)
  cli/                 (empty — Phase 1+)
  scripts/
    check_neo4j.py     Phase 0: verify Neo4j connection (DONE)
    download_arxiv.py  Phase 0: download frozen cs.CL corpus (DONE)
    spike.py           Phase 0: test LLM extraction on one paper (DONE)
tests/test_smoke.py    offline smoke tests (DONE)
data/raw/  data/gold/  gitignored data dirs
```

Config is read from `.env` (copy from `.env.example`). Install with
`pip install -e .`. Run scripts as modules from the repo root, e.g.
`python -m smart_extract.scripts.check_neo4j`.

## 9. The LLM seam (important convention)

**All LLM calls go through `smart_extract/extraction/llm.py`.** It exposes
`complete(prompt, system=None)` and `extract_json(prompt, system=None)` and talks
to any OpenAI-compatible endpoint configured by `LLM_BASE_URL`, `LLM_API_KEY`,
`LLM_MODEL` in `.env`. Do not call provider SDKs directly elsewhere or hardcode a
model — route everything through this module. This is what makes the system
"model-agnostic" (local Ollama or hosted API, swap via `.env` only).

Keep prompts in `extraction/prompts.py` so the spike and the real pipeline share
them.

## 10. Build plan (phases)

Phase 0 (DONE): scaffold, config, LLM seam, Neo4j check, arXiv downloader,
extraction spike.

**Phase 1 (NEXT): digital PDF → minimal end-to-end thread.**
- `intake/pdf.py`: extract text from a born-digital PDF (PyMuPDF/pdfplumber).
- `graph/store.py`: Neo4j writer; create constraints; MERGE Paper + Author +
  AUTHORED_BY.
- `extraction/extract.py`: run the LLM extraction (reuse prompts) → dict.
- `cli/main.py`: an `ingest <path>` command tying intake → extract → store.
- Done when: `ingest paper.pdf` puts a paper + authors in the graph.

Phase 2: image/OCR lane — `intake/image.py` (OpenCV preprocess + Tesseract);
route both lanes to one clean-text object. Also produce photographed copies of
the frozen papers for the robustness evaluation.

Phase 3: full extraction — content entities (method/dataset/metric), the USES
relation, summaries; keep deterministic vs LLM fields separate; light validation.

Phase 4: complete graph (all 5 node types, 4 edge types) + FastAPI backend + web
dashboard + finish CLI + NL→Cypher query (`query/nl2cypher.py`) + evaluation
(precision/recall/F1 on a hand-labelled gold set; digital vs photographed
comparison). This phase's outputs and numbers become Chapter 4.

Always: write a small test alongside each module; keep modules importable and
single-purpose; prefer many small increments over big rewrites.

## 11. Evaluation requirements (needed for Chapter 4)

- Hand-label ~15–20 papers in `data/gold/` as ground truth (entities + USES).
- Compute precision, recall, F1 per entity type and for the USES relation.
- Run the **same** papers as photographs and compare scores to quantify how much
  the OCR pathway degrades accuracy. This comparison is a core result.
- Provide a reproducible `scripts/evaluate.py` that prints/saves these numbers.

## 12. Coding conventions

- Python, type hints, docstrings, `from __future__ import annotations` where
  useful. Standard library + the declared deps; don't add heavy deps casually.
- All config via `smart_extract.config.settings`; never hardcode secrets/paths.
- All LLM access via `extraction/llm.py`; all prompts in `extraction/prompts.py`.
- Use `MERGE` for idempotent graph writes. Add Neo4j constraints for uniqueness.
- Small, testable functions. Add/extend `tests/` with each module (offline tests
  must not require network or services).
- Handle failure clearly (bad PDF, OCR garbage, LLM non-JSON) — surface useful
  messages rather than crashing the pipeline.

## 13. Anti-goals / guardrails (do NOT do these)

- Do **not** run OCR on born-digital PDFs — they have a real text layer; OCR only
  applies to the image/photo lane.
- Do **not** reintroduce a layout-detection model trained from scratch (e.g.
  YOLO). If layout help is needed, prefer a pretrained option; default is to rely
  on the text layer / OCR reading order.
- Do **not** add a second programming language (Go, etc.) for any interface.
- Do **not** broaden scope beyond academic papers, or add relationship types
  beyond USES, unless explicitly asked.
- Do **not** hardcode an LLM provider/model or call provider SDKs outside
  `llm.py`.
- Do **not** invent evaluation numbers, screenshots, or results.
- If the developer asks for writeup help: every reference must be real and
  verifiable, and **no source older than 2020** (strict rule for this project).

## 14. How to work with the developer

Solo developer, CPU-only machine, on a deadline. Favour the simplest thing that
works and can be demoed. Build the reliable backbone first (digital path +
metadata) so there is always a working system, then add the riskier parts (USES
extraction, OCR). Explain trade-offs briefly and honestly; push back when a
request would hurt finishability or internal consistency.