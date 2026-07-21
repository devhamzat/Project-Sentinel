import { useState } from "react";
import { search } from "../api.js";

function SearchIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="7" cy="7" r="4.5" />
      <line x1="10.5" y1="10.5" x2="14" y2="14" />
    </svg>
  );
}

function Hit({ hit }) {
  return (
    <div className="card" style={{ marginBottom: "0.75rem" }}>
      <div className="card-header">
        <span className="card-title">
          {hit.title || "(untitled paper)"}
          {hit.arxiv_id && (
            <span className="kv-key-mono" style={{ marginLeft: 8 }}>
              arXiv {hit.arxiv_id}
            </span>
          )}
        </span>
        <span className="kv-key-mono" title="cosine similarity">
          {hit.score.toFixed(3)}
        </span>
      </div>
      <div className="card-body">
        <p style={{ margin: 0, fontSize: "0.85rem", lineHeight: 1.55, whiteSpace: "pre-wrap" }}>
          {hit.text}
        </p>
        <p className="muted" style={{ fontSize: "0.75rem", margin: "0.5rem 0 0" }}>
          passage #{hit.chunk_index}
        </p>
      </div>
    </div>
  );
}

export default function Search() {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  async function submit(e) {
    e.preventDefault();
    const query = q.trim();
    if (!query || busy) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await search(query));
    } catch (err) {
      setResult(null);
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Search</h1>
        <p className="page-desc">
          Find passages by meaning across your ingested papers — no exact
          keywords needed. For structured questions (authors, counts), use Ask.
        </p>
      </div>

      <form onSubmit={submit} className="input-row" style={{ marginBottom: "1.25rem" }}>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="e.g. how do these papers reduce hallucination?"
          aria-label="semantic search query"
          disabled={busy}
        />
        <button type="submit" className="btn btn-primary" disabled={busy || !q.trim()}>
          {busy ? <span className="spinner" style={{ borderTopColor: "#fff" }} /> : <SearchIcon />}
          Search
        </button>
      </form>

      {error && (
        <div className="status-line error">
          <span>{error}</span>
        </div>
      )}

      {result && (
        <>
          {result.answer && <p className="answer">{result.answer}</p>}
          {result.chunks.length === 0 ? (
            <p className="muted" style={{ fontSize: "0.85rem" }}>
              No matching passages.
            </p>
          ) : (
            <div className="section">
              <div className="section-label">
                Passages ({result.chunks.length})
              </div>
              {result.chunks.map((hit, i) => (
                <Hit key={i} hit={hit} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
