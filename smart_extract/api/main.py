"""FastAPI backend — the REST door onto the shared backend service (§4).

Endpoints (all call smart_extract.service, same logic as the CLI):
  GET  /health            -> liveness
  GET  /stats             -> node/relationship counts
  POST /ask    {question} -> NL -> Cypher, runs it, returns cypher + rows
  POST /search {query, k} -> semantic search: ranked passages + grounded answer
  POST /ingest (upload)   -> ingest an uploaded PDF/image into the graph

CORS is open for local development so the separate React dashboard can call it.
Run: uvicorn smart_extract.api.main:app --reload
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from smart_extract import service
from smart_extract.extraction.llm import LLMError
from smart_extract.intake import IntakeError
from smart_extract.query.nl2cypher import QueryError
from smart_extract.query.retrieve import RetrievalError

app = FastAPI(
    title="Smart Data Extraction API",
    description="Ingest academic papers and query the knowledge graph in English.",
    version="0.1.0",
)

# Local-dev CORS: the React dashboard runs on a different port.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    question: str
    cypher: str
    rows: list[dict]
    answer: str


class SearchRequest(BaseModel):
    query: str
    k: int = 5


class ChunkHit(BaseModel):
    arxiv_id: str | None
    title: str
    text: str
    chunk_index: int
    score: float


class SearchResponse(BaseModel):
    query: str
    answer: str
    chunks: list[ChunkHit]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/stats")
def stats() -> dict[str, int]:
    try:
        return service.graph_summary()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Graph unavailable: {exc}")


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty.")
    try:
        result = service.answer_question(question)
    except QueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc))
    return AskResponse(
        question=result.question,
        cypher=result.cypher,
        rows=result.rows,
        answer=result.answer,
    )


@app.post("/search", response_model=SearchResponse)
def search(req: SearchRequest) -> SearchResponse:
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query must not be empty.")
    try:
        result = service.search_content(query, k=max(1, min(req.k, 20)))
    except RetrievalError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"LLM error: {exc}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc))
    return SearchResponse(
        query=result.query,
        answer=result.answer,
        chunks=[
            ChunkHit(
                arxiv_id=c.paper_arxiv_id,
                title=c.paper_title,
                text=c.text,
                chunk_index=c.chunk_index,
                score=c.score,
            )
            for c in result.chunks
        ],
    )


@app.post("/ingest")
async def ingest(file: UploadFile = File(...)) -> dict:
    """Ingest an uploaded paper (PDF or image) into the graph."""
    suffix = Path(file.filename or "upload").suffix or ".pdf"
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = Path(tmp.name)
        return service.ingest_paper(tmp_path)
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"LLM error: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()
