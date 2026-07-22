import { useState } from "react";
import { login, register } from "../api.js";

export default function Login({ onAuthenticated }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    if (!email.trim() || !password || busy) return;
    if (creating && password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const user = creating
        ? await register(email.trim(), password)
        : await login(email.trim(), password);
      onAuthenticated(user);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function switchMode() {
    setCreating((value) => !value);
    setConfirmPassword("");
    setError("");
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
          <h1 id="login-title">{creating ? "Create account" : "Sign in"}</h1>
          <p>
            {creating
              ? "Create your own private research workspace."
              : "Sign in to your private research workspace."}
          </p>
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
              autoComplete={creating ? "new-password" : "current-password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              minLength={creating ? 12 : undefined}
              required
            />
          </label>
          {creating && (
            <label>
              <span>Confirm password</span>
              <input
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                minLength={12}
                required
              />
            </label>
          )}
          {error && <div className="auth-error" role="alert">{error}</div>}
          <button className="btn btn-primary auth-submit" disabled={busy}>
            {busy
              ? (creating ? "Creating account..." : "Signing in...")
              : (creating ? "Create account" : "Sign in")}
          </button>
          <button
            type="button"
            className="auth-switch"
            disabled={busy}
            onClick={switchMode}
          >
            {creating ? "Already have an account? Sign in" : "New here? Create an account"}
          </button>
        </form>
      </section>
    </main>
  );
}
