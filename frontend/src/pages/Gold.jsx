import { useEffect, useMemo, useState } from "react";
import { listGold, getGold, saveGold } from "../api.js";

// Admin-only labelling of the evaluation gold set (§11). This is a research
// tool, not a tester feature: it edits data/gold/*.json so evaluate.py has a
// human-verified ground truth. The reviewer decides every value; nothing here
// auto-labels. Grounding markers (✓/⚠) only show where a value appears in the
// real paper text — they are hints, not answers.

const FIELD_LABELS = {
  authors: "Authors",
  affiliations: "Affiliations",
  keywords: "Keywords",
  datasets: "Datasets (USES)",
  methods: "Methods",
  metrics: "Metrics",
};
const FIELD_ORDER = ["authors", "affiliations", "keywords", "datasets", "methods", "metrics"];

function StatusDot({ labelled }) {
  return (
    <span
      className={`gold-dot ${labelled ? "done" : "todo"}`}
      title={labelled ? "hand-labelled" : "still a template"}
      aria-hidden="true"
    />
  );
}

function Mark({ inPaper }) {
  if (inPaper === null) return <span className="gold-mark unknown" title="no PDF to check against">?</span>;
  if (inPaper) return <span className="gold-mark ok" title="found in paper text">✓</span>;
  return <span className="gold-mark warn" title="NOT found in paper text — likely wrong">⚠</span>;
}

function FieldEditor({ field, entries, onChange }) {
  const [draft, setDraft] = useState("");

  function remove(i) {
    onChange(entries.filter((_, idx) => idx !== i));
  }
  function add() {
    const v = draft.trim();
    if (!v) return;
    if (entries.some((e) => e.value.toLowerCase() === v.toLowerCase())) {
      setDraft("");
      return;
    }
    // Manually added values have no grounding snapshot; mark as unknown.
    onChange([...entries, { value: v, in_paper: null, snippets: [], added: true }]);
    setDraft("");
  }

  const warnCount = entries.filter((e) => e.in_paper === false).length;

  return (
    <div className="gold-field">
      <div className="gold-field-head">
        <span className="section-label" style={{ margin: 0 }}>
          {FIELD_LABELS[field]} ({entries.length})
        </span>
        {warnCount > 0 && (
          <span className="gold-warn-badge" title="values not found in the paper text">
            {warnCount} to check
          </span>
        )}
      </div>

      {field === "datasets" && entries.length === 0 && (
        <p className="gold-hint">
          Empty USES relation — confirm the paper really uses no named dataset
          before saving. This is the project's central relation.
        </p>
      )}

      <ul className="gold-values">
        {entries.map((e, i) => (
          <li key={i} className={`gold-value ${e.in_paper === false ? "warn" : ""}`}>
            <Mark inPaper={e.in_paper} />
            <div className="gold-value-body">
              <span className="gold-value-text">{e.value}</span>
              {e.snippets && e.snippets.length > 0 && (
                <span className="gold-snippets">
                  {e.snippets.map((s, si) => (
                    <span key={si} className="gold-snippet">· {s}</span>
                  ))}
                </span>
              )}
            </div>
            <button
              type="button"
              className="gold-remove"
              onClick={() => remove(i)}
              aria-label={`remove ${e.value}`}
              title="drop this value"
            >
              ×
            </button>
          </li>
        ))}
        {entries.length === 0 && <li className="gold-empty">(empty)</li>}
      </ul>

      <div className="gold-add">
        <input
          value={draft}
          onChange={(ev) => setDraft(ev.target.value)}
          onKeyDown={(ev) => {
            if (ev.key === "Enter") {
              ev.preventDefault();
              add();
            }
          }}
          placeholder={`add ${FIELD_LABELS[field].toLowerCase()}…`}
          aria-label={`add ${field}`}
        />
        <button type="button" className="btn btn-ghost" onClick={add} disabled={!draft.trim()}>
          Add
        </button>
      </div>
    </div>
  );
}

