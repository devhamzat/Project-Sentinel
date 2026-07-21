"""Offline tests for the remote CLI HTTP boundary."""

from __future__ import annotations

import pytest


class FakeResponse:
    def __init__(self, status: int, body=None, content_type="application/json"):
        self.status_code = status
        self._body = body
        self.headers = {"content-type": content_type}
        self.ok = 200 <= status < 300

    def json(self):
        if self._body is None:
            raise ValueError
        return self._body


class FakeHttp:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


def test_remote_client_sends_both_authentication_tokens():
    from smart_extract.cli.client import RemoteClient

    http = FakeHttp(FakeResponse(200, {"papers": 3}))
    client = RemoteClient(
        "https://sentinel.example.com/api/",
        sentinel_token="sentinel-token",
        cloudflare_token="cloudflare-token",
        http=http,
    )
    assert client.stats() == {"papers": 3}
    method, url, kwargs = http.calls[0]
    assert (method, url) == ("GET", "https://sentinel.example.com/api/stats")
    assert kwargs["headers"]["Authorization"] == "Bearer sentinel-token"
    assert kwargs["headers"]["cf-access-token"] == "cloudflare-token"


def test_remote_client_turns_401_into_session_error():
    from smart_extract.cli.client import RemoteAuthenticationError, RemoteClient

    client = RemoteClient(
        "http://127.0.0.1:8000",
        sentinel_token="expired",
        http=FakeHttp(FakeResponse(401, {"detail": "Session expired."})),
    )
    with pytest.raises(RemoteAuthenticationError, match="Session expired"):
        client.me()


def test_remote_client_identifies_cloudflare_html_rejection():
    from smart_extract.cli.client import RemoteAuthenticationError, RemoteClient

    client = RemoteClient(
        "https://sentinel.example.com/api",
        http=FakeHttp(FakeResponse(403, None, "text/html")),
    )
    with pytest.raises(RemoteAuthenticationError, match="Cloudflare Access"):
        client.stats()


def test_remote_url_requires_https():
    from smart_extract.cli.client import RemoteClient, RemoteError

    with pytest.raises(RemoteError, match="HTTPS"):
        RemoteClient("http://sentinel.example.com/api")


def test_login_uses_token_endpoint():
    from smart_extract.cli.client import RemoteClient

    http = FakeHttp(FakeResponse(200, {
        "access_token": "token",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "user": {"id": "w", "email": "a@example.com", "role": "tester"},
    }))
    result = RemoteClient("http://localhost:8000", http=http).login(
        "a@example.com", "password"
    )
    assert result.access_token == "token"
    assert http.calls[0][1].endswith("/auth/token")
    assert http.calls[0][2]["json"]["email"] == "a@example.com"
