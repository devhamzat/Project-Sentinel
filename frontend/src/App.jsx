import { useState } from "react";
import Dashboard from "./pages/Dashboard.jsx";
import Ask from "./pages/Ask.jsx";
import Ingest from "./pages/Ingest.jsx";
import Settings from "./pages/Settings.jsx";
import { useTheme } from "./useTheme.js";

const TABS = [
  { id: "dashboard", label: "dashboard" },
  { id: "ask", label: "ask" },
  { id: "ingest", label: "ingest" },
  { id: "settings", label: "settings" },
];

export default function App() {
  const [tab, setTab] = useState("dashboard");
  const [theme, setTheme] = useTheme();
  const [ingestTick, setIngestTick] = useState(0);
  const bumpStats = () => setIngestTick((n) => n + 1);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">$</span> sentinel
        </div>
        <nav className="tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`tab ${tab === t.id ? "active" : ""}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">hybrid nlp + llm · neo4j</div>
      </aside>

      <main className="content">
        {tab === "dashboard" && <Dashboard key={ingestTick} />}
        {tab === "ask" && <Ask onIngested={bumpStats} />}
        {tab === "ingest" && <Ingest onIngested={bumpStats} />}
        {tab === "settings" && <Settings theme={theme} setTheme={setTheme} />}
      </main>
    </div>
  );
}
