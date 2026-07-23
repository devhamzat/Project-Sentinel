# Production image for Project Sentinel — a single container that serves BOTH
# the FastAPI backend and the built React dashboard from one origin (so cookies
# work with no cross-origin CORS setup). Host-agnostic: run it on any container
# host (Fly, Render, Railway, a VM). Neo4j is external (e.g. AuraDB Free) and
# configured via environment variables — it is NOT part of this image.
#
# Build:  docker build -t sentinel .
# Run:    docker run -p 8000:8000 --env-file .env sentinel
#
# See docs/deployment.md for the full env checklist and free-tier notes.

# ---- Stage 1: build the React frontend -> static files ----------------------
FROM node:20-slim AS frontend
WORKDIR /app/frontend

# Install deps first (better layer caching) then build.
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
# Same-origin production: the API serves these files, so the base is "" and the
# frontend calls /auth/login, /stats, ... directly (no /api prefix, no proxy).
ENV VITE_API_BASE=""
RUN npm run build          # outputs to /app/frontend/dist

# ---- Stage 2: python runtime ------------------------------------------------
FROM python:3.11-slim AS runtime

# System deps: Tesseract for the OCR lane; libGL/glib for opencv-python-headless.
# tesseract-ocr-eng is the English language data the image lane needs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install Python deps first (layer caching), then the spaCy model, then code.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m spacy download en_core_web_sm

# App source + packaging metadata, installed as a package (console script etc.).
COPY pyproject.toml README.md ./
COPY smart_extract/ ./smart_extract/
RUN pip install --no-cache-dir --no-deps -e .

# Bring in the built frontend from stage 1; the API serves it from here.
COPY --from=frontend /app/frontend/dist ./frontend/dist

COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

# Most hosts inject $PORT; default to 8000 for local runs. Entrypoint honours it.
ENV PORT=8000
EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
