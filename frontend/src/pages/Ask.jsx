import { useEffect, useRef, useState } from "react";
import { ask, ingest } from "../api.js";

const STORAGE_KEY = "sentinel-chat-history";
const MAX_STORED = 200;

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
      <div className="bubble">
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
  const fileRef = useRef(null);
  const endRef  = useRef(null);

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

  async function submit(e) {
    e.preventDefault();
    const text = q.trim();
    if (!text || busy) return;
    setQ("");
    push({ role: "user", text });
    push({ role: "assistant", kind: "pending" });
    setBusy(true);
    try {
      const res = await ask(text);
      replaceLast({ kind: "rows", rows: res.rows, answer: res.answer });
    } catch (err) {
      replaceLast({ kind: "error", text: err.message });
    } finally {
      setBusy(false);
    }
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

  return (
    <div className="chat">
      <div className="page-header" style={{ marginBottom: "1rem", display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div>
          <h1 className="page-title">Ask</h1>
          <p className="page-desc">Ask questions in plain English — or attach a paper to ingest it.</p>
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
        {messages.length === 0 && (
          <div className="chat-empty">
            <span className="chat-empty-icon">🔍</span>
            Ask about papers, authors, datasets, or keywords.<br />
            Hit the paperclip to add a new paper.
          </div>
        )}
        {messages.map((m) => <Message key={m.id} msg={m} />)}
        <div ref={endRef} />
      </div>

      <div className="chat-input-wrap">
        <form onSubmit={submit} className="chat-input">
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
            placeholder="Which papers use BERT?"
            aria-label="question"
            disabled={busy}
          />
          <button type="submit" className="chat-send" disabled={busy || !q.trim()}>
            {busy ? <span className="spinner" style={{ borderTopColor: "#fff" }} /> : <SendIcon />}
          </button>
        </form>
      </div>
    </div>
  );
}
