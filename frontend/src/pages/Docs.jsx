const SECTIONS = [
  {
    id: "overview",
    title: "Overview",
    content: (
      <>
        <p>
          Sentinel is a hybrid NLP + LLM system that extracts structured entities
          and relationships from academic research papers and stores them in a
          queryable Neo4j knowledge graph.
        </p>
        <p>
          Papers come in as born-digital PDFs or photographed/scanned images. The
          system extracts bibliographic metadata, content entities, dataset usage
          relationships, and a summary — then lets you ask questions in plain
          English.
        </p>
        <div className="docs-pipeline">
          <div className="pipeline-step">
            <span className="pipeline-label">Input</span>
            <span className="pipeline-value">PDF or Image</span>
          </div>
          <span className="pipeline-arrow">→</span>
          <div className="pipeline-step">
            <span className="pipeline-label">Extract</span>
            <span className="pipeline-value">NLP + LLM</span>
          </div>
          <span className="pipeline-arrow">→</span>
          <div className="pipeline-step">
            <span className="pipeline-label">Store</span>
            <span className="pipeline-value">Neo4j Graph</span>
          </div>
          <span className="pipeline-arrow">→</span>
          <div className="pipeline-step">
            <span className="pipeline-label">Query</span>
            <span className="pipeline-value">Plain English</span>
          </div>
        </div>
      </>
    ),
  },
  {
    id: "ingest",
    title: "Ingesting Papers",
    content: (
      <>
        <p>
          Navigate to the <strong>Ingest</strong> tab and drop a file or click to
          browse. Two intake lanes are supported:
        </p>
        <div className="docs-table-wrap">
          <table className="result-table">
            <thead>
              <tr>
                <th>Lane</th>
                <th>File types</th>
                <th>How it works</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><code>pdf</code></td>
                <td>.pdf</td>
                <td>Text layer extracted directly with PyMuPDF — no OCR.</td>
              </tr>
              <tr>
                <td><code>image</code></td>
                <td>.png · .jpg · .jpeg</td>
                <td>OpenCV preprocessing → Tesseract OCR → text.</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p>
          After ingestion the page shows the paper title, which lane was used, and
          counts of extracted authors, datasets, and keywords. The dashboard
          counters update automatically.
        </p>
        <div className="docs-note">
          Re-ingesting the same paper is safe — the graph uses <code>MERGE</code>,
          so no duplicate nodes are created.
        </div>
      </>
    ),
  },
  {
    id: "ask",
    title: "Asking Questions",
    content: (
      <>
        <p>
          The <strong>Ask</strong> tab accepts natural-language questions. An LLM
          translates your question into a Cypher query, runs it against the graph,
          and returns the results along with a plain-English answer.
        </p>
        <div className="docs-table-wrap">
          <table className="result-table">
            <thead>
              <tr><th>Example question</th><th>What it returns</th></tr>
            </thead>
            <tbody>
              <tr><td>Which papers use the SQuAD dataset?</td><td>Paper titles with a USES→Dataset edge</td></tr>
              <tr><td>What datasets are used most often?</td><td>Datasets ranked by how many papers use them</td></tr>
              <tr><td>Which author has the most papers?</td><td>Author name with the highest paper count</td></tr>
              <tr><td>Which papers use the same dataset as a given paper?</td><td>Papers sharing a dataset (a multi-hop traversal)</td></tr>
              <tr><td>List all papers and their publication year.</td><td>Every Paper node with its year</td></tr>
            </tbody>
          </table>
        </div>
        <p>
          You can also ingest a paper directly from the Ask tab by clicking the
          paperclip icon — the result appears inline in the conversation.
          Chat history is saved in your browser and restored on reload.
        </p>
      </>
    ),
  },
  {
    id: "graph",
    title: "Knowledge Graph Schema",
    content: (
      <>
        <p>Five node types and four relationship types make up the graph.</p>
        <div className="docs-table-wrap">
          <table className="result-table">
            <thead>
              <tr><th>Node</th><th>Key properties</th></tr>
            </thead>
            <tbody>
              <tr><td><code>Paper</code></td><td>title, year, summary, arxiv_id</td></tr>
              <tr><td><code>Author</code></td><td>name</td></tr>
              <tr><td><code>Affiliation</code></td><td>name</td></tr>
              <tr><td><code>Dataset</code></td><td>name</td></tr>
              <tr><td><code>Keyword</code></td><td>term</td></tr>
            </tbody>
          </table>
        </div>
        <div className="docs-table-wrap" style={{ marginTop: "1rem" }}>
          <table className="result-table">
            <thead>
              <tr><th>Relationship</th><th>Meaning</th></tr>
            </thead>
            <tbody>
              <tr><td><code>AUTHORED_BY</code></td><td>Paper → Author</td></tr>
              <tr><td><code>AFFILIATED_WITH</code></td><td>Author → Affiliation</td></tr>
              <tr><td><code>HAS_KEYWORD</code></td><td>Paper → Keyword</td></tr>
              <tr><td><code>USES</code></td><td>Paper → Dataset (the core contribution)</td></tr>
            </tbody>
          </table>
        </div>
        <div className="docs-note">
          The <code>USES</code> relationship is the central contribution of this
          project — it captures which datasets a paper actually uses, extracted by
          the LLM from the full paper text.
        </div>
      </>
    ),
  },
  {
    id: "scope",
    title: "Scope & Limitations",
    content: (
      <>
        <p>
          Sentinel is deliberately focused. Knowing what it does <em>not</em> do
          helps set expectations when a question returns nothing.
        </p>
        <div className="docs-table-wrap">
          <table className="result-table">
            <thead>
              <tr><th>In scope</th><th>Out of scope</th></tr>
            </thead>
            <tbody>
              <tr>
                <td>English academic papers (computer science, arXiv cs.CL)</td>
                <td>Other document types, other fields, non-English papers</td>
              </tr>
              <tr>
                <td>The fixed entity set and the <code>USES</code> relation</td>
                <td>Open-ended extraction of arbitrary facts or relationships</td>
              </tr>
              <tr>
                <td>Questions answerable from the graph's contents</td>
                <td>General world-knowledge questions (e.g. current events)</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div className="docs-note">
          Questions are answered <strong>only</strong> from what is in the graph.
          If you ask something the graph cannot answer — an unknown dataset, or a
          topic outside the ingested papers — you will get an empty result rather
          than a guessed answer. This is intentional: the system does not invent
          facts that are not in your corpus.
        </div>
      </>
    ),
  },
  {
    id: "api",
    title: "REST API Reference",
    content: (
      <>
        <p>
          The FastAPI backend runs on <code>http://localhost:8000</code>. All
          endpoints are also proxied through the dashboard at <code>/api/…</code>.
        </p>
        <div className="docs-table-wrap">
          <table className="result-table">
            <thead>
              <tr><th>Method</th><th>Path</th><th>Description</th></tr>
            </thead>
            <tbody>
              <tr>
                <td><span className="http-badge get">GET</span></td>
                <td><code>/stats</code></td>
                <td>Node and relationship counts from the graph.</td>
              </tr>
              <tr>
                <td><span className="http-badge post">POST</span></td>
                <td><code>/ingest</code></td>
                <td>Upload a file (multipart). Returns title, lane, and entity counts.</td>
              </tr>
              <tr>
                <td><span className="http-badge post">POST</span></td>
                <td><code>/ask</code></td>
                <td>JSON body <code>{"{ question }"}</code>. Returns answer + rows array.</td>
              </tr>
              <tr>
                <td><span className="http-badge get">GET</span></td>
                <td><code>/health</code></td>
                <td>Liveness check — returns <code>{"{ status: ok }"}</code>.</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p style={{ marginTop: "1rem" }}>Full interactive docs are available at <code>http://localhost:8000/docs</code> (Swagger UI) when the backend is running.</p>
      </>
    ),
  },
  {
    id: "stack",
    title: "Tech Stack",
    content: (
      <>
        <div className="docs-table-wrap">
          <table className="result-table">
            <thead>
              <tr><th>Layer</th><th>Technology</th></tr>
            </thead>
            <tbody>
              <tr><td>PDF extraction</td><td>PyMuPDF / pdfplumber</td></tr>
              <tr><td>OCR</td><td>OpenCV + Tesseract (pytesseract)</td></tr>
              <tr><td>NLP / NER</td><td>spaCy · en_core_web_sm</td></tr>
              <tr><td>LLM</td><td>OpenAI-compatible endpoint (Groq / Ollama)</td></tr>
              <tr><td>Knowledge graph</td><td>Neo4j · Cypher</td></tr>
              <tr><td>Backend / API</td><td>FastAPI · uvicorn</td></tr>
              <tr><td>Dashboard</td><td>React · Vite</td></tr>
              <tr><td>CLI</td><td>Python (argparse)</td></tr>
            </tbody>
          </table>
        </div>
      </>
    ),
  },
];

export default function Docs() {
  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Documentation</h1>
        <p className="page-desc">How to use Sentinel and how it works.</p>
      </div>

      <nav className="docs-nav">
        {SECTIONS.map((s) => (
          <a key={s.id} href={`#${s.id}`} className="docs-nav-link">
            {s.title}
          </a>
        ))}
      </nav>

      <div className="docs-body">
        {SECTIONS.map((s) => (
          <section key={s.id} id={s.id} className="docs-section">
            <h2 className="docs-section-title">{s.title}</h2>
            <div className="docs-content">{s.content}</div>
          </section>
        ))}
      </div>
    </div>
  );
}
