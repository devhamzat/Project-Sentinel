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
    page: int | None = None  # 1-based source page, when the intake lane knew it


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


# A sentence end: ., ! or ? (optionally closed by a quote/bracket) followed by
# whitespace or end of string. Used to prefer clean cut points over mid-word.
_SENTENCE_END = re.compile(r"[.!?][\"')\]]?(?=\s|$)")


def _overlap_tail(text: str, overlap_chars: int) -> str:
    """Return trailing context of ``text`` to carry into the next chunk.

    The overlap exists so a passage spanning a chunk boundary is still
    retrievable, so the ideal tail is one or more *whole* trailing sentences
    rather than a mid-word char slice. Return the longest run of complete
    sentences at the end of ``text`` that fits within ``overlap_chars``. If the
    final sentence alone is longer than the budget (or the text has no sentence
    break at all), fall back to the raw ``overlap_chars`` slice so the boundary
    is still covered.
    """
    if overlap_chars <= 0:
        return ""
    if len(text) <= overlap_chars:
        return text
    threshold = len(text) - overlap_chars
    # Start the tail just after the last sentence end that still leaves the tail
    # within the overlap budget.
    start = None
    for m in _SENTENCE_END.finditer(text):
        if m.end() >= threshold:
            start = m.end()
            break
    if start is not None and start < len(text):
        return text[start:].lstrip()
    return text[-overlap_chars:]


def _find_cut(piece: str, target: int, floor: int) -> int:
    """Return the index to cut ``piece`` at, at or before ``target``.

    Prefer the last sentence end that lands in the window ``[floor, target]`` so
    a chunk stops on a clean boundary. If the piece is shorter than ``target``,
    cut at its end. If no sentence end sits in the window (e.g. a long unbroken
    run with no punctuation), fall back to the hard length cut at ``target`` so
    oversized pieces still split.
    """
    if len(piece) <= target:
        return len(piece)
    best = -1
    for m in _SENTENCE_END.finditer(piece, floor, target):
        best = m.end()
    return best if best != -1 else target


