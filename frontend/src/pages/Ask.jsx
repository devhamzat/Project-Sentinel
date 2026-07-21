import { useEffect, useRef, useState } from "react";
import { ask, search, ingest } from "../api.js";

const STORAGE_KEY = "sentinel-chat-history";
const MAX_STORED = 200;

const SUGGESTIONS = {
  ask: [
    "Which papers use BERT?",
    "Who are the most prolific authors?",
    "Which datasets appear in more than one paper?",
  ],
  search: [
    "How do these papers reduce hallucination?",
    "Methods for entity extraction",
    "Limitations the authors mention",
  ],
};

const MODES = {
  ask: {
    label: "Ask",
    placeholder: "Ask about papers, authors, datasets, or keywords…",
    desc: "Query the knowledge graph — authors, papers, counts.",
  },
  search: {
    label: "Search",
    placeholder: "Search passages by meaning…",
    desc: "Semantic search over ingested passages — no exact keywords needed.",
  },
};

let idSeq = 0;
const nextId = () => ++idSeq;

function loadHistory() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const msgs = JSON.parse(raw);
    // drop any pending messages left over from a crashed session
    return msgs.filter((m) => m.kind !== "pending");
  } catch {
    return [];
  }
}

function saveHistory(messages) {
  try {
    // only persist settled messages; cap to avoid blowing up storage
    const settled = messages.filter((m) => m.kind !== "pending");
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify(settled.slice(-MAX_STORED))
    );
  } catch {
    /* storage quota — silently ignore */
  }
}

function SendIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="14" y1="2" x2="2" y2="8" />
      <line x1="14" y1="2" x2="10" y2="14" />
      <line x1="2" y1="8" x2="10" y2="14" />
    </svg>
  );
}

function AskModeIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none"
      stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 10.5a1.5 1.5 0 0 1-1.5 1.5H4.5L2 14.5v-11A1.5 1.5 0 0 1 3.5 2h9A1.5 1.5 0 0 1 14 3.5z" />
    </svg>
  );
}

function SearchModeIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none"
      stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="7" cy="7" r="4.5" />
      <line x1="10.5" y1="10.5" x2="14" y2="14" />
    </svg>
  );
}

function ChevronIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 16 16" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="4 6 8 10 12 6" />
    </svg>
  );
}

function AttachIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M13.5 7.5l-6 6a4 4 0 0 1-5.66-5.66l6.5-6.5a2.5 2.5 0 0 1 3.54 3.54L5.36 11.4a1 1 0 0 1-1.42-1.42L9.5 4.5" />
    </svg>
  );
}

function ResultRows({ rows }) {
  if (!rows.length) {
    return <p className="muted" style={{ fontSize: "0.8rem", marginTop: "0.4rem" }}>Query ran — nothing matched.</p>;
  }
  const cols = Object.keys(rows[0]);
  return (
    <div style={{ marginTop: "0.6rem" }}>
      <table className="result-table">
        <thead>
          <tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>{cols.map((c) => <td key={c}>{String(row[c])}</td>)}</tr>
          ))}
        </tbody>
      </table>
      <p className="rowcount">{rows.length} row{rows.length !== 1 ? "s" : ""}</p>
    </div>
  );
}

function Passages({ chunks }) {
  if (!chunks.length) {
    return <p className="muted" style={{ fontSize: "0.8rem", marginTop: "0.4rem" }}>No matching passages.</p>;
  }
  return (
    <div className="passages">
      {chunks.map((hit, i) => (
        <div className="passage" key={i}>
          <div className="passage-head">
            <span className="passage-title">
              {hit.title || "(untitled paper)"}
              {hit.arxiv_id && (
                <span className="kv-key-mono" style={{ marginLeft: 6 }}>arXiv {hit.arxiv_id}</span>
              )}
            </span>
            <span className="passage-score" title="cosine similarity">{hit.score.toFixed(3)}</span>
          </div>
          <p className="passage-text">{hit.text}</p>
          <p className="passage-meta">passage #{hit.chunk_index}</p>
        </div>
      ))}
    </div>
  );
}

function Message({ msg }) {
  if (msg.role === "user") {
    return (
      <div className="msg user">
        <div className="bubble">{msg.text}</div>
      </div>
    );
  }
  return (
    <div className="msg bot">
      <div className="msg-avatar">AI</div>
      <div className={`bubble ${msg.kind === "chunks" ? "wide" : ""}`}>
        {msg.kind === "pending" && (
          <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="spinner" />
            <span className="muted" style={{ fontSize: "0.8rem" }}>Thinking…</span>
          </span>
        )}
        {msg.kind === "error" && (
          <span className="text-error" style={{ fontSize: "0.83rem" }}>{msg.text}</span>
        )}
        {msg.kind === "rows" && (
          <>
            {msg.answer && <p className="answer">{msg.answer}</p>}
            <ResultRows rows={msg.rows} />
          </>
        )}
        {msg.kind === "chunks" && (
          <>
            {msg.answer && <p className="answer">{msg.answer}</p>}
            <Passages chunks={msg.chunks} />
          </>
        )}
        {msg.kind === "note" && (
          <span className={msg.ok ? "text-ok" : "muted"} style={{ fontSize: "0.83rem" }}>
            {msg.text}
          </span>
        )}
      </div>
    </div>
  );
}

export default function Ask({ onIngested }) {
  const [messages, setMessages] = useState(() => loadHistory());
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState("ask");
  const [menuOpen, setMenuOpen] = useState(false);
  const fileRef = useRef(null);
  const endRef  = useRef(null);
  const menuRef = useRef(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onDoc = (e) => {
      if (!menuRef.current?.contains(e.target)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [menuOpen]);

  useEffect(() => {
    saveHistory(messages);
  }, [messages]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function push(msg) {
    setMessages((m) => [...m, { id: nextId(), ...msg }]);
  }
  function replaceLast(updater) {
    setMessages((m) => {
      const copy = [...m];
      copy[copy.length - 1] = { ...copy[copy.length - 1], ...updater };
      return copy;
    });
  }

  async function sendQuery(text) {
    if (!text || busy) return;
    setQ("");
    push({ role: "user", text });
    push({ role: "assistant", kind: "pending" });
    setBusy(true);
    try {
      if (mode === "search") {
        const res = await search(text);
        replaceLast({ kind: "chunks", chunks: res.chunks, answer: res.answer });
      } else {
        const res = await ask(text);
        replaceLast({ kind: "rows", rows: res.rows, answer: res.answer });
      }
    } catch (err) {
      replaceLast({ kind: "error", text: err.message });
    } finally {
      setBusy(false);
    }
  }

  function submit(e) {
    e.preventDefault();
    sendQuery(q.trim());
  }

  async function onFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    push({ role: "user", text: `Ingesting: ${file.name}` });
    push({ role: "assistant", kind: "pending" });
    setBusy(true);
    try {
      const r = await ingest(file);
      const c = r.counts;
      replaceLast({
        kind: "note",
        ok: true,
        text:
          `Stored "${r.title}" (${r.source_kind} lane) — ` +
          `${c.authors} author${c.authors !== 1 ? "s" : ""} · ` +
          `${c.datasets} dataset${c.datasets !== 1 ? "s" : ""} · ` +
          `${c.keywords} keyword${c.keywords !== 1 ? "s" : ""}`,
      });
      onIngested?.();
    } catch (err) {
      replaceLast({ kind: "error", text: err.message });
    } finally {
      setBusy(false);
    }
  }

  function clearHistory() {
    setMessages([]);
    localStorage.removeItem(STORAGE_KEY);
  }

  const empty = messages.length === 0;

  const ModeIcon = mode === "search" ? SearchModeIcon : AskModeIcon;

  const inputForm = (
    <form onSubmit={submit} className="chat-input">
      <div className="mode-select" ref={menuRef}>
        <button
          type="button"
          className="mode-btn"
          onClick={() => setMenuOpen((o) => !o)}
          disabled={busy}
          title="Switch mode"
        >
          <ModeIcon />
          {MODES[mode].label}
          <ChevronIcon />
        </button>
        {menuOpen && (
          <div className="mode-menu">
            {Object.entries(MODES).map(([id, meta]) => (
              <button
                key={id}
                type="button"
                className={`mode-item ${mode === id ? "active" : ""}`}
                onClick={() => { setMode(id); setMenuOpen(false); }}
              >
                <span className="mode-item-title">
                  {id === "search" ? <SearchModeIcon /> : <AskModeIcon />}
                  {meta.label}
                </span>
                <span className="mode-item-desc">{meta.desc}</span>
              </button>
            ))}
          </div>
        )}
      </div>
      <button
        type="button"
        className="chat-attach"
        title="Ingest a paper"
        onClick={() => fileRef.current?.click()}
        disabled={busy}
      >
        <AttachIcon />
      </button>
      <input
        ref={fileRef}
        type="file"
        accept=".pdf,.png,.jpg,.jpeg"
        onChange={onFile}
        style={{ display: "none" }}
      />
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={MODES[mode].placeholder}
        aria-label="question"
        disabled={busy}
      />
      <button type="submit" className="chat-send" disabled={busy || !q.trim()}>
        {busy ? <span className="spinner" style={{ borderTopColor: "currentColor" }} /> : <SendIcon />}
      </button>
    </form>
  );

  return (
    <div className="chat">
      <div className="page-header" style={{ marginBottom: "1rem", display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div>
          <h1 className="page-title">Ask</h1>
          <p className="page-desc">Ask the graph or search passages by meaning — switch modes in the input.</p>
        </div>
        {messages.length > 0 && (
          <button
            className="btn btn-ghost"
            onClick={clearHistory}
            disabled={busy}
            style={{ marginTop: "0.25rem", flexShrink: 0 }}
          >
            Clear history
          </button>
        )}
      </div>

      <div className="chat-log">
        {empty ? (
          <div className="ask-hero constellation">
            <div className="ask-hero-kicker">neo4j · knowledge graph</div>
            <h2 className="ask-hero-title">Ask the graph anything.</h2>
            {inputForm}
            <div className="ask-suggestions">
              {SUGGESTIONS[mode].map((s) => (
                <button
                  key={s}
                  type="button"
                  className="suggestion-chip"
                  onClick={() => sendQuery(s)}
                  disabled={busy}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map((m) => <Message key={m.id} msg={m} />)}
            <div ref={endRef} />
          </>
        )}
      </div>

      {!empty && <div className="chat-input-wrap">{inputForm}</div>}
    </div>
  );
}
