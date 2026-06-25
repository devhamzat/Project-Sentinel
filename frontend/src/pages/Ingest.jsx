import { useState, useRef } from "react";
import { ingest } from "../api.js";

function UploadIcon() {
  return (
    <svg className="drop-icon" viewBox="0 0 40 40" fill="none"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M28 26.7A8 8 0 0 0 20 12a8 8 0 0 0-7.76 6.07A6 6 0 1 0 10 30h20a5 5 0 0 0-2-3.3z" />
      <line x1="20" y1="22" x2="20" y2="32" />
      <polyline points="16 26 20 22 24 26" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="2.5 8.5 6.5 12.5 13.5 4.5" />
    </svg>
  );
}

export default function Ingest({ onIngested }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef(null);

  async function process(file) {
    if (!file) return;
    setBusy(true);
    setResult(null);
    setError(null);
    try {
      const r = await ingest(file);
      setResult(r);
      onIngested?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  function onChange(e) { process(e.target.files?.[0]); }

  function onDrop(e) {
    e.preventDefault();
    setDragOver(false);
    process(e.dataTransfer.files?.[0]);
  }

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Ingest a Paper</h1>
        <p className="page-desc">
          Upload a born-digital PDF or a page photo (PNG / JPG). The system will
          extract entities and store them in the knowledge graph.
        </p>
      </div>

      <div
        className={`drop-zone ${dragOver ? "drag-over" : ""} ${busy ? "uploading" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.png,.jpg,.jpeg"
          onChange={onChange}
          disabled={busy}
        />
        {busy ? (
          <>
            <span className="spinner" style={{ width: 28, height: 28, borderWidth: 3, margin: "0 auto 1rem" }} />
            <div className="drop-label">Processing…</div>
            <div className="drop-sub">Extracting entities and writing to graph</div>
          </>
        ) : (
          <>
            <UploadIcon />
            <div className="drop-label">Drop a file here, or click to browse</div>
            <div className="drop-sub">.pdf · .png · .jpg · .jpeg</div>
          </>
        )}
      </div>

      {error && (
        <div className="status-line error" style={{ marginTop: "1rem" }}>
          <span>{error}</span>
        </div>
      )}

      {result && (
        <div className="result-card">
          <div className="result-card-header">
            <CheckIcon />
            <span className="result-card-title">{result.title}</span>
            <span className="badge badge-ok">{result.source_kind}</span>
          </div>
          <div className="result-counts">
            <div className="result-count-cell">
              <span className="count-num">{result.counts?.authors ?? 0}</span>
              <span className="count-label">Authors</span>
            </div>
            <div className="result-count-cell">
              <span className="count-num">{result.counts?.datasets ?? 0}</span>
              <span className="count-label">Datasets</span>
            </div>
            <div className="result-count-cell">
              <span className="count-num">{result.counts?.keywords ?? 0}</span>
              <span className="count-label">Keywords</span>
            </div>
          </div>
        </div>
      )}

      <div className="divider" />

      <div className="section-label">Supported formats</div>
      <div className="kv-list">
        <div className="kv-row">
          <span className="kv-key">PDF — digital lane
            <span className="kv-key-mono">.pdf</span>
          </span>
          <span style={{ fontSize: "0.78rem", color: "var(--softer)" }}>text layer extracted directly</span>
        </div>
        <div className="kv-row">
          <span className="kv-key">Image — OCR lane
            <span className="kv-key-mono">.png .jpg</span>
          </span>
          <span style={{ fontSize: "0.78rem", color: "var(--softer)" }}>OpenCV → Tesseract → text</span>
        </div>
      </div>
    </div>
  );
}
