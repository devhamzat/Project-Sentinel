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
