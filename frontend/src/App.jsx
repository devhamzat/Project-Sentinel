import { useEffect, useState } from "react";
import { getStats, ask, ingest } from "./api.js";

const NODE_LABELS = ["Paper", "Author", "Affiliation", "Keyword", "Dataset"];
const REL_LABELS = ["AUTHORED_BY", "AFFILIATED_WITH", "HAS_KEYWORD", "USES"];

function StatsPanel({ stats, onRefresh }) {
  return (
    <section className="card">
      <div className="card-head">
        <h2>Knowledge graph</h2>
        <button onClick={onRefresh}>Refresh</button>
      </div>
      {stats ? (
        <div className="stats-grid">
          {NODE_LABELS.map((l) => (
            <div className="stat" key={l}>
              <span className="num">{stats[l] ?? 0}</span>
              <span className="lbl">{l}</span>
            </div>
          ))}
          {REL_LABELS.map((l) => (
            <div className="stat rel" key={l}>
              <span className="num">{stats[l] ?? 0}</span>
              <span className="lbl">{l}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">Loading… (is the API running on :8000?)</p>
      )}
    </section>
  );
}

function AskPanel() {
  const [q, setQ] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    if (!q.trim()) return;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      setResult(await ask(q.trim()));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const cols = result?.rows?.length ? Object.keys(result.rows[0]) : [];

  return (
    <section className="card">
      <h2>Ask a question</h2>
      <form onSubmit={submit} className="ask-form">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="e.g. Which papers use the SQuAD dataset?"
        />
        <button disabled={busy}>{busy ? "Thinking…" : "Ask"}</button>
      </form>
      {error && <p className="error">{error}</p>}
      {result && (
        <div className="result">
          {result.rows.length ? (
            <table>
              <thead>
                <tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr>
              </thead>
              <tbody>
                {result.rows.map((row, i) => (
                  <tr key={i}>
                    {cols.map((c) => <td key={c}>{String(row[c])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">No results.</p>
          )}
        </div>
      )}
    </section>
  );
}

function IngestPanel({ onIngested }) {
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  async function onFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setStatus(`Ingesting ${file.name}…`);
    try {
      const r = await ingest(file);
      const c = r.counts;
      setStatus(
        `Stored "${r.title}" (${r.source_kind} lane): ` +
          `${c.authors} authors, ${c.datasets} datasets, ${c.keywords} keywords.`
      );
      onIngested?.();
    } catch (err) {
      setStatus(`Failed: ${err.message}`);
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }

  return (
    <section className="card">
      <h2>Ingest a paper</h2>
      <p className="muted">Upload a born-digital PDF or a page photo (PNG/JPG).</p>
      <input type="file" accept=".pdf,.png,.jpg,.jpeg" onChange={onFile} disabled={busy} />
      {status && <p className={status.startsWith("Failed") ? "error" : "ok"}>{status}</p>}
    </section>
  );
}

export default function App() {
  const [stats, setStats] = useState(null);

  function refresh() {
    getStats().then(setStats).catch(() => setStats(null));
  }
  useEffect(refresh, []);

  return (
    <div className="app">
      <header>
        <h1>Smart Data Extraction</h1>
        <p className="muted">
          A hybrid NLP + LLM knowledge graph over academic papers.
        </p>
      </header>
      <StatsPanel stats={stats} onRefresh={refresh} />
      <AskPanel />
      <IngestPanel onIngested={refresh} />
    </div>
  );
}
