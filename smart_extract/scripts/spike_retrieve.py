"""SPIKE: prove semantic retrieval finds what keyword-Cypher cannot (§9 of
docs/design-retrieve.md).

Run from the repo root (needs Neo4j 5.11+ running and an embeddings endpoint
configured — see LLM_EMBED_* in .env):

    python -m smart_extract.scripts.spike_retrieve                 # default paper
    python -m smart_extract.scripts.spike_retrieve 2606.18237      # pick a paper
    python -m smart_extract.scripts.spike_retrieve 2606.18237 "how do they reduce hallucination?"

It (1) reads one frozen PDF, (2) chunks + embeds + stores it as (:Chunk) nodes
with a vector index, and (3) runs a few conceptual queries, printing the
top-ranked passages with cosine scores. If meaning-based queries surface the
right passages (even with no shared keywords), the GraphRAG claim is
demonstrated, not asserted.

This does NOT change ingestion or the service layer. It only adds (:Chunk)
nodes/index to the graph for the chosen paper.
"""

from __future__ import annotations

import sys

from smart_extract.config import settings
from smart_extract.extraction.llm import LLMError
from smart_extract.graph.store import open_store
from smart_extract.intake.pdf import read_pdf
from smart_extract.query.retrieve import chunk_text, index_paper, retrieve

DEFAULT_QUERIES = [
    "How do the authors evaluate or measure their results?",
    "What are the main limitations or weaknesses of this work?",
    "What datasets or benchmarks are used?",
]


def _pick_pdf(arxiv_id: str | None):
    if arxiv_id:
        hits = sorted(settings.raw_dir.glob(f"{arxiv_id}*.pdf"))
    else:
        hits = sorted(settings.raw_dir.glob("*.pdf"))
    return hits[0] if hits else None


def main() -> int:
    args = sys.argv[1:]
    arxiv_id = args[0] if args and "." in args[0] else None
    extra_query = next((a for a in args if " " in a or "?" in a), None)
    queries = [extra_query] if extra_query else DEFAULT_QUERIES

    pdf = _pick_pdf(arxiv_id)
    if pdf is None:
        print(f"No PDF found in {settings.raw_dir} (looked for {arxiv_id or 'any'}).")
        return 1

    intake = read_pdf(pdf)
    aid = intake.arxiv_id
    print(f"Paper: {pdf.name}  (arxiv {aid})")

    # Offline sanity check first — chunking needs no services.
    chunks = chunk_text(intake.text)
    print(f"Chunked into {len(chunks)} passages (avg "
          f"{sum(len(c) for c in chunks) // max(len(chunks), 1)} chars).")
    if not chunks:
        print("No chunks produced; aborting.")
        return 1

    try:
        with open_store() as store:
            # The paper must already exist in the graph (ingest it first) so the
            # chunks attach to it. If it isn't there, create a minimal stub Paper.
            existing = store.run_read(
                "MATCH (p:Paper {arxiv_id:$a}) RETURN p.title AS t", a=aid
            )
            if not existing:
                print("  paper not in graph yet — creating a minimal stub Paper.")
                store.run_write(
                    "MERGE (p:Paper {arxiv_id:$a}) SET p.title = coalesce(p.title,$t)",
                    a=aid, t=pdf.stem,
                )

            n = index_paper(store, aid, existing[0]["t"] if existing else pdf.stem,
                            intake.text)
            print(f"Indexed {n} chunks with embeddings + vector index.\n")

            for q in queries:
                print(f"Q: {q}")
                result = retrieve(q, k=3, store=store)
                if not result.chunks:
                    print("   (no results)\n")
                    continue
                for c in result.chunks:
                    preview = " ".join(c.text.split())[:160]
                    print(f"   [{c.score:.3f}] #{c.chunk_index}: {preview}…")
                print()
    except LLMError as exc:
        print(f"\nEmbedding/LLM error: {exc}\n"
              "Set LLM_EMBED_BASE_URL / LLM_EMBED_API_KEY / LLM_EMBED_MODEL in .env "
              "(your chat provider may not serve embeddings).")
        return 1
    except Exception as exc:  # noqa: BLE001 - spike: surface DB/index errors plainly
        print(f"\nGraph/vector error: {exc}\n"
              "Vector search needs Neo4j 5.11+. Check the DB is up and the version.")
        return 1

    print("Done. If the passages above match the questions' meaning, semantic "
          "retrieval works — the GraphRAG claim is demonstrated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
