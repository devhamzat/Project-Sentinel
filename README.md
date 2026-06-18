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
python -m spacy download en_core_web_sm
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

## Ingesting papers

```bash
smart-extract ingest data/raw/2606.18246v1.pdf     # digital lane (PDF text layer)
smart-extract ingest data/photo/2606.18246v1_p1.png  # photo lane (OpenCV + Tesseract OCR)
```

The OCR lane needs the Tesseract engine installed (Windows: UB-Mannheim build,
incl. the English language data). Set `TESSERACT_CMD` in `.env` only if it is
not at the default `C:\Program Files\Tesseract-OCR\`.
