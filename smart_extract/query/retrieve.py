"""Semantic content retrieval over paper chunks (GraphRAG).

Developer-approved extension (2026-07-16) of the original NL->Cypher-only
retrieval design — see docs/design-retrieve.md for the rationale and the
approval note. It complements, not replaces, query.nl2cypher:

  structured/relational questions -> ask()      ("Which authors used SQuAD?")
  conceptual/content questions    -> search()   ("papers about reducing hallucination")

Ingestion chunks each paper's clean text, embeds the chunks through the llm.py
seam, and stores them as (:Paper)-[:HAS_CHUNK]->(:Chunk {text, embedding})
nodes under a Neo4j native vector index — single store, no extra database.
``search()`` embeds the question, ranks chunks by cosine similarity, and
phrases a grounded answer that cites the owning papers.

The chunking functions are pure and offline (no network, no DB) so they are
unit-testable per CLAUDE.md §12; only the embed/store/search paths touch
services.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from smart_extract.extraction.llm import LLMError, complete, embed
from smart_extract.graph.store import GraphStore, open_store

# Vector index name reused by writer and reader.
CHUNK_INDEX = "chunk_embedding"


class RetrievalError(RuntimeError):
    """Raised when a semantic search cannot run (e.g. nothing indexed yet)."""


@dataclass
class Chunk:
    """One searchable passage of a paper."""

    paper_arxiv_id: str | None
    paper_title: str
    text: str
    chunk_index: int
    score: float = 0.0  # cosine similarity, filled in by search


@dataclass
class RetrievalResult:
    query: str
    chunks: list[Chunk] = field(default_factory=list)
    answer: str = ""  # grounded natural-language answer citing the papers


# --- chunking (pure, offline, testable) --------------------------------------


# Signals that a chunk is bibliography, not content: bracketed citation
# markers, publication years, venue boilerplate, and links (URLs / DOIs).
_CITATION_MARKER = re.compile(r"\[\d+\]")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_VENUE = re.compile(r"(?i)arxiv preprint|in proceedings|doi:\s*10\.|pages \d+")
_URL_DOI = re.compile(r"(?i)https?://|www\.|doi:\s*10\.|10\.\d{4,}/")
# A chunk that *opens* with a bibliography fragment: a bare URL/DOI or a
# leading [n] citation marker at the very start (a citation split mid-entry).
_LEADS_WITH_REF = re.compile(r"(?i)^\s*(?:url\s+)?(?:https?://|www\.|doi:|\[\d+\]\s)")
# Connective "function words" that flowing prose is dense in but reference
# lists (names, titles, venues, years) are not — used to spare genuine content
# that merely cites links from the link-based bibliography rules.
_FUNCTION_WORD = re.compile(
    r"(?i)\b(?:the|of|and|to|that|is|are|we|with|this|these|for|which|be|by|"
    r"as|in|on|our|from|can|has|have|not|it|its|an|a)\b"
)


def looks_like_references(chunk: str) -> bool:
    """True if a chunk reads like bibliography entries rather than content.

    Bibliography text is dense with other papers' titles and topical keywords,
    so it out-ranks real content on almost any query and misleads the grounded
    answer into citing papers that are not in the graph. Filtering is done
    per-chunk (not by locating a References section) because on arXiv the
    references often sit mid-document, followed by appendices that are worth
    keeping. A content chunk with a few inline citations like [3, 4] stays:
    the thresholds require entry-like density — many [n] markers AND many
    years, repeated venue boilerplate, or a cluster of links (URLs/DOIs), which
    prose almost never carries but reference entries almost always do.
    """
    markers = len(_CITATION_MARKER.findall(chunk))
    years = len(_YEAR.findall(chunk))
    venues = len(_VENUE.findall(chunk))
    links = len(_URL_DOI.findall(chunk))
    # A chunk boundary can land mid-entry, leaving mostly comma-separated
    # author names with a single venue string — catch that by comma density.
    commas_per_1k = chunk.count(",") * 1000 / max(len(chunk), 1)
    # Flowing prose is dense in connective function words; reference lists are
    # not. A chunk above this density is genuine content (e.g. a dataset- or
    # tooling-heavy methods paragraph citing several URLs) and must be spared
    # the link-based rules below, which would otherwise wrongly drop it.
    func_per_1k = len(_FUNCTION_WORD.findall(chunk)) * 1000 / max(len(chunk), 1)
    is_prose = func_per_1k >= 18

    if markers >= 4 and years >= 4:
        return True
    if venues >= 3:
        return True
    # Links are a strong bibliography signal, but only in non-prose: a cluster
    # of URLs/DOIs, or a single link in a short link-heavy fragment (a citation
    # split mid-entry). A prose paragraph that happens to cite a dataset or tool
    # URL stays — important for the dataset-centric papers this project targets.
    if not is_prose:
        if links >= 2:
            return True
        if links >= 1 and (venues >= 1 or years >= 1) and len(chunk) <= 300:
            return True
    # A chunk that opens with a bare URL/DOI or a leading [n] marker is the tail
    # of one reference bleeding into the next entry; require a corroborating
    # venue, year, or citation marker so a section that merely starts by quoting
    # a link (with none of those) is left alone.
    if _LEADS_WITH_REF.match(chunk) and (venues >= 1 or years >= 1 or markers >= 1):
        return True
    return venues >= 1 and commas_per_1k >= 20


def _split_paragraphs(text: str) -> list[str]:
    """Split on blank lines into paragraphs, dropping empties."""
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def _hard_split(piece: str, target_chars: int, overlap_chars: int) -> list[str]:
    """Slice an oversized piece of text into overlapping windows by length."""
    step = max(1, target_chars - overlap_chars)
    return [piece[i : i + target_chars].strip() for i in range(0, len(piece), step)]


def chunk_text(text: str, target_chars: int = 1200, overlap_chars: int = 180) -> list[str]:
    """Split clean text into overlapping windows of roughly ``target_chars``.

    Deterministic and model-independent: prefers paragraph boundaries, but a
    paragraph longer than ``target_chars`` is itself hard-split so no chunk is
    much larger than the target (oversized chunks blur semantic precision and
    waste embedding budget). Consecutive windows share an ``overlap_chars`` tail
    so a passage spanning a boundary is still retrievable. Char-based (not
    tokens) to stay dependency-free; ~1200 chars ≈ a few hundred tokens.
    """
    text = text.strip()
    if not text:
        return []

    # First, break the document into pieces no larger than target_chars: split
    # on paragraphs, then hard-split any paragraph that is still too big. A
    # hard-split window after the first already begins with the previous
    # window's overlap, so the packer must not prepend a tail to it again.
    pieces: list[tuple[str, bool]] = []  # (text, already_overlapped)
    for para in _split_paragraphs(text) or [text]:
        if len(para) > target_chars:
            windows = _hard_split(para, target_chars, overlap_chars)
            pieces.extend((w, i > 0) for i, w in enumerate(windows) if w)
        else:
            pieces.append((para, False))

    # Then greedily pack pieces up to target_chars, carrying a tail overlap.
    chunks: list[str] = []
    current = ""
    for piece, already_overlapped in pieces:
        if current and len(current) + len(piece) + 2 > target_chars:
            chunks.append(current.strip())
            if already_overlapped or not overlap_chars:
                current = piece
            else:
                current = (current[-overlap_chars:] + "\n\n" + piece).strip()
        else:
            current = (current + "\n\n" + piece).strip() if current else piece
    if current.strip():
        chunks.append(current.strip())

    return [c for c in chunks if c]


# --- index / store / search (touch the DB) -----------------------------------


def ensure_vector_index(store: GraphStore, dimensions: int) -> None:
    """Create the (:Chunk) vector index and uniqueness constraint if absent.

    Requires Neo4j 5.11+ (native vector index). ``dimensions`` must match the
    embedding model (e.g. 1536 for text-embedding-3-small, 768 for
    nomic-embed-text). Re-running is safe (IF NOT EXISTS).
    """
    store.run_write(
        "CREATE CONSTRAINT chunk_paper_key IF NOT EXISTS "
        "FOR (c:Chunk) REQUIRE (c.paper_key, c.chunk_index) IS UNIQUE"
    )
    store.run_write(
        f"CREATE VECTOR INDEX {CHUNK_INDEX} IF NOT EXISTS "
        "FOR (c:Chunk) ON (c.embedding) "
        "OPTIONS {indexConfig: {"
        "`vector.dimensions`: $dim, "
        "`vector.similarity_function`: 'cosine'}}",
        dim=dimensions,
    )


def index_paper(store: GraphStore, arxiv_id: str | None, title: str, text: str) -> int:
    """Chunk, embed, and store a paper's passages. Returns the chunk count.

    Idempotent: chunks MERGE on (paper_key, chunk_index) where ``paper_key`` is
    the arXiv id when known, else the title (MERGE cannot key on null), so
    re-indexing replaces rather than duplicates. Creates the vector index on
    first call, sized to the dimension the embedding model actually returned.
    """
    paper_key = arxiv_id or title
    if not paper_key:
        return 0
    chunks = [c for c in chunk_text(text) if not looks_like_references(c)]
    if not chunks:
        return 0
    vectors = embed(chunks)
    ensure_vector_index(store, dimensions=len(vectors[0]))

    rows = [
        {"i": i, "text": c, "embedding": v}
        for i, (c, v) in enumerate(zip(chunks, vectors))
    ]
    store.run_write(
        """
        MATCH (p:Paper)
        WHERE ($arxiv_id IS NOT NULL AND p.arxiv_id = $arxiv_id)
           OR ($arxiv_id IS NULL AND p.title = $title)
        WITH p LIMIT 1
        UNWIND $rows AS row
        MERGE (c:Chunk {paper_key: $paper_key, chunk_index: row.i})
        SET c.text = row.text, c.embedding = row.embedding
        MERGE (p)-[:HAS_CHUNK]->(c)
        """,
        arxiv_id=arxiv_id, title=title, paper_key=paper_key, rows=rows,
    )
    # A re-index that produced fewer chunks must not leave stale tails behind.
    store.run_write(
        "MATCH (c:Chunk {paper_key: $paper_key}) WHERE c.chunk_index >= $n "
        "DETACH DELETE c",
        paper_key=paper_key, n=len(rows),
    )
    return len(rows)


def retrieve(query: str, k: int = 5, store: GraphStore | None = None) -> RetrievalResult:
    """Find the k passages most semantically similar to ``query``.

    Embeds the query, runs Neo4j's native vector search over (:Chunk), and
    returns ranked Chunks with their cosine score and owning paper. Read-only.
    Raises RetrievalError when no content has been indexed yet.
    """

    def _run(s: GraphStore) -> RetrievalResult:
        query_vec = embed([query])[0]
        try:
            rows = s.run_read(
                f"""
                CALL db.index.vector.queryNodes('{CHUNK_INDEX}', $k, $vec)
                YIELD node AS c, score
                MATCH (p:Paper)-[:HAS_CHUNK]->(c)
                RETURN p.arxiv_id AS arxiv_id, p.title AS title,
                       c.text AS text, c.chunk_index AS chunk_index, score
                ORDER BY score DESC
                """,
                k=k, vec=query_vec,
            )
        except Exception as exc:  # noqa: BLE001 - map "no index" to a clear message
            if "index" in str(exc).lower():
                raise RetrievalError(
                    "No content is indexed for semantic search yet. Ingest at "
                    "least one paper (with LLM_EMBED_* configured) first."
                ) from exc
            raise
        chunks = [
            Chunk(
                paper_arxiv_id=r.get("arxiv_id"),
                paper_title=r.get("title") or "",
                text=r.get("text") or "",
                chunk_index=r.get("chunk_index", -1),
                score=float(r.get("score", 0.0)),
            )
            for r in rows
        ]
        return RetrievalResult(query=query, chunks=chunks)

    if store is not None:
        return _run(store)
    with open_store() as s:
        return _run(s)


# --- grounded answering -------------------------------------------------------

# System prompt for phrasing retrieved passages into a cited answer. Mirrors
# nl2cypher's anti-hallucination stance: only the passages, always attributed.
_GROUNDED_SYSTEM = (
    "You answer a user's question using ONLY the provided passages from academic "
    "papers. Write a short, direct answer (2-4 sentences). Cite papers by the "
    'title given in the [from "..."] label above each passage — never by titles '
    "that merely appear inside the passage text. If the passages do not contain "
    "the answer, say so plainly — never invent facts that are not in the passages."
)


def phrase_grounded_answer(query: str, chunks: list[Chunk]) -> str:
    """Turn retrieved passages into a short cited answer (best-effort).

    Like nl2cypher.phrase_answer, phrasing is a nicety: it never raises, so a
    chat-model outage cannot break search — callers still get the ranked chunks.
    """
    if not chunks:
        return ""
    passages = "\n\n".join(
        f'[from "{c.paper_title}"]\n{c.text}' for c in chunks
    )
    body = f"Question: {query}\n\nPassages:\n{passages}"
    try:
        return complete(body, system=_GROUNDED_SYSTEM).strip()
    except LLMError:
        return ""


def search(query: str, k: int = 5, store: GraphStore | None = None) -> RetrievalResult:
    """Semantic search plus a grounded, cited answer — the query-path twin of ask().

    Pipeline: embed the question -> vector-rank chunks -> phrase an answer from
    those chunks only. The chunks (with scores and owning papers) are always
    returned so every answer is attributable.
    """
    result = retrieve(query, k=k, store=store)
    result.answer = phrase_grounded_answer(query, result.chunks)
    return result
