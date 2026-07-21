import { useState } from "react";
import { login } from "../api.js";

export default function Login({ onAuthenticated }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    if (!email.trim() || !password || busy) return;
    setBusy(true);
    setError("");
    try {
      const user = await login(email.trim(), password);
      onAuthenticated(user);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell constellation">
      <section className="auth-card" aria-labelledby="login-title">
        <div className="brand auth-brand">
          <div className="brand-icon" aria-hidden="true">
            <svg viewBox="0 0 16 16">
              <path d="M8 2L3 5v4l5 3 5-3V5z" />
              <line x1="8" y1="9" x2="8" y2="14" />
            </svg>
          </div>
          <div className="brand-text">
            <span className="brand-name">Sentinel</span>
            <span className="brand-sub">private research workspace</span>
          </div>
        </div>

        <div className="auth-heading">
          <h1 id="login-title">Sign in</h1>
          <p>Use the account issued by the project administrator.</p>
        </div>

        <form onSubmit={submit} className="auth-form">
          <label>
            <span>Email</span>
            <input
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              autoFocus
            />
          </label>
          <label>
            <span>Password</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>
          {error && <div className="auth-error" role="alert">{error}</div>}
          <button className="btn btn-primary auth-submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </section>
    </main>
  );
}