export default function Gold() {
  const [papers, setPapers] = useState([]);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [title, setTitle] = useState("");
  const [fields, setFields] = useState({});
  const [textFilter, setTextFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(null);

  async function refreshList() {
    setLoading(true);
    try {
      setPapers(await listGold());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refreshList();
  }, []);

  async function open(arxivId) {
    setError(null);
    setSaved(null);
    setSelected(arxivId);
    setDetail(null);
    try {
      const d = await getGold(arxivId);
      setDetail(d);
      setTitle(d.title);
      setFields(d.fields);
      setTextFilter("");
    } catch (err) {
      setError(err.message);
    }
  }

  async function save() {
    if (!selected || busy) return;
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      const payload = {};
      for (const f of FIELD_ORDER) {
        payload[f] = (fields[f] || []).map((e) => e.value);
      }
      const res = await saveGold(selected, title, payload);
      setSaved(res);
      // Reflect labelled status locally without a full reload.
      setPapers((prev) =>
        prev.map((p) => (p.arxiv_id === selected ? { ...p, labelled: true } : p)),
      );
      setDetail((prev) => (prev ? { ...prev, labelled: true } : prev));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const setField = (field) => (entries) =>
    setFields((prev) => ({ ...prev, [field]: entries }));

  const progress = useMemo(() => {
    const done = papers.filter((p) => p.labelled).length;
    return { done, total: papers.length };
  }, [papers]);

  const filteredText = useMemo(() => {
    if (!detail?.text) return "";
    const needle = textFilter.trim().toLowerCase();
    if (!needle) return detail.text.slice(0, 6000);
    return detail.text
      .split("\n")
      .filter((line) => line.toLowerCase().includes(needle))
      .slice(0, 60)
      .join("\n");
  }, [detail, textFilter]);

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Gold labelling</h1>
        <p className="page-desc">
          Hand-verify the evaluation ground truth (admin only). ✓ means a value
          appears in the paper text, ⚠ means it does not — but you decide every
          value. Saving marks a paper as human-labelled for evaluation.
        </p>
      </div>

      {papers.length > 0 && (
        <div className="gold-progress">
          <div className="gold-progress-bar">
            <div
              className="gold-progress-fill"
              style={{ width: `${progress.total ? (progress.done / progress.total) * 100 : 0}%` }}
            />
          </div>
          <span className="muted" style={{ fontSize: "0.8rem" }}>
            {progress.done}/{progress.total} labelled
          </span>
        </div>
      )}

      {error && <div className="status-line error"><span>{error}</span></div>}

      <div className="gold-layout">
        <aside className="gold-list">
          {loading && <span className="spinner" aria-label="loading" />}
          {papers.map((p) => (
            <button
              key={p.arxiv_id}
              className={`gold-list-item ${selected === p.arxiv_id ? "active" : ""}`}
              onClick={() => open(p.arxiv_id)}
            >
              <StatusDot labelled={p.labelled} />
              <span className="gold-list-title">{p.title || p.arxiv_id}</span>
              <span
                className={`gold-list-uses ${p.datasets === 0 ? "warn" : ""}`}
                title="dataset (USES) count"
              >
                {p.datasets} ds
              </span>
            </button>
          ))}
        </aside>

        <section className="gold-detail">
          {!selected && <p className="muted">Select a paper to label.</p>}
          {selected && !detail && <span className="spinner" aria-label="loading paper" />}
          {detail && (
            <>
              <label className="gold-title-field">
                <span className="section-label" style={{ margin: 0 }}>Title</span>
                <input value={title} onChange={(e) => setTitle(e.target.value)} />
              </label>

              {!detail.has_text && (
                <div className="status-line warn">
                  <span>No readable PDF for this paper — grounding hints unavailable.</span>
                </div>
              )}

              {FIELD_ORDER.map((f) => (
                <FieldEditor
                  key={f}
                  field={f}
                  entries={fields[f] || []}
                  onChange={setField(f)}
                />
              ))}

              <div className="gold-actions">
                <button className="btn btn-primary" onClick={save} disabled={busy}>
                  {busy ? <span className="spinner" style={{ borderTopColor: "#fff" }} /> : null}
                  Save as labelled
                </button>
                {saved && <span className="gold-saved">Saved ✓ ({detail.labelled ? "labelled" : ""})</span>}
              </div>
            </>
          )}
        </section>

        {detail?.has_text && (
          <aside className="gold-text">
            <input
              className="gold-text-filter"
              value={textFilter}
              onChange={(e) => setTextFilter(e.target.value)}
              placeholder="find in paper text…"
              aria-label="filter paper text"
            />
            <pre className="gold-text-body">{filteredText}</pre>
          </aside>
        )}
      </div>
    </div>
  );
}