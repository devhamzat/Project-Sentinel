# Chapter 4 Handoff — Context for Writing "Results & Evaluation"

**Purpose of this file.** You (Claude, in a chat window with no access to the
code) wrote Chapters 1–3 of this final-year project. This note gives you
everything needed to write **Chapter 4 (System Implementation + Results &
Evaluation)** so it is (a) faithful to what the built system *actually does* and
(b) internally consistent with Chapters 1–3. **Every number, screenshot, and
claim in Chapter 4 must be real and verifiable — nothing may be invented.** The
numbers below are genuine outputs of the built system, computed against a
hand-labelled gold set. Use them exactly; do not round differently or embellish.

---

## 1. What the project is (recap, so Ch.4 stays on-topic)

**Title:** *"Smart Data Extraction for Unstructured Data: A Hybrid NLP and Large
Language Model System for Extracting Structured Entities and Relationships from
Academic Research Papers into a Queryable Knowledge Base."*

B.Sc. Computer Science, Crescent University Abeokuta. Academic papers are the
chosen **representative form of unstructured data** — keep that framing; do not
drift the scope toward general document processing.

The system ingests academic CS papers (arXiv `cs.CL`) as **born-digital PDFs**
or **photographed/scanned images**, extracts structured entities and the central
`USES` (paper→dataset) relationship plus a summary, builds a **Neo4j knowledge
graph**, and answers natural-language questions (LLM→Cypher) plus semantic
content search (GraphRAG). Chapters 1–3 describe this exact design.

---

## 2. What was actually built (all phases complete)

A working end-to-end system. Concretely:

- **Two intake lanes → one clean-text representation.**
  - Digital: PyMuPDF/pdfplumber extract the PDF text layer (no OCR on digital —
    that would be wrong).
  - Photo: OpenCV preprocessing + Tesseract OCR on photographed page images.
- **Hybrid extraction.** Deterministic NLP (spaCy) handles predictable
  bibliographic fields; an LLM handles interpretive fields (content entities,
  the `USES` relation, the summary). These paths are deliberately separate so
  factual metadata is not at the mercy of LLM hallucination. **This hybrid split
  is the thesis, and the evaluation below empirically supports it** (see §5).
- **Model-agnostic LLM seam.** All LLM calls route through one module talking to
  any OpenAI-compatible endpoint, configured by `.env` only. Development used
  **Groq's hosted `llama-3.1-8b-instant`** (the dev machine is CPU-only, so a
  fast hosted API was used; a local Ollama model is the offline fallback). The
  architecture does not depend on which is used.
- **Neo4j knowledge graph** (see §3 for the schema), written idempotently with
  `MERGE` so re-ingesting a paper does not duplicate nodes.
- **Three "doors" onto one shared Python backend service:**
  - **FastAPI** REST API (the only layer that calls the backend service logic),
  - a **Python remote CLI** (`sentinel`) — a thin HTTP client,
  - a **React web dashboard** — a thin *presentation* layer that holds no
    business logic and talks only to the REST API. *(Note for the writeup:
    Chapters 1–3 describe an all-Python system; Chapter 4 should frame React as
    the presentation layer over the Python REST API — the system is still
    Python, React merely renders.)*
- **The remote CLI (`sentinel`) in detail.** A Python command-line client that
  authenticates against the REST API (session tokens saved locally) and drives
  the same backend as the dashboard. It supports Cloudflare Access for remote
  deployments. Its commands are:
  - `sentinel login` / `sentinel register` / `sentinel logout` / `sentinel whoami`
    — session management (register creates a tester workspace and signs in).
  - `sentinel ingest <path>` — upload a PDF or photo for ingestion into the graph.
  - `sentinel ask "<question>"` — natural-language question answered via NL→Cypher.
  - `sentinel search "<query>"` — semantic passage search over ingested papers.
  - `sentinel stats` — node/relationship counts for the active workspace.
  - `sentinel users add|list|claim|reset-password|disable|enable` — admin-only
    account management (mirrors the auth/multi-tenant enhancement in this section).
  For Chapter 4, the CLI is a good way to *show the system working without the
  browser*: a terminal transcript of `sentinel ingest` then `sentinel ask` /
  `sentinel search` demonstrates the same pipeline as the dashboard. Any such
  transcript must be captured from a real run — do not fabricate CLI output.
- **Natural-language querying:** an LLM translates the user's English question
  into Cypher against the fixed schema, runs it, and returns the answer.
- **Semantic search (GraphRAG extension):** each paper's body is chunked and
  embedded into Neo4j; a search endpoint returns meaning-ranked passages plus a
  grounded, cited answer. This *complements* NL→Cypher (structured questions →
  Cypher; conceptual questions → semantic search).
