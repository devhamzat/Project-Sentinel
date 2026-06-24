import { useEffect, useState } from "react";
import { getStats } from "../api.js";

const NODE_LABELS = ["Paper", "Author", "Affiliation", "Keyword", "Dataset"];
const REL_LABELS = ["AUTHORED_BY", "AFFILIATED_WITH", "HAS_KEYWORD", "USES"];

export default function Dashboard() {
  const [stats, setStats] = useState(null);

  function refresh() {
    getStats().then(setStats).catch(() => setStats(null));
  }
  useEffect(refresh, []);

  return (
    <section className="block">
      <h2>
        knowledge graph
        <button className="linkbtn" onClick={refresh}>refresh</button>
      </h2>
      {stats ? (
        <div className="kv">
          {NODE_LABELS.map((l) => (
            <div className="kv-row" key={l}>
              <span className="k">{l.toLowerCase()}</span>
              <span className="v">{stats[l] ?? 0}</span>
            </div>
          ))}
          {REL_LABELS.map((l) => (
            <div className="kv-row rel" key={l}>
              <span className="k">{l.toLowerCase()}</span>
              <span className="v">{stats[l] ?? 0}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">loading… (is the api running on :8000?)</p>
      )}
    </section>
  );
}
