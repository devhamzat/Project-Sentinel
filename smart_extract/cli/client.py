"""HTTP client used by the remote Sentinel CLI.

The CLI intentionally knows nothing about Neo4j, OCR, or the LLM pipeline.  It
talks only to the deployed FastAPI API and presents the returned JSON.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests


class RemoteError(RuntimeError):
    """An API, network, or Cloudflare Access error safe to show to a user."""


class RemoteAuthenticationError(RemoteError):
    """The saved Sentinel session is missing, expired, or invalid."""


@dataclass(frozen=True)
class LoginResult:
    access_token: str
    expires_at: str
    user: dict[str, Any]


def normalise_api_url(value: str) -> str:
    """Validate and canonicalise a Sentinel API base URL."""
    url = value.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RemoteError("API URL must be an absolute http:// or https:// URL.")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RemoteError("Remote Sentinel API URLs must use HTTPS.")
    return url


def should_use_cloudflare(api_url: str) -> bool:
    """Enable Access automatically for non-local deployed URLs."""
    hostname = urlparse(api_url).hostname
    return hostname not in {"localhost", "127.0.0.1", "::1"}


def cloudflare_access_login(app_url: str) -> str:
    """Authenticate interactively with Cloudflare Access and return its JWT."""
    executable = shutil.which("cloudflared")
    if not executable:
        raise RemoteError(
            "cloudflared is required for this deployment. Install it, then run "
            "'sentinel login' again (or use --no-cloudflare for a local API)."
        )
    try:
        subprocess.run(
            [executable, "access", "login", app_url],
            check=True,
        )
        result = subprocess.run(
            [executable, "access", "token", f"-app={app_url}"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        suffix = f": {detail}" if detail else "."
        raise RemoteError(f"Cloudflare Access login failed{suffix}") from exc
    token = result.stdout.strip()
    if not token:
        raise RemoteError("Cloudflare Access did not return an access token.")
    return token


class RemoteClient:
    """Small, synchronous client for the deployed Sentinel API."""

    def __init__(
        self,
        api_url: str,
        *,
        sentinel_token: str | None = None,
        cloudflare_token: str | None = None,
        http: requests.Session | None = None,
    ) -> None:
        self.api_url = normalise_api_url(api_url)
        self.sentinel_token = sentinel_token
        self.cloudflare_token = cloudflare_token
        self.http = http or requests.Session()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.sentinel_token:
            headers["Authorization"] = f"Bearer {self.sentinel_token}"
        if self.cloudflare_token:
            headers["cf-access-token"] = self.cloudflare_token
        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        timeout: int = 60,
        **kwargs: Any,
    ) -> Any:
        headers = self._headers()
        headers.update(kwargs.pop("headers", {}))
        try:
            response = self.http.request(
                method,
                f"{self.api_url}/{path.lstrip('/')}",
                headers=headers,
                timeout=timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise RemoteError(f"Could not reach {self.api_url}: {exc}") from exc

        content_type = response.headers.get("content-type", "")
        if self.cloudflare_token and "text/html" in content_type:
            raise RemoteAuthenticationError(
                "Cloudflare Access rejected or expired this CLI session. "
                "Run 'sentinel login' again."
            )
        if response.status_code == 401:
            raise RemoteAuthenticationError(self._error_detail(response))
        if response.status_code == 403 and "text/html" in content_type:
            raise RemoteAuthenticationError(
                "Cloudflare Access rejected or expired this CLI session. "
                "Run 'sentinel login' again."
            )
        if not response.ok:
            raise RemoteError(self._error_detail(response))
        if response.status_code == 204:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise RemoteError("The Sentinel API returned an invalid JSON response.") from exc

    @staticmethod
    def _error_detail(response: requests.Response) -> str:
        try:
            body = response.json()
            detail = body.get("detail") if isinstance(body, dict) else None
        except ValueError:
            detail = None
        return str(detail or f"Sentinel API request failed (HTTP {response.status_code}).")

    def login(self, email: str, password: str) -> LoginResult:
        body = self.request(
            "POST", "/auth/token", json={"email": email, "password": password}
        )
        return LoginResult(
            access_token=body["access_token"],
            expires_at=body["expires_at"],
            user=body["user"],
        )

    def me(self) -> dict[str, Any]:
        return self.request("GET", "/auth/me")

    def logout(self) -> None:
        self.request("POST", "/auth/logout")

    def stats(self) -> dict[str, int]:
        return self.request("GET", "/stats")

    def ask(self, question: str) -> dict[str, Any]:
        return self.request("POST", "/ask", json={"question": question}, timeout=180)

    def search(self, query: str, k: int) -> dict[str, Any]:
        return self.request("POST", "/search", json={"query": query, "k": k}, timeout=180)

    def ingest(self, path: str | Path) -> dict[str, Any]:
        source = Path(path)
        if not source.is_file():
            raise RemoteError(f"File does not exist: {source}")
        try:
            with source.open("rb") as handle:
                return self.request(
                    "POST",
                    "/ingest",
                    files={"file": (source.name, handle)},
                    timeout=600,
                )
        except OSError as exc:
            raise RemoteError(f"Could not read {source}: {exc}") from exc

    def list_users(self) -> list[dict[str, Any]]:
        return self.request("GET", "/admin/users")

    def add_user(self, email: str, password: str, role: str) -> dict[str, Any]:
        return self.request(
            "POST", "/admin/users", json={"email": email, "password": password, "role": role}
        )

    def claim_user_papers(self, email: str) -> dict[str, Any]:
        encoded = quote(email, safe="")
        return self.request("POST", f"/admin/users/{encoded}/claim")

    def reset_user_password(self, email: str, password: str) -> dict[str, Any]:
        encoded = quote(email, safe="")
        return self.request(
            "PUT", f"/admin/users/{encoded}/password", json={"password": password}
        )

    def set_user_active(self, email: str, active: bool) -> dict[str, Any]:
        encoded = quote(email, safe="")
        return self.request(
            "PATCH", f"/admin/users/{encoded}", json={"active": active}
        )