- **Multi-tenant authentication (an enhancement beyond the original scope).**
  The original design (Chapters 1–3) framed a single-user personal tool. The
  built system went further: per-workspace accounts with isolation, scrypt
  password hashing, HMAC-signed session tokens, and self-registration of
  "tester" accounts. **How to frame this in Ch.4:** present it honestly as an
  *implementation enhancement* — the core extraction/graph/query system is
  unchanged; auth/workspaces were added so the system could be deployed and used
  by more than one person. Do not pretend Chapters 1–3 predicted it; say the
  implementation extended the design in this respect.

---

## 3. Knowledge graph schema (state this exactly)

**Nodes:** `Paper{title, year, summary}`, `Author{name}`, `Affiliation{name}`,
`Dataset{name}`, `Keyword{term}`.

**Relationships:**
- `(:Paper)-[:AUTHORED_BY]->(:Author)`
- `(:Author)-[:AFFILIATED_WITH]->(:Affiliation)`
- `(:Paper)-[:HAS_KEYWORD]->(:Keyword)`
- `(:Paper)-[:USES]->(:Dataset)` ← **the project's central contribution**

Plus infrastructure for semantic search (not a knowledge entity):
`(:Paper)-[:HAS_CHUNK]->(:Chunk {text, embedding, ...})` under a Neo4j native
vector index. In a multi-tenant deployment, papers are owned per workspace so
tenants' graphs are isolated.

---

## 4. Evaluation method (describe this before the results)

- **Corpus:** 62 `cs.CL` papers were downloaded once from arXiv and **frozen**
  for reproducibility. (Chapters 1–3 say "~60"; the exact frozen number is 62.)
- **Gold set:** **15** of those papers were **hand-labelled by the developer** as
  ground truth — author names, affiliations, keywords, datasets (the `USES`
  relation), methods, and metrics — each value verified against the paper
  itself. Labelling was done through a purpose-built admin labelling interface
  that shows, for every pre-filled value, whether it actually appears in the
  paper text (a hint only — the human decided every value). **The gold set was
  produced independently of the model's own output; the system was never used to
  grade itself.** State this clearly — it is what makes the accuracy numbers
  meaningful.
- **Metric:** for each field, predictions vs gold are compared as **sets** of
  normalised strings, giving **precision, recall, and F1** per field, plus a
  micro-averaged **overall**. Counts are reported as true positives / false
  positives / false negatives (tp/fp/fn).
- **Two lanes, same 15 papers:** extraction was run on the **digital** source
  (PDF text) and on the **photographed** source (OCR of the page image), and the
  scores compared. This digital-vs-photograph comparison **quantifies how much
  the OCR pathway degrades accuracy** — a core required result.
- **Reproducibility:** the evaluation is a single script
  (`scripts/evaluate.py --compare`) that re-runs extraction and prints/saves the
  numbers. LLM calls retry transient network failures with backoff so a dropped
  connection does not silently drop a paper from the scored set (this was a real
  bug that invalidated a first run; it is fixed, and the reported numbers below
  are from a clean run where all 15 papers scored on both lanes).

---

## 5. Results (REAL numbers — use exactly; do not invent or alter)

Model: `llama-3.1-8b-instant` (Groq). Gold set: 15 papers. Same papers on both
lanes.

### Digital lane (born-digital PDF text)

| Field           |   P   |   R   |  F1   | tp/fp/fn |
|-----------------|-------|-------|-------|----------|
| authors         | 1.000 | 1.000 | 1.000 | 69/0/0   |
| affiliations    | 1.000 | 0.938 | 0.968 | 30/0/2   |
| keywords        | 0.884 | 0.866 | 0.875 | 84/11/13 |
| datasets (USES) | 0.824 | 0.560 | 0.667 | 14/3/11  |
| methods         | 0.825 | 0.797 | 0.810 | 47/10/12 |
| metrics         | 0.844 | 0.794 | 0.818 | 27/5/7   |
| **overall**     | **0.903** | **0.858** | **0.880** | 271/29/45 |

### Photo lane (OCR of the page image)

| Field           |   P   |   R   |  F1   | tp/fp/fn |
|-----------------|-------|-------|-------|----------|
| authors         | 0.746 | 0.725 | 0.735 | 50/17/19 |
| affiliations    | 0.621 | 0.562 | 0.590 | 18/11/14 |
| keywords        | 0.742 | 0.505 | 0.601 | 49/17/48 |
| datasets (USES) | 0.700 | 0.280 | 0.400 | 7/3/18   |
| methods         | 0.184 | 0.119 | 0.144 | 7/31/52  |
| metrics         | 0.476 | 0.294 | 0.364 | 10/11/24 |
| **overall**     | **0.610** | **0.446** | **0.516** | 141/90/175 |

