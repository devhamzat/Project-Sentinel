// The ONLY module that talks to the backend. All requests go through the Vite
// /api proxy to the FastAPI REST API. No business logic lives here — just HTTP.

const BASE = "/api";

async function handle(res) {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res.json();
}

export function getStats() {
  return fetch(`${BASE}/stats`).then(handle);
}

export function ask(question) {
  return fetch(`${BASE}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  }).then(handle);
}

export function search(query, k = 5) {
  return fetch(`${BASE}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, k }),
  }).then(handle);
}

export function ingest(file) {
  const form = new FormData();
  form.append("file", file);
  return fetch(`${BASE}/ingest`, { method: "POST", body: form }).then(handle);
}
