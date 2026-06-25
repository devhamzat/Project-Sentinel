import { THEMES } from "../useTheme.js";

const THEME_META = {
  light: { name: "Light",    desc: "Clean white"    },
  dark:  { name: "Dark",     desc: "Deep slate"     },
  mono:  { name: "Mono",     desc: "Grayscale only" },
};

function ThemePreview({ theme }) {
  return (
    <div className={`theme-preview theme-preview-${theme}`}>
      <div className="theme-preview-bar" />
      <div className="theme-preview-body">
        <div className="theme-preview-sidebar" />
        <div className="theme-preview-content" />
      </div>
    </div>
  );
}

export default function Settings({ theme, setTheme }) {
  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Settings</h1>
        <p className="page-desc">Appearance and display preferences.</p>
      </div>

      <div className="settings-section">
        <div className="settings-title">Theme</div>
        <div className="theme-grid">
          {THEMES.map((t) => (
            <button
              key={t}
              className={`theme-opt ${theme === t ? "active" : ""}`}
              onClick={() => setTheme(t)}
            >
              <ThemePreview theme={t} />
              <span className="theme-name">{THEME_META[t].name}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="divider" />

      <div className="settings-section">
        <div className="settings-title">About</div>
        <div className="kv-list">
          <div className="kv-row">
            <span className="kv-key">Project</span>
            <span style={{ fontSize: "0.8rem", color: "var(--soft)" }}>Smart Data Extraction for Unstructured Data</span>
          </div>
          <div className="kv-row">
            <span className="kv-key">Stack</span>
            <span style={{ fontSize: "0.8rem", color: "var(--soft)" }}>spaCy · LLM · Neo4j · FastAPI · React</span>
          </div>
          <div className="kv-row">
            <span className="kv-key">Version</span>
            <span className="kv-key-mono" style={{ fontSize: "0.78rem" }}>v0.1.0</span>
          </div>
        </div>
      </div>
    </div>
  );
}
