# Design note: `retrieve()` — semantic content retrieval (GraphRAG)

**Status:** IMPLEMENTED (developer-approved 2026-07-16). The spike proved the
approach; the feature is now wired into ingestion (`service.ingest_paper`
chunk-indexes each paper, best-effort), the service layer (`search_content`),
and all three doors (`sentinel search`, `POST /search`, the dashboard's Search
page). See the CLAUDE.md §6 extension note.
**Scope flag (historical):** this adds *semantic retrieval over paper content*,
which the original CLAUDE.md design did not include — the locked design
retrieved only via NL→Cypher over extracted entities. It was adopted as a
**conscious scope extension**, approved like the Phase-4 React deviation:
deliberate, documented, justified.

---

## 1. Why — the gap this closes

Today the system has **one** retrieval mode, and it is not semantic in the way
people assume:

- A question goes to the LLM, which writes Cypher (`query/nl2cypher.py`).
- That Cypher matches stored entity strings with `CONTAINS` substring filters
  (e.g. `WHERE toLower(d.name) CONTAINS 'squad'`).
- The "intelligence" is the LLM *guessing the right keyword to grep for*; the
  retrieval underneath is literal string matching over extracted entities.

Two consequences:

1. **No matching by meaning.** "Papers about making models smaller" returns
   nothing unless an entity literally contains those words — even though papers
   on *quantization* / *distillation* are obviously relevant.
2. **No access to the paper body.** The graph stores extracted *entities* plus a
   short `Paper.summary`. The full text is never persisted or indexed, so there
   is nothing to search *into* a paper at all.

`retrieve()` adds the missing primitive: **find passages by semantic
similarity**, then (optionally) enrich with graph structure. This is the
difference between "files papers into a graph" and "a knowledge base you can ask
things of" — and it is the foundation other people would build a RAG system on.

This does **not** replace NL→Cypher. The two are complementary:

| Question shape | Mode | Example |
|---|---|---|
| Structured / relational | NL→Cypher (exists) | "Which authors used SQuAD?", "Most-used dataset?" |
| Conceptual / content | `retrieve()` (new) | "Papers about reducing hallucination", "Explain this paper's method" |

The strongest combination (**GraphRAG**) uses `retrieve()` to find relevant
chunks by meaning, then walks the graph from the owning papers to add structured
context (authors, datasets, related papers) before generation.

---

## 2. The contract

A single pure-ish function in a new module `smart_extract/query/retrieve.py`,
callable from the service layer exactly like `ask()` is today.

```python
@dataclass
class Chunk:
    paper_arxiv_id: str | None
    paper_title: str
    text: str            # the retrieved passage
    score: float         # cosine similarity in [0, 1]
    section: str | None  # best-effort section label, if known
    chunk_index: int     # position within the paper

@dataclass
class RetrievalResult:
    query: str
    chunks: list[Chunk]                 # ranked, best first
    graph_context: dict[str, Any] = ... # optional: entities around the papers

def retrieve(
    query: str,
    k: int = 8,
    *,
    filters: dict[str, Any] | None = None,  # e.g. {"year": 2024, "dataset": "squad"}
    expand_graph: bool = False,             # add structured context per paper
    store: GraphStore | None = None,
) -> RetrievalResult: ...
```

Design intent of the signature:

- **Returns context, not an answer.** The consumer brings their own generation
  step. This is what makes it *infrastructure*: a RAG builder drops `retrieve()`
  behind their own LLM prompt. (Our own dashboard would call `retrieve()` then
  `complete()` to phrase an answer — see §6.)
- **Always cites.** Every `Chunk` carries its paper id/title and position, so any
  generated answer can be grounded and attributed. This matches the project's
  existing anti-hallucination stance (grounded USES, returned Cypher).
- **`filters`** apply graph constraints *before/after* vector search (hybrid),
  e.g. "passages about distillation **in 2024 papers**". Implemented as a Cypher
  pre-filter on candidate papers, or a post-filter on results.
- **`expand_graph`** is the GraphRAG switch: off = plain vector RAG; on = also
  return the authors/datasets/keywords/related-papers around each hit.

---

## 3. Where chunks and vectors live (Neo4j, no new database)

Neo4j has a native **vector index**, so we stay single-store (CLAUDE.md §4: not
relational; one store). Add one node type and one relationship — additive, no
change to the existing §6 model:

```
(:Paper {arxiv_id, title, year, summary})            # unchanged
   -[:HAS_CHUNK]->
(:Chunk {chunk_index, text, section, embedding})     # NEW
```

- `Chunk.embedding` is a `LIST<FLOAT>` of fixed dimension `D` (set by the
  embedding model; e.g. 384 for a small local model, 1536 for a hosted one).
- A vector index over it:
  ```cypher
  CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS
  FOR (c:Chunk) ON (c.embedding)
  OPTIONS { indexConfig: {
    `vector.dimensions`: $D,
    `vector.similarity_function`: 'cosine'
  }}
  ```
- Uniqueness: `(:Chunk)` keyed by `(paper, chunk_index)` via a constraint, so
  re-ingesting a paper re-MERGEs chunks idempotently — consistent with the
  existing MERGE-everything rule. Add to `_CONSTRAINTS` in `graph/store.py`.

**Why store the body now:** chunks finally persist the paper text the graph has
been missing. The summary stays as-is; chunks are the searchable body.

