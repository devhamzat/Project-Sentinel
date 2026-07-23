# CLI Transcript — Real Runs for Chapter 4

These are **genuine, unedited outputs** of the `sentinel` remote CLI against the
running Project Sentinel API (FastAPI backend + Neo4j graph), captured on
2026-07-23. They demonstrate the third interface (alongside the REST API and the
React dashboard) driving the same backend pipeline. Nothing here is fabricated;
you can reproduce any of it by running the same command against a live API with
a logged-in session.

> To turn these into image figures for the thesis, run the same commands in your
> own terminal and screenshot them — the text below is the ground truth of what
> they produce.

---

## 1. `sentinel --help` — the command surface

```text
$ sentinel --help
usage: sentinel [-h]
                {login,register,logout,whoami,ingest,ask,search,stats,users} ...

Remote client for a deployed Project Sentinel API.

positional arguments:
  {login,register,logout,whoami,ingest,ask,search,stats,users}
    login               start a secure remote CLI session
    register            create a tester account and sign in
    logout              remove the active remote session
    whoami              verify and show the active remote account
    ingest              upload a PDF or photo for ingestion
    ask                 ask a natural-language graph question
    search              find passages by meaning
    stats               show active-workspace counts
    users               manage deployment accounts (admin only)
```

## 2. `sentinel whoami` — authenticated session

```text
$ sentinel whoami
Email:   haemisce@gmail.com
Role:    admin
API:     http://127.0.0.1:8000
Expires: 2026-07-23 13:28 W. Central Africa Standard Time
```

## 3. `sentinel stats` — knowledge-graph contents

```text
$ sentinel stats
  Paper            60
  Author           238
  Affiliation      122
  Keyword          394
  Dataset          114
  AUTHORED_BY      245
  AFFILIATED_WITH  511
  HAS_KEYWORD      421
  USES             116
```

This shows the populated graph: 60 papers, 238 authors, 122 affiliations, 114
datasets, and 116 `USES` edges — the project's central relationship. (Stats
captured after re-ingesting the corpus to backfill affiliations — see the note
at the end of this file.)

## 4. `sentinel ingest` — the extraction pipeline end to end

```text
$ sentinel ingest data/raw/2606.18237v1.pdf
Read digital source (id: 2606.18237).
  title:    ReproRepo: Scaling Reproducibility Audits with GitHub Repository Issues
  authors:  8   affiliations: 2
  keywords: 7   datasets: 0 (USES)   methods: 4
  filtered datasets: ['1,149 recent machine learning papers from major conferences']
  indexed 68 passage(s) for semantic search.
OK - stored Paper 'ReproRepo: Scaling Reproducibility Audits with GitHub Repository Issues' with 8 author(s), 0 dataset(s).
```

One command runs the whole pipeline: read the digital PDF text layer → hybrid
extraction (bibliographic + LLM-interpretive fields) → light validation (note
the malformed candidate dataset was *filtered* out rather than stored) → write
to the Neo4j graph → chunk-and-embed the body (68 passages) for semantic search.

## 5. `sentinel ask` — natural language → Cypher (the working path)

```text
$ sentinel ask "How many papers are in the knowledge base?"
The knowledge base contains 60 papers.

Cypher: MATCH (w:Workspace {id: $user_id})-[:OWNS]->(p:Paper) RETURN count(p) AS papers

  papers=60

1 row(s).
```

```text
$ sentinel ask "Which papers use the MMLU dataset?"
The paper "Holistic Data Scheduler for LLM Pre-training via Multi-Objective Reinforcement Learning" uses the MMLU dataset.

Cypher: MATCH (w:Workspace {id: $user_id})-[:OWNS]->(p:Paper)-[:USES]->(d:Dataset) WHERE toLower(d.name) CONTAINS 'mmlu' RETURN p.title AS paper

  paper=Holistic Data Scheduler for LLM Pre-training via Multi-Objective Reinforcement Learning

1 row(s).
```

