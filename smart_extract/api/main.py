"""FastAPI backend — the REST door onto the shared backend service (§4).

Data endpoints call smart_extract.service; the remote CLI calls these endpoints:
  GET  /health            -> liveness
  GET  /stats             -> node/relationship counts
  POST /ask    {question} -> NL -> Cypher, runs it, returns cypher + rows
  POST /search {query, k} -> semantic search: ranked passages + grounded answer
  POST /ingest (upload)   -> ingest an uploaded PDF/image into the graph

CORS uses an explicit allowlist so the separate React dashboard can call it.
Run: uvicorn smart_extract.api.main:app --reload
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from smart_extract import service
from smart_extract import service_gold
from smart_extract.service_gold import GoldError
from smart_extract.auth import (
    AuthError,
    AuthConfigurationError,
    InvalidCredentials,
    User,
    authenticate,
    create_user,
    hash_password,
    issue_session,
    normalise_email,
    session_expires_at,
    user_from_session,
)
from smart_extract.config import settings
from smart_extract.extraction.llm import LLMError
from smart_extract.intake import IntakeError
from smart_extract.query.nl2cypher import QueryError
from smart_extract.query.retrieve import RetrievalError
from smart_extract.graph.store import open_store

app = FastAPI(
    title="Smart Data Extraction API",
    description="Ingest academic papers and query the knowledge graph in English.",
    version="0.1.0",
)

# Explicit origins are required because authenticated requests carry cookies.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
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
    page: int | None = None


class SearchResponse(BaseModel):
    query: str
    answer: str
    chunks: list[ChunkHit]


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: str
    email: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str
    user: UserResponse


class CreateUserRequest(BaseModel):
    email: str
    password: str
    role: str = "tester"


class AdminUserResponse(UserResponse):
    active: bool


class PasswordRequest(BaseModel):
    password: str


class UserActiveRequest(BaseModel):
    active: bool


def require_user(request: Request) -> User:
    """Resolve an HttpOnly session cookie (or Bearer token for API clients)."""
    token = request.cookies.get(settings.auth_cookie_name)
    authorization = request.headers.get("authorization", "")
    if not token and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        raise HTTPException(
            status_code=401, detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return user_from_session(token)
    except (InvalidCredentials, AuthConfigurationError) as exc:
        raise HTTPException(
            status_code=401, detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required.")
    return user


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.auth_token_ttl_minutes * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


def _register_tester(req: LoginRequest) -> tuple[User, str]:
    if not settings.registration_enabled:
        raise HTTPException(status_code=403, detail="Account registration is disabled.")
    try:
        user = create_user(req.email, req.password, "tester")
        token = issue_session(user)
    except AuthConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return user, token


@app.post("/auth/login", response_model=UserResponse)
def login(req: LoginRequest, response: Response) -> UserResponse:
    try:
        user = authenticate(req.email, req.password)
        token = issue_session(user)
    except InvalidCredentials as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except AuthConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _set_session_cookie(response, token)
    return UserResponse(id=user.id, email=user.email, role=user.role)


@app.post("/auth/register", response_model=UserResponse, status_code=201)
def register(req: LoginRequest, response: Response) -> UserResponse:
    """Create a normal workspace account and sign in the browser."""
    user, token = _register_tester(req)
    _set_session_cookie(response, token)
    return UserResponse(id=user.id, email=user.email, role=user.role)


@app.post("/auth/token", response_model=TokenResponse)
def token_login(req: LoginRequest) -> TokenResponse:
    """Issue a bearer token for non-browser clients such as the remote CLI."""
    try:
        user = authenticate(req.email, req.password)
        token = issue_session(user)
    except InvalidCredentials as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except AuthConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return TokenResponse(
        access_token=token,
        expires_at=session_expires_at(token).isoformat(),
        user=UserResponse(id=user.id, email=user.email, role=user.role),
    )


@app.post("/auth/register/token", response_model=TokenResponse, status_code=201)
def token_register(req: LoginRequest) -> TokenResponse:
    """Create a normal workspace account and sign in the remote CLI."""
    user, token = _register_tester(req)
    return TokenResponse(
        access_token=token,
        expires_at=session_expires_at(token).isoformat(),
        user=UserResponse(id=user.id, email=user.email, role=user.role),
    )


@app.post("/auth/logout", status_code=204)
def logout(response: Response) -> None:
    response.delete_cookie(
        settings.auth_cookie_name,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )


@app.get("/auth/me", response_model=UserResponse)
def me(user: User = Depends(require_user)) -> UserResponse:
    return UserResponse(id=user.id, email=user.email, role=user.role)


@app.get("/admin/users", response_model=list[AdminUserResponse])
def list_users(_admin: User = Depends(require_admin)) -> list[AdminUserResponse]:
    with open_store() as store:
        rows = store.list_users()
    return [AdminUserResponse(**row) for row in rows]


@app.post("/admin/users", response_model=UserResponse, status_code=201)
def add_user(
    req: CreateUserRequest, _admin: User = Depends(require_admin)
) -> UserResponse:
    try:
        user = create_user(req.email, req.password, req.role)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UserResponse(id=user.id, email=user.email, role=user.role)


@app.post("/admin/users/{email}/claim")
def claim_user_papers(
    email: str, _admin: User = Depends(require_admin)
) -> dict[str, int]:
    try:
        email = normalise_email(email)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with open_store() as store:
        row = store.get_user_by_email(email)
        if not row:
            raise HTTPException(status_code=404, detail=f"No account exists for {email}.")
        claimed = store.claim_unowned_papers(str(row["id"]))
    return {"claimed": claimed}


@app.put("/admin/users/{email}/password")
def reset_user_password(
    email: str,
    req: PasswordRequest,
    _admin: User = Depends(require_admin),
) -> dict[str, str]:
    try:
        email = normalise_email(email)
        password_hash = hash_password(req.password)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with open_store() as store:
        changed = store.update_user_password(email, password_hash)
    if not changed:
        raise HTTPException(status_code=404, detail=f"No account exists for {email}.")
    return {"email": email}


@app.patch("/admin/users/{email}")
def set_user_active(
    email: str,
    req: UserActiveRequest,
    admin: User = Depends(require_admin),
) -> dict[str, object]:
    try:
        email = normalise_email(email)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if email == admin.email and not req.active:
        raise HTTPException(status_code=400, detail="You cannot disable your own account.")
    with open_store() as store:
        changed = store.set_user_active(email, req.active)
    if not changed:
        raise HTTPException(status_code=404, detail=f"No account exists for {email}.")
    return {"email": email, "active": req.active}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/stats")
def stats(user: User = Depends(require_user)) -> dict[str, int]:
    try:
        return service.graph_summary(owner_id=user.id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Graph unavailable: {exc}")


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, user: User = Depends(require_user)) -> AskResponse:
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty.")
    try:
        result = service.answer_question(question, owner_id=user.id)
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
def search(
    req: SearchRequest, user: User = Depends(require_user)
) -> SearchResponse:
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query must not be empty.")
    try:
        result = service.search_content(
            query, k=max(1, min(req.k, 20)), owner_id=user.id
        )
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
                page=c.page,
            )
            for c in result.chunks
        ],
    )


class GoldSaveRequest(BaseModel):
    title: str
    fields: dict[str, list[str]]


@app.get("/gold")
def gold_list(_admin: User = Depends(require_admin)) -> list[dict]:
    """List every gold file with labelling status (research tool, admin only)."""
    return service_gold.list_gold()


@app.get("/gold/{arxiv_id}")
def gold_get(arxiv_id: str, _admin: User = Depends(require_admin)) -> dict:
    """Load one gold paper with source text and per-value grounding evidence."""
    try:
        return service_gold.load_gold(arxiv_id)
    except GoldError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.put("/gold/{arxiv_id}")
def gold_save(
    arxiv_id: str,
    req: GoldSaveRequest,
    _admin: User = Depends(require_admin),
) -> dict:
    """Persist a hand-corrected paper (strips the template marker)."""
    try:
        return service_gold.save_gold(arxiv_id, req.title, req.fields)
    except GoldError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/ingest")
async def ingest(
    file: UploadFile = File(...), user: User = Depends(require_user)
) -> dict:
    """Ingest an uploaded paper (PDF or image) into the graph."""
    suffix = Path(file.filename or "upload").suffix or ".pdf"
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = Path(tmp.name)
            total = 0
            limit = settings.max_upload_mb * 1024 * 1024
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > limit:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds the {settings.max_upload_mb} MB upload limit.",
                    )
                tmp.write(chunk)
        return await run_in_threadpool(
            service.ingest_paper,
            tmp_path,
            user.id,
            file.filename,
        )
    except IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"LLM error: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        await file.close()
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()


# --- Serve the built React dashboard (production single-origin deployment) ---
#
# In dev the frontend runs on its own Vite server and proxies /api -> here, so
# this block does nothing (no build dir). In production the Docker image builds
# the frontend into ``frontend/dist`` and this mount serves it from the SAME
# origin as the API — so cookies "just work" with no cross-origin CORS setup.
#
# It is added LAST, so every API route above still matches first. Unknown paths
# fall back to index.html (client-side routing), EXCEPT anything that looks like
# an API/doc path, which is left to 404 as JSON rather than returning HTML.
def _mount_frontend() -> None:
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    dist = settings.frontend_dist_path
    if not (dist / "index.html").exists():
        return  # no build present (e.g. local dev) — leave the API bare

    # Hashed asset files (JS/CSS) are served from /assets by the Vite build.
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    index = dist / "index.html"
    _non_spa = ("/auth", "/admin", "/gold", "/ask", "/search", "/ingest",
                "/stats", "/health", "/docs", "/openapi.json", "/redoc")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        # Do not swallow real API 404s into the HTML shell.
        if any(("/" + full_path).startswith(p) for p in _non_spa):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)


_mount_frontend()