---

## 4. The embedding seam (extend `llm.py`, do not bypass it)

CLAUDE.md §9 says *all* model access goes through `extraction/llm.py`. Embeddings
are model access, so they belong there too — add a third public function beside
`complete()` and `extract_json()`:

```python
def embed(texts: list[str]) -> list[list[float]]:
    """Return one embedding vector per input text via the OpenAI-compatible seam."""
```

Implementation notes:
- Use the same OpenAI-compatible client (`_client()`), calling
  `client.embeddings.create(model=settings.llm_embed_model, input=texts)`.
- New `.env` key `LLM_EMBED_MODEL` (+ `llm_embed_model` in `config.py`). Keeps
  the system model-agnostic: a hosted embedding model **or** a local one (Ollama
  exposes `/embeddings`; or a small `sentence-transformers` model runs fine
  CPU-only — note the dev machine is GPU-less, §4). The architecture must not
  depend on which.
- Batch inputs; embeddings endpoints accept many texts per call.
- Raise `LLMError` on failure, like the other seam functions.

This keeps the "swap providers via .env only" guarantee intact for embeddings.

---

## 5. The pipeline `retrieve()` runs

```
query ─► embed(query) ─► Neo4j vector search (db.index.vector.queryNodes)
                              │   top-N candidate Chunks by cosine
       filters ──────────────┤   (pre-filter papers and/or post-filter hits)
                              ▼
                        ranked Chunks
                              │
        expand_graph? ──► for each owning Paper, MATCH its authors / datasets /
                          keywords / USES neighbours ─► graph_context
                              ▼
                        RetrievalResult(chunks, graph_context)
```

Vector query (read-only, runs through `GraphStore.run_read`):

```cypher
CALL db.index.vector.queryNodes('chunk_embedding', $k, $query_vec)
YIELD node AS c, score
MATCH (p:Paper)-[:HAS_CHUNK]->(c)
RETURN p.arxiv_id AS arxiv_id, p.title AS title,
       c.text AS text, c.section AS section,
       c.chunk_index AS chunk_index, score
ORDER BY score DESC
```

Chunking strategy (kept deliberately simple for v1):
- Split clean text into ~500–800 token windows with ~15% overlap, on paragraph
  boundaries where possible. Carry a best-effort `section` label.
- Chunking is deterministic and offline → **unit-testable with no network**
  (per §12), independent of the embedding model.

---

## 6. How it plugs into what already exists

- **Ingestion** (`service.ingest_paper`): after extraction/store, also chunk the
  same clean text, `embed()` the chunks, and write `(:Chunk)` nodes. One added
  step in a path that already has the clean text in hand — no second intake.
- **Service layer**: add `search_content(query, k, ...)` beside
  `answer_question()`, returning `RetrievalResult`. All three doors (CLI, API,
  React) reach it through the service, unchanged in pattern.
- **Our own answers get smarter for free:** a new `answer_semantic()` can
  `retrieve()` then `complete()` over the chunks to produce a *grounded,
  cited* natural-language answer — directly reinforcing the project's
  anti-hallucination theme.
- **Router (optional, later):** a thin classifier (LLM or heuristic) sends
  structured questions to `ask()` (Cypher) and conceptual ones to
  `search_content()` (vectors). Not required for v1; can start as two explicit
  endpoints / CLI subcommands.

---

## 7. Evaluation hook (so it earns a place in the writeup)

To avoid an unmeasured feature (CLAUDE.md §11/§13 — real numbers only):
- Hand-label a small set of `(question → relevant paper/passage)` pairs.
- Report **Recall@k** / **MRR** for `retrieve()` on the frozen corpus.
- Compare *keyword-Cypher-only* vs *vector* vs *hybrid* on conceptual questions
  to show the gain is real, not asserted. This becomes a clean Chapter-5 result.

---

## 8. Risks / honest cautions

1. **New surface area on a deadline.** Chunking, an embedding seam, a vector
   index, write-path changes, and an eval harness. Only take this on once
   **Phase-4 evaluation is on track** — a finished, evaluated narrow system
   beats a smarter, unproven one for grading.
2. **Scope.** It crosses the CLAUDE.md line on retrieval; needs explicit
   developer sign-off and a writeup framing (Chapter 5 future work, or an
   approved extension paralleling the React deviation).
3. **Embedding model choice affects `D`** and therefore the index. Pin the model
   in `.env`; re-embedding the corpus is required if it changes. Document the
   chosen model and dimension for reproducibility (the corpus is frozen, §4).
4. **Cost/time of embedding the corpus** is a one-off batch over ~60 papers —
   trivial at this scale, but note it so re-runs are intentional.

---

## 9. Smallest viable spike (to prove it, not ship it)

1. Add `embed()` to `llm.py` + `LLM_EMBED_MODEL` to config.
2. Add `db.index.vector` constraint/index + `(:Chunk)` write to `graph/store.py`.
3. `query/retrieve.py` with deterministic chunking + the vector query above.
4. A script that ingests **one** paper's chunks and runs three conceptual
   queries, printing ranked passages with scores.

If the spike returns sensible passages for meaning-based queries that
keyword-Cypher misses, the claim "this generalises toward RAG infrastructure" is
**demonstrated**, and the full build can be scheduled deliberately.