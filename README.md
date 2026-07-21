# Project Sentinel — Smart Data Extraction for Unstructured Data

A hybrid NLP + Large Language Model system that extracts structured entities and
relationships from academic research papers and stores them in a queryable Neo4j
knowledge graph.

See `CLAUDE.md` for the full project context, design decisions, and build plan.

## Quick start

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows
pip install -e .[dev]
python -m spacy download en_core_web_sm   # NER validator for the hybrid path
cp .env.example .env              # then fill in Neo4j + LLM settings
```

## Neo4j (Docker)

```bash
docker compose up -d              # start Neo4j (bolt :7687, browser :7474)
python -m smart_extract.scripts.check_neo4j   # verify the connection
docker compose down               # stop (data kept); add -v to wipe the graph
```

Login at http://localhost:7474 with the user/password from `.env`
(defaults: `neo4j` / `changeme`).

## Scripts

```bash
python -m smart_extract.scripts.check_neo4j      # verify Neo4j connection
python -m smart_extract.scripts.download_arxiv   # download & freeze cs.CL corpus
python -m smart_extract.scripts.spike            # test LLM extraction on one paper
python -m smart_extract.scripts.make_photos      # make photographed copies (OCR eval)
pytest -q                                        # smoke + lane tests
```

## Remote CLI

The CLI is an HTTPS client. It does not need Neo4j, LLM, OCR, or server
credentials on the user's computer. For a Cloudflare-protected deployment,
install `cloudflared` and sign in once:

```bash
sentinel login you@example.com --api-url https://sentinel.example.com/api
sentinel ingest data/raw/2606.18246v1.pdf
sentinel ingest data/photo/2606.18246v1_p1.png
sentinel ask "Which papers use the SQuAD dataset?"
sentinel search "transformer evaluation" -k 5
sentinel stats
sentinel whoami
sentinel logout
```

For non-local URLs, `sentinel login` automatically opens the browser for
Cloudflare Access and then prompts for the Sentinel password. Both expiring
tokens and the API URL are stored in the operating-system credential manager;
neither password is stored. Use `--no-cloudflare` only when the API is not
behind Access. Local development defaults to `http://127.0.0.1:8000`.

## Web app (REST API + React dashboard)

```bash
# Terminal 1 — Python REST API
uvicorn smart_extract.api.main:app --reload --port 8000   # docs at /docs

# Terminal 2 — React dashboard (presentation layer; talks only to the API)
cd frontend && npm install && npm run dev                 # http://localhost:5173
```

The dashboard proxies `/api/*` to the FastAPI backend. The React app and remote
CLI hold no business logic: both call FastAPI, which is the only public door to
the Python service layer (`smart_extract/service.py`).

## Authentication and test accounts

The web API is private by default. Accounts are invite-only and stored in
Neo4j; there is no public registration route. Before deployment, set a random
`AUTH_SECRET`, the exact `CORS_ALLOWED_ORIGINS`, and `AUTH_COOKIE_SECURE=true`
in the deployment environment.

Create the first administrator once from a trusted shell on the API host:

```bash
python -m smart_extract.scripts.bootstrap_admin you@example.com
```

Then all account management is remote and admin-only:

```bash
sentinel login you@example.com --api-url https://sentinel.example.com/api
sentinel users add supervisor@example.com --role tester
sentinel users list
sentinel users reset-password supervisor@example.com
sentinel users disable supervisor@example.com
```

Existing papers created before authentication have no owner. Assign them once:

```bash
sentinel users claim you@example.com
```

There is intentionally no remote first-admin bootstrap endpoint. Password
resets and account disabling invalidate Sentinel sessions immediately.
Account-management routes verify the admin role again on the server; the CLI's
local role check is only an early UX hint.

Browser sessions use a signed token in an HttpOnly, SameSite cookie. Every API
route except `/health`, `/auth/login`, and `/auth/token` requires a valid
session. `/auth/token` is the CLI bearer-token exchange and is expected to sit
behind Cloudflare Access in production. Dashboard counts, graph questions,
semantic search, ingestion ownership, and browser chat history are scoped to
the signed-in account.

## Cloudflare deployment boundary

Create a Cloudflare Access application for the Sentinel hostname, allow only
the exact tester emails, and map a Cloudflare Tunnel route to the reverse proxy
serving React plus FastAPI. The CLI sends Cloudflare's token in
`cf-access-token` and Sentinel's workspace token as `Authorization: Bearer ...`.
Neo4j remains private and is never contacted by the CLI.

## Evaluation (Chapter 4 numbers)

```bash
python -m smart_extract.scripts.make_gold_template --limit 20  # pre-fill templates
#   --> hand-correct each data/gold/<id>.json to the TRUE labels, delete _INSTRUCTIONS
python -m smart_extract.scripts.make_photos --pages 1          # photo copies for OCR eval
python -m smart_extract.scripts.evaluate --compare             # P/R/F1, digital vs photo
```

Numbers come from YOUR hand-labelled gold set — never fabricated.

The OCR lane needs the Tesseract engine installed (Windows: UB-Mannheim build,
incl. the English language data). Set `TESSERACT_CMD` in `.env` only if it is
not at the default `C:\Program Files\Tesseract-OCR\`.