def _hard_split(piece: str, target_chars: int, overlap_chars: int) -> list[str]:
    """Slice an oversized piece into overlapping windows, preferring sentence ends.

    Each window is grown up to ``target_chars`` but cut back to the last sentence
    boundary within a tolerance of the target (``_find_cut``), falling back to a
    raw length cut when the text has no punctuation to break on. The next window
    starts ``overlap_chars`` before the actual cut so a sentence straddling a
    boundary is still retrievable.
    """
    windows: list[str] = []
    # Only look for a sentence end in the last portion of the window, so we don't
    # cut a window drastically short just because an early sentence ended.
    floor = max(1, target_chars - max(overlap_chars, target_chars // 4))
    start = 0
    while start < len(piece):
        rel_cut = _find_cut(piece[start:], target_chars, floor)
        end = start + rel_cut
        window = piece[start:end].strip()
        if window:
            windows.append(window)
        if end >= len(piece):
            break
        # Begin the next window overlap_chars back, but snap forward to the last
        # sentence end in that region so a window starts on a fresh sentence
        # rather than mid-word. Always advance to avoid looping on unbroken text.
        raw_start = max(0, end - overlap_chars)
        snapped = raw_start
        for m in _SENTENCE_END.finditer(piece, raw_start, end):
            # Skip a sentence end that coincides with the window end — that
            # boundary belongs to this window, not the start of the next.
            if m.end() < end:
                snapped = m.end()
        start = max(start + 1, snapped)
    return windows


def chunk_text(text: str, target_chars: int = 1200, overlap_chars: int = 180) -> list[str]:
    """Split clean text into overlapping windows of roughly ``target_chars``.

    Deterministic and model-independent: prefers paragraph boundaries, but a
    paragraph longer than ``target_chars`` is itself split so no chunk is much
    larger than the target (oversized chunks blur semantic precision and waste
    embedding budget). Splits prefer the nearest sentence end within a tolerance
    of the target, falling back to a raw length cut only when the text has no
    punctuation to break on, so chunks rarely start or end mid-sentence.
    Consecutive windows share an ``overlap_chars`` tail (also snapped to a
    sentence where possible) so a passage spanning a boundary is still
    retrievable. Char-based (not tokens) to stay dependency-free; ~1200 chars ≈
    a few hundred tokens.
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
                current = (_overlap_tail(current, overlap_chars) + "\n\n" + piece).strip()
        else:
            current = (current + "\n\n" + piece).strip() if current else piece
    if current.strip():
        chunks.append(current.strip())

    return [c for c in chunks if c]


def chunk_pages(pages: list[str]) -> list[tuple[str, int]]:
    """Chunk page-by-page, tagging each chunk with its 1-based page number.

    A thin wrapper over ``chunk_text`` that preserves page provenance for
    citation locators. Chunking each page independently (rather than the whole
    document at once) keeps every chunk on a single page, so its page number is
    unambiguous — at the cost of not merging a short page tail with the next
    page's head, which is an acceptable trade for a clean locator. Returns
    ``(chunk_text, page_number)`` pairs in reading order.
    """
    out: list[tuple[str, int]] = []
    for page_no, page_text in enumerate(pages, start=1):
        for chunk in chunk_text(page_text):
            out.append((chunk, page_no))
    return out


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


def index_paper(
    store: GraphStore,
    arxiv_id: str | None,
    title: str,
    text: str,
    owner_id: str | None = None,
    pages: list[str] | None = None,
) -> int:
    """Chunk, embed, and store a paper's passages. Returns the chunk count.

    Idempotent: chunks MERGE on (paper_key, chunk_index) where ``paper_key`` is
    the arXiv id when known, else the title (MERGE cannot key on null), so
    re-indexing replaces rather than duplicates. Creates the vector index on
    first call, sized to the dimension the embedding model actually returned.

    When ``pages`` (per-page text, e.g. from the digital-PDF lane) is given,
    chunks are cut page-by-page and each records its 1-based source page so the
    grounded answer can cite a locator (``p.6``). Without it, the whole ``text``
    is chunked as before and page is null — the OCR lane and older callers are
    unaffected.
    """
    identity = arxiv_id or title
    if not identity:
        return 0
    paper_key = f"{owner_id}:{identity}" if owner_id else identity
    if pages:
        tagged = [
            (c, pg) for c, pg in chunk_pages(pages) if not looks_like_references(c)
        ]
    else:
        tagged = [(c, None) for c in chunk_text(text) if not looks_like_references(c)]
    if not tagged:
        return 0
    chunks = [c for c, _ in tagged]
    vectors = embed(chunks)
    ensure_vector_index(store, dimensions=len(vectors[0]))

    rows = [
        {"i": i, "text": c, "embedding": v, "page": pg}
        for i, ((c, pg), v) in enumerate(zip(tagged, vectors))
    ]
    store.run_write(
        """
        MATCH (p:Paper)
        WHERE ($arxiv_id IS NOT NULL AND p.arxiv_id = $arxiv_id)
           OR ($arxiv_id IS NULL AND p.title = $title)
        WITH p LIMIT 1
        OPTIONAL MATCH (w:Workspace {id:$owner_id})-[:OWNS]->(p)
        WITH p, w
        WHERE $owner_id IS NULL OR w IS NOT NULL
        UNWIND $rows AS row
        MERGE (c:Chunk {paper_key: $paper_key, chunk_index: row.i})
        SET c.text = row.text, c.embedding = row.embedding,
            c.owner_id = $owner_id, c.page = row.page
        MERGE (p)-[:HAS_CHUNK]->(c)
        """,
        arxiv_id=arxiv_id, title=title, paper_key=paper_key, rows=rows,
        owner_id=owner_id,
    )
    # A re-index that produced fewer chunks must not leave stale tails behind.
    store.run_write(
        "MATCH (c:Chunk {paper_key: $paper_key}) WHERE c.chunk_index >= $n "
        "DETACH DELETE c",
        paper_key=paper_key, n=len(rows),
    )
    return len(rows)


def retrieve(
    query: str,
    k: int = 5,
    store: GraphStore | None = None,
    owner_id: str | None = None,
) -> RetrievalResult:
    """Find the k passages most semantically similar to ``query``.

    Embeds the query, runs Neo4j's native vector search over (:Chunk), and
    returns ranked Chunks with their cosine score and owning paper. Read-only.
    Raises RetrievalError when no content has been indexed yet.
    """

    def _run(s: GraphStore) -> RetrievalResult:
        query_vec = embed([query])[0]
        try:
            if owner_id:
                # The vector index is global, so over-fetch candidates and then
                # discard every chunk outside the authenticated workspace.
                rows = s.run_read(
                    f"""
                    CALL db.index.vector.queryNodes('{CHUNK_INDEX}', $candidate_k, $vec)
                    YIELD node AS c, score
                    MATCH (w:Workspace {{id:$owner_id}})-[:OWNS]->(p:Paper)-[:HAS_CHUNK]->(c)
                    WHERE c.owner_id = $owner_id
                    RETURN p.arxiv_id AS arxiv_id, p.title AS title,
                           c.text AS text, c.chunk_index AS chunk_index,
                           c.page AS page, score
                    ORDER BY score DESC LIMIT $k
                    """,
                    candidate_k=max(100, k * 20), k=k, vec=query_vec,
                    owner_id=owner_id,
                )
            else:
                rows = s.run_read(
                    f"""
                    CALL db.index.vector.queryNodes('{CHUNK_INDEX}', $k, $vec)
                    YIELD node AS c, score
                    MATCH (p:Paper)-[:HAS_CHUNK]->(c)
                    RETURN p.arxiv_id AS arxiv_id, p.title AS title,
                           c.text AS text, c.chunk_index AS chunk_index,
                           c.page AS page, score
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
                page=r.get("page"),
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
    "that merely appear inside the passage text. When the label includes a page "
    "(e.g. p.6), you may include it in the citation. If the passages do not "
    "contain the answer, say so plainly — never invent facts that are not in the "
    "passages."
)


def _passage_label(chunk: Chunk) -> str:
    """Attribution label above a passage: the paper title, plus page if known."""
    if chunk.page:
        return f'[from "{chunk.paper_title}", p.{chunk.page}]'
    return f'[from "{chunk.paper_title}"]'


def phrase_grounded_answer(query: str, chunks: list[Chunk]) -> str:
    """Turn retrieved passages into a short cited answer (best-effort).

    Like nl2cypher.phrase_answer, phrasing is a nicety: it never raises, so a
    chat-model outage cannot break search — callers still get the ranked chunks.
    """
    if not chunks:
        return ""
    passages = "\n\n".join(
        f"{_passage_label(c)}\n{c.text}" for c in chunks
    )
    body = f"Question: {query}\n\nPassages:\n{passages}"
    try:
        return complete(body, system=_GROUNDED_SYSTEM).strip()
    except LLMError:
        return ""


def search(
    query: str,
    k: int = 5,
    store: GraphStore | None = None,
    owner_id: str | None = None,
) -> RetrievalResult:
    """Semantic search plus a grounded, cited answer — the query-path twin of ask().

    Pipeline: embed the question -> vector-rank chunks -> phrase an answer from
    those chunks only. The chunks (with scores and owning papers) are always
    returned so every answer is attributable.
    """
    result = retrieve(query, k=k, store=store, owner_id=owner_id)
    result.answer = phrase_grounded_answer(query, result.chunks)
    return result
