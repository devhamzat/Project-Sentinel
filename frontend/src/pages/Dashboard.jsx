import { useEffect, useState } from "react";
import { getStats } from "../api.js";

const NODES = [
  { key: "Paper",       label: "Papers"      },
  { key: "Author",      label: "Authors"     },
  { key: "Affiliation", label: "Affiliations" },
  { key: "Keyword",     label: "Keywords"    },
  { key: "Dataset",     label: "Datasets"    },
];

const RELS = [
  { key: "AUTHORED_BY",    label: "Authored by"    },
  { key: "AFFILIATED_WITH",label: "Affiliated with" },
  { key: "HAS_KEYWORD",    label: "Has keyword"    },
  { key: "USES",           label: "Uses dataset"   },
];

function RefreshIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M13.5 8A5.5 5.5 0 1 1 10 3.07" />
      <polyline points="10 1 10 4 13 4" />
    </svg>
  );
}

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  function refresh() {
    setLoading(true);
    getStats()
      .then((s) => { setStats(s); setLoading(false); })
      .catch(() => { setStats(null); setLoading(false); });
  }

  useEffect(refresh, []);

  const totalNodes = stats
    ? NODES.reduce((s, n) => s + (stats[n.key] ?? 0), 0)
    : null;

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Knowledge Graph</h1>
        <p className="page-desc">Live counts from your Neo4j instance.</p>
      </div>

      {loading && (
        <div className="section">
          <div className="stats-grid" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
            {[0,1,2].map(i => (
              <div className="stat-cell" key={i}>
                <div className="shimmer" style={{ width: "50%", marginBottom: 8 }} />
                <div className="shimmer" style={{ width: "35%", height: "1.6em" }} />
              </div>
            ))}
          </div>
        </div>
      )}

      {!loading && !stats && (
        <div className="status-line error">
          <span>Cannot reach the API on :8000 — is the backend running?</span>
        </div>
      )}

      {!loading && stats && (
        <>
          <div className="section">
            <div className="section-label">Nodes</div>
            <div className="stats-grid">
              {NODES.map(({ key, label }) => (
                <div className="stat-cell" key={key}>
                  <span className="stat-label">{label}</span>
                  <span className="stat-value accent">{stats[key] ?? 0}</span>
                </div>
              ))}
              <div className="stat-cell" key="total">
                <span className="stat-label">Total nodes</span>
                <span className="stat-value">{totalNodes}</span>
              </div>
            </div>
          </div>

          <div className="section">
            <div className="section-label">Relationships</div>
            <div className="kv-list">
              {RELS.map(({ key, label }) => (
                <div className="kv-row" key={key}>
                  <span className="kv-key">
                    {label}
                    <span className="kv-key-mono">{key}</span>
                  </span>
                  <span className="kv-val">{stats[key] ?? 0}</span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      <button
        className="btn btn-ghost"
        onClick={refresh}
        style={{ marginTop: "0.5rem" }}
      >
        <RefreshIcon /> Refresh
      </button>
    </div>
  );
}