The LLM translates plain English into Cypher against the fixed schema, runs it,
and returns both the answer and the query it generated (good for transparency in
the writeup). The second example correctly traverses the `USES` relationship.

## 6. `sentinel ask` — an HONEST limitation (keep this for the discussion)

Not every question yields correct Cypher. This real run shows the LLM producing
an **invalid property access** (`p.AUTHORED_BY.name`) instead of traversing the
`AUTHORED_BY` relationship, so it returns no author:

```text
$ sentinel ask "Who are the authors of the ReproRepo paper?"
The graph contains nothing matching the authors of the ReproRepo paper.

Cypher: MATCH (w:Workspace {id: $user_id})-[:OWNS]->(p:Paper) WHERE toLower(p.title) CONTAINS 'reprorepo' RETURN p.AUTHORED_BY.name AS author

  author=None

1 row(s).
```

This is worth reporting in Chapter 4's discussion of the NL→Cypher approach: a
small LLM sometimes mishandles relationship traversal, which is a known
limitation of LLM-generated queries and motivates future work (schema-aware
prompting, query validation, or a larger model).

## 7. `sentinel search` — semantic (GraphRAG) content retrieval

```text
$ sentinel search "how do these papers reduce hallucination in language models?"
These papers do not directly address how to reduce hallucination in language
models. However, they do suggest that static agents, which inspect only the
paper and repository snapshot without code execution, can recover a substantial
fraction of human-reported reproduction blockers with low false positive rates.

[0.700] ReproRepo: Scaling Reproducibility Audits with GitHub Repository Issues (arXiv 2606.18237) - passage #1
    ...the best agent in our study, namely Codex with GPT-5.5, surfaces at least
    one semantically related human-reported blocker for ~90% of papers...

[0.694] ReproRepo: ... - passage #28
    ...Experimental Results ... Table 3 compares the four models in our study...

[0.690] ReproRepo: ... - passage #34
    ...Adding the paper improves performance across all metrics, with the largest
    gains appearing under exact matching...
```

(Output abbreviated to three passages; the live command returns five.) Each hit
carries a cosine-similarity score, the source paper + arXiv id, and a passage
locator — and the model gives a **grounded answer that honestly says the corpus
does not directly cover the asked topic** rather than hallucinating one. This
complements `ask`: structured questions → `ask` (NL→Cypher), conceptual/content
questions → `search` (semantic retrieval).

---

## Notes for the writeup

- All commands run against the live API with a real logged-in admin session;
  `stats` confirms a populated 60-paper graph.
- The `ask` limitation in §6 is a **genuine result** — include it honestly as a
  limitation, do not filter it out.
- **Affiliations were backfilled (resolved).** During capture, affiliations were
  absent for papers ingested before affiliation-writing worked (graph showed
  `Affiliation = 0`). The corpus was then **re-ingested**, and because graph
  writes use `MERGE` (idempotent), this updated existing papers in place without
  duplication. Afterwards `Affiliation` rose to **122** and `AFFILIATED_WITH` to
  **511** — the stats in §3 above are the post-backfill figures.

- **Ingest reliability: 56 of 62 papers succeeded on re-ingest.** The 6 failures
  are genuine and worth reporting honestly in Chapter 4's limitations:
  - **1 paper** (`2606.24188`) exceeded the 25 MB upload limit — the
    `MAX_UPLOAD_MB` safety guard working as designed, not an extraction failure.
  - **5 papers** (`2606.24192`, `24259`, `24381`, `24773`, and one other) failed
    with Groq `json_validate_failed` (HTTP 400): the small model
    (`llama-3.1-8b-instant`) produced malformed or over-long JSON — e.g. echoing
    the paper text into the response, adding prose like "Here is the JSON…", or
    hitting the completion-token limit before closing the object. These are
    **permanent** errors (retry correctly does not waste attempts on them) and
    reflect the JSON-reliability limits of a small model. This reinforces the
    "larger model as future work" point and complements the NL→Cypher limitation
    in §6. The graph still holds all 60 papers; the failed ones were simply left
    unchanged.
