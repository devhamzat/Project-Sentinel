import { useEffect, useRef, useState } from "react";
import { ask, ingest } from "../api.js";

let idSeq = 0;
const nextId = () => ++idSeq;

function ResultRows({ rows }) {
  if (!rows.length) {
    return <p className="muted">query ran — nothing in the graph matched.</p>;
  }
  const cols = Object.keys(rows[0]);
  return (
    <>
      <table>
        <thead>
          <tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>{cols.map((c) => <td key={c}>{String(row[c])}</td>)}</tr>
          ))}
        </tbody>
      </table>
      <p className="rowcount">{rows.length} row(s)</p>
    </>
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
  // assistant
  return (
    <div className="msg bot">
      <div className="bubble">
        {msg.kind === "error" && <p className="error">{msg.text}</p>}
        {msg.kind === "rows" && (
          <>
            {msg.answer && <p className="answer">{msg.answer}</p>}
            {msg.rows.length > 0 && <ResultRows rows={msg.rows} />}
          </>
        )}
        {msg.kind === "note" && <p className={msg.ok ? "ok" : "muted"}>{msg.text}</p>}
        {msg.kind === "pending" && <p className="muted">…</p>}
      </div>
    </div>
  );
}

export default function Ask({ onIngested }) {
  const [messages, setMessages] = useState([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);
  const endRef = useRef(null);

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
    push({ role: "user", text: `+ ${file.name}` });
    push({ role: "assistant", kind: "pending" });
    setBusy(true);
    try {
      const r = await ingest(file);
      const c = r.counts;
      replaceLast({
        kind: "note",
        ok: true,
        text:
          `stored "${r.title}" (${r.source_kind} lane): ` +
          `${c.authors} authors · ${c.datasets} datasets · ${c.keywords} keywords`,
      });
      onIngested?.();
    } catch (err) {
      replaceLast({ kind: "error", text: err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="chat">
      <div className="chat-log">
        {messages.length === 0 && (
          <p className="muted chat-empty">
            ask about papers, authors, datasets, keywords… or hit + to add a paper.
          </p>
        )}
        {messages.map((m) => <Message key={m.id} msg={m} />)}
        <div ref={endRef} />
      </div>

      <form onSubmit={submit} className="prompt chat-input">
        <button
          type="button"
          className="plus"
          title="ingest a paper"
          onClick={() => fileRef.current?.click()}
          disabled={busy}
        >
          +
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
          placeholder="which papers use core-bench?"
          aria-label="question"
        />
        <button disabled={busy}>{busy ? "…" : "run"}</button>
      </form>
    </section>
  );
}
