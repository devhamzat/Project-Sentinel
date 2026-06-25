import { useState } from "react";
import Dashboard from "./pages/Dashboard.jsx";
import Ask from "./pages/Ask.jsx";
import Ingest from "./pages/Ingest.jsx";
import Settings from "./pages/Settings.jsx";
import { useTheme } from "./useTheme.js";

function IconGraph() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6"
      strokeLinecap="round" strokeLinejoin="round" className="tab-icon">
      <circle cx="3" cy="8" r="1.5" />
      <circle cx="13" cy="3.5" r="1.5" />
      <circle cx="13" cy="12.5" r="1.5" />
      <line x1="4.4" y1="7.2" x2="11.6" y2="4.3" />
      <line x1="4.4" y1="8.8" x2="11.6" y2="11.7" />
    </svg>
  );
}

function IconAsk() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6"
      strokeLinecap="round" strokeLinejoin="round" className="tab-icon">
      <path d="M14 10.5a1.5 1.5 0 0 1-1.5 1.5H4.5L2 14.5v-11A1.5 1.5 0 0 1 3.5 2h9A1.5 1.5 0 0 1 14 3.5z" />
    </svg>
  );
}

function IconIngest() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6"
      strokeLinecap="round" strokeLinejoin="round" className="tab-icon">
      <path d="M9 2H4a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V6z" />
      <polyline points="9 2 9 6 13 6" />
      <line x1="8" y1="9" x2="8" y2="12.5" />
      <polyline points="6.25 10.75 8 9 9.75 10.75" />
    </svg>
  );
}

function IconSettings() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6"
      strokeLinecap="round" strokeLinejoin="round" className="tab-icon">
      <circle cx="8" cy="8" r="2" />
      <path d="M8 1v1.5M8 13.5V15M1 8h1.5M13.5 8H15M3.05 3.05l1.06 1.06M11.89 11.89l1.06 1.06M3.05 12.95l1.06-1.06M11.89 4.11l1.06-1.06" />
    </svg>
  );
}

const TABS = [
  { id: "dashboard", label: "Dashboard",  Icon: IconGraph    },
  { id: "ask",       label: "Ask",         Icon: IconAsk      },
  { id: "ingest",    label: "Ingest",      Icon: IconIngest   },
  { id: "settings",  label: "Settings",    Icon: IconSettings },
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
          <div className="brand-icon">
            <svg viewBox="0 0 16 16">
              <path d="M8 2L3 5v4l5 3 5-3V5z" />
              <line x1="8" y1="9" x2="8" y2="14" />
            </svg>
          </div>
          <div className="brand-text">
            <span className="brand-name">Sentinel</span>
            <span className="brand-sub">smart-extract v0.1</span>
          </div>
        </div>

        <nav className="sidebar-nav">
          <div className="nav-section-label">Navigation</div>
          {TABS.map(({ id, label, Icon }) => (
            <button
              key={id}
              className={`tab ${tab === id ? "active" : ""}`}
              onClick={() => setTab(id)}
            >
              <Icon />
              {label}
            </button>
          ))}
        </nav>

        <div className="sidebar-foot">
          hybrid nlp + llm<br />neo4j knowledge graph
        </div>
      </aside>

      <main className="content">
        {tab === "dashboard" && <Dashboard key={ingestTick} />}
        {tab === "ask"       && <Ask onIngested={bumpStats} />}
        {tab === "ingest"    && <Ingest onIngested={bumpStats} />}
        {tab === "settings"  && <Settings theme={theme} setTheme={setTheme} />}
      </main>
    </div>
  );
}
