// The ONLY module that talks to the backend. No business logic lives here —
// just HTTP.
//
// In dev, requests go to "/api/*" and Vite proxies them to the FastAPI backend
// (see vite.config.js). In production the built frontend is served by FastAPI
// itself (same origin), so the base is "" and requests hit "/auth/login" etc.
// directly. Override via VITE_API_BASE at build time.
const BASE = import.meta.env.VITE_API_BASE ?? "/api";

async function handle(res) {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* non-JSON error body */
    }
    const error = new Error(detail);
    error.status = res.status;
    if (res.status === 401) {
      window.dispatchEvent(new CustomEvent("sentinel-auth-expired"));
    }
    throw error;
  }
  if (res.status === 204) return null;
  return res.json();
}

function request(path, options = {}) {
  return fetch(`${BASE}${path}`, { credentials: "include", ...options }).then(handle);
}

export function login(email, password) {
  return request("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}

export function register(email, password) {
  return request("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}

export function logout() {
  return request("/auth/logout", { method: "POST" });
}

export function getMe() {
  return request("/auth/me");
}

export function getStats() {
  return request("/stats");
}

export function ask(question) {
  return request("/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
}

export function search(query, k = 5) {
  return request("/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, k }),
  });
}

export function ingest(file) {
  const form = new FormData();
  form.append("file", file);
  return request("/ingest", { method: "POST", body: form });
}

// Gold labelling (admin-only research tooling — not a tester-facing feature).
export function listGold() {
  return request("/gold");
}

export function getGold(arxivId) {
  return request(`/gold/${encodeURIComponent(arxivId)}`);
}

export function saveGold(arxivId, title, fields) {
  return request(`/gold/${encodeURIComponent(arxivId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, fields }),
  });
}
