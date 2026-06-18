"""Shared extraction prompts (CLAUDE.md §9).

Kept in one place so the Phase-0 spike and the real Phase-3 pipeline use the
*same* prompt. The schema here mirrors the Neo4j data model in CLAUDE.md §6.

Division of labour (the "hybrid reliability" principle, §4): deterministic NLP
handles predictable bibliographic fields; the LLM handles interpretive fields.
This prompt targets the LLM's share — content entities, the USES relation, and
the summary — but also returns title/authors so the spike can see end-to-end
output before the deterministic path exists.
"""

from __future__ import annotations

# System prompt: pins the model to faithful, schema-bound extraction.
EXTRACTION_SYSTEM = (
    "You are a precise information-extraction system for academic research "
    "papers in computer science. You extract only what the text supports. "
    "You never invent authors, datasets, or facts. When a field is absent, you "
    "return an empty list or empty string. You always respond with a single "
    "valid JSON object and nothing else."
)

# The JSON shape we ask for, mirroring CLAUDE.md §6.
#   Paper{title, year, summary}
#   Author{name}, Affiliation{name}, Dataset{name}, Keyword{term}
#   (:Paper)-[:USES]->(:Dataset)   <- the central relationship
_SCHEMA_BLOCK = """\
Return a JSON object with exactly these keys:

{
  "title": string,                 // the paper's title
  "year": integer | null,          // publication year if stated, else null
  "authors": [string, ...],        // author full names, in order
  "affiliations": [string, ...],   // distinct institutions named
  "keywords": [string, ...],       // 3-8 topical keywords/terms
  "datasets": [string, ...],       // named datasets the paper USES (empty if none)
  "methods": [string, ...],        // named methods/models/architectures used or proposed
  "metrics": [string, ...],        // named evaluation metrics reported (e.g. F1, BLEU, accuracy)
  "summary": string                // a 2-4 sentence plain-English summary
}

Rules:
- Use only information present in the provided text.
- "datasets" must list datasets the paper actually uses or evaluates on,
  not datasets merely cited in passing. Use the dataset's exact name as written.
- "methods" are named techniques/models (e.g. "BERT", "self-attention"), not
  generic phrases.
- "metrics" are named measures the paper reports results in.
- Do not include markdown, comments, or any text outside the JSON object.
"""


def extraction_prompt(paper_text: str, *, max_chars: int = 12000) -> str:
    """Build the user prompt for extracting structured fields from one paper.

    ``paper_text`` is truncated to ``max_chars`` to stay within context limits;
    the front matter (title, authors, abstract, intro) carries most of what we
    need, so leading text is preserved.
    """
    text = paper_text.strip()
    if len(text) > max_chars:
        text = text[:max_chars]
    return (
        f"{_SCHEMA_BLOCK}\n"
        "Extract the fields from the following paper text:\n\n"
        "-----BEGIN PAPER-----\n"
        f"{text}\n"
        "-----END PAPER-----"
    )