### OCR robustness (headline comparison)

**Overall F1: digital 0.880 → photo 0.516, a drop of 0.364.**

(The raw JSON with 4-decimal precision lives at `data/eval_results.json`; the
overall photo F1 there is 0.5155.)

---

## 6. How to interpret the results (this is the analysis Ch.4 needs)

1. **The hybrid-reliability design is empirically confirmed.** On the digital
   lane, the deterministic-style bibliographic fields are near-perfect
   (**authors F1 = 1.000, affiliations = 0.968**), while the LLM-interpretive
   fields are lower and more variable (**datasets 0.667, methods 0.810, metrics
   0.818, keywords 0.875**). This is exactly the pattern the hybrid architecture
   predicts and justifies: route predictable fields through deterministic NLP,
   interpretive fields through the LLM. This is the central positive result.

2. **Photographing papers substantially degrades accuracy** (overall F1 0.880 →
   0.516). This quantifies the cost of the image/OCR pathway and is the required
   digital-vs-photograph robustness result. Bibliographic fields survive OCR
   better than interpretive ones.

3. **The `USES` relation (datasets) is the hardest field** even on clean text
   (recall 0.560 — the model misses just under half the labelled datasets). As
   the project's central contribution, this deserves explicit discussion:
   precision is decent (0.824), so when it names a dataset it is usually right,
   but recall is the weakness.

### Caveats you MUST state honestly (do not hide these)

- **The photo lane sees only the first page of each paper.** The photographed
  set is one image per paper (page 1). So on the photo lane, fields that
  typically appear later in a paper (many methods, metrics, and datasets) are
  low **partly by construction**, not purely from OCR error — e.g. methods F1 =
  0.144 reflects both OCR degradation *and* content that simply is not on page
  one. Name this as a limitation of the evaluation setup; it is more credible to
  state it than to let it be discovered. (Digital extraction reads the whole
  paper, so the two lanes are not a pure like-for-like OCR test — they are a
  realistic "clean full PDF vs single photographed page" comparison.)
- **A small model was used.** `llama-3.1-8b-instant` is fast and free but modest;
  the interpretive-field scores would likely rise with a larger model. The
  numbers are honest for this configuration. Frame a larger model as future work.
- **Sample size.** 15 hand-labelled papers is within the planned range but
  small; report it as such and avoid over-generalising.
- **Ingest reliability with a small model.** When the full 62-paper corpus was
  (re-)ingested, **56 succeeded and 6 failed**: 1 exceeded the 25 MB upload
  guard, and 5 failed because `llama-3.1-8b-instant` returned malformed/over-long
  JSON (`json_validate_failed`). Report this honestly — it quantifies the
  JSON-reliability limit of a small model on the extraction task and motivates
  "larger model" as future work. It is not a crash: the pipeline surfaces a clear
  error per paper and continues.

---

## 7. Chapter 4 structure suggestion

1. **System implementation** — walk the built architecture (two lanes → clean
   text → hybrid extraction → Neo4j → three interfaces), the technology choices,
   and the multi-tenant enhancement (framed per §2). Include real screenshots of
   the dashboard (login/workspace, ingest, ask, search) and CLI output. *(These
   screenshots must be captured from the running system — do not fabricate them.
   If a screenshot is not yet available, leave a clearly marked placeholder for
   the developer to fill, rather than inventing an image description.)*
   **Real, unedited CLI runs are already captured in `docs/cli-transcript.md`**
   (help surface, whoami, stats, ingest, ask incl. a genuine NL→Cypher failure,
   and semantic search) — use them verbatim for the CLI figures/examples.
2. **Evaluation methodology** — §4 above (corpus, gold set + independence,
   metric, two-lane comparison, reproducibility).
3. **Results** — the two tables and the OCR-robustness figure from §5.
4. **Discussion / analysis** — §6 (hybrid confirmed; OCR cost; USES difficulty;
   caveats stated honestly).
5. **Limitations & future work** — single-page photo lane, small model, sample
   size, richer relations beyond `USES`, larger gold set.

---

## 8. Hard rules for the writeup (carry over from the project's standards)

- **Never fabricate** results, numbers, screenshots, or citations. Use the real
  numbers in §5 verbatim.
- Keep the scope to **academic papers as unstructured data**; do not broaden to
  general document processing.
- **`USES` is the only semantic relationship** in scope; richer relations are
  future work only.
- If you add **references**: every source must be real and verifiable, and **no
  source older than 2020** (strict rule for this project).
- Frame **React** as the presentation layer over a Python REST API, and
  **multi-tenant auth** as an implementation enhancement beyond the Chapters 1–3
  design — honestly, not retroactively.