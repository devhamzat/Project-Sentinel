#!/usr/bin/env sh
# Production entrypoint: ensure the Neo4j schema exists, then serve the app.
#
# We create uniqueness constraints on boot so a FRESH database (e.g. a new
# AuraDB Free instance) enforces MERGE idempotency from the first ingest. If the
# database is briefly unreachable we WARN and start anyway rather than
# crash-looping — the API's own endpoints return clear 503s until Neo4j is up.
set -e

echo "[entrypoint] ensuring Neo4j constraints ..."
if python -c "from smart_extract.graph.store import open_store
with open_store() as s:
    s.ensure_constraints()
print('[entrypoint] constraints ensured.')"; then
    :
else
    echo "[entrypoint] WARNING: could not reach Neo4j to ensure constraints."
    echo "[entrypoint] Starting the API anyway; check NEO4J_URI / credentials."
fi

# Bind to the port the host injects (Fly/Render/Railway/etc.); default 8000.
PORT="${PORT:-8000}"
echo "[entrypoint] starting uvicorn on 0.0.0.0:${PORT} ..."
exec uvicorn smart_extract.api.main:app --host 0.0.0.0 --port "${PORT}"
