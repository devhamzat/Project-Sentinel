import { useState } from "react";
import { ingest } from "../api.js";

export default function Ingest({ onIngested }) {
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  async function onFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setStatus(`ingesting ${file.name}…`);
    try {
      const r = await ingest(file);
      const c = r.counts;
      setStatus(
        `stored "${r.title}" (${r.source_kind} lane): ` +
          `${c.authors} authors · ${c.datasets} datasets · ${c.keywords} keywords`
      );
      onIngested?.();
    } catch (err) {
      setStatus(`failed: ${err.message}`);
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }

  return (
    <section className="block">
      <h2>ingest a paper</h2>
      <div className="file">
        <input
          type="file"
          accept=".pdf,.png,.jpg,.jpeg"
          onChange={onFile}
          disabled={busy}
        />
        <div>pdf (digital lane) or page photo png/jpg (ocr lane)</div>
      </div>
      {status && (
        <p className={`status ${status.startsWith("failed") ? "error" : "ok"}`}>
          {status}
        </p>
      )}
    </section>
  );
}
