import { useState } from "react";
import { THEMES } from "../useTheme.js";
import Docs from "./Docs.jsx";

const THEME_META = {
  watchtower: { name: "Watchtower", desc: "Graphite & amber" },
  light:      { name: "Light",      desc: "Clean white"      },
  dark:       { name: "Dark",       desc: "Deep slate"       },
  mono:       { name: "Mono",       desc: "Grayscale only"   },
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

function Appearance({ theme, setTheme, user, onLogout }) {
  return (
    <>
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
        <div className="settings-title">Account</div>
        <div className="kv-list">
          <div className="kv-row">
            <span className="kv-key">Signed in as</span>
            <span className="kv-key-mono">{user.email}</span>
          </div>
          <div className="kv-row">
            <span className="kv-key">Role</span>
            <span className="badge">{user.role}</span>
          </div>
        </div>
        <button className="btn btn-ghost" onClick={onLogout} style={{ marginTop: "0.8rem" }}>
          Sign out
        </button>
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
    </>
  );
}

const SETTING_TABS = [
  { id: "appearance", label: "Appearance" },
  { id: "docs",       label: "Docs"       },
];

export default function Settings({ theme, setTheme, user, onLogout }) {
  const [activeTab, setActiveTab] = useState("appearance");

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Settings</h1>
      </div>

      <div className="settings-tabs">
        {SETTING_TABS.map((t) => (
          <button
            key={t.id}
            className={`settings-tab ${activeTab === t.id ? "active" : ""}`}
            onClick={() => setActiveTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="settings-tab-body">
        {activeTab === "appearance" && (
          <Appearance theme={theme} setTheme={setTheme} user={user} onLogout={onLogout} />
        )}
        {activeTab === "docs"       && <Docs />}
      </div>
    </div>
  );
}
