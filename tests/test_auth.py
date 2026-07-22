"""Offline authentication and tenant-query safety tests."""

from __future__ import annotations

import pytest
from pydantic import SecretStr
from contextlib import contextmanager


def test_password_hash_round_trip_and_random_salt():
    from smart_extract.auth import hash_password, verify_password

    first = hash_password("a-correct-horse-battery-staple")
    second = hash_password("a-correct-horse-battery-staple")
    assert first != second
    assert verify_password("a-correct-horse-battery-staple", first)
    assert not verify_password("wrong-password-value", first)


def test_password_policy_rejects_short_password():
    from smart_extract.auth import AuthError, hash_password

    with pytest.raises(AuthError):
        hash_password("too-short")


def test_session_rejects_tampering_before_database(monkeypatch):
    from smart_extract import auth

    monkeypatch.setattr(
        auth.settings, "auth_secret", SecretStr("x" * 48)
    )
    user = auth.User(id="user-1", email="a@example.com", role="tester")
    token = auth.issue_session(user, now=100)
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(auth.InvalidCredentials):
        auth.user_from_session(tampered, now=101)


def test_session_rejects_expired_token_before_database(monkeypatch):
    from smart_extract import auth

    monkeypatch.setattr(auth.settings, "auth_secret", SecretStr("y" * 48))
    monkeypatch.setattr(auth.settings, "auth_token_ttl_minutes", 1)
    user = auth.User(id="user-1", email="a@example.com", role="tester")
    token = auth.issue_session(user, now=100)
    with pytest.raises(auth.InvalidCredentials):
        auth.user_from_session(token, now=161)


def test_valid_session_resolves_active_user(monkeypatch):
    from smart_extract import auth

    monkeypatch.setattr(auth.settings, "auth_secret", SecretStr("z" * 48))
    user = auth.User(
        id="user-1", email="a@example.com", role="tester", session_version=3
    )
    token = auth.issue_session(user, now=100)

    class FakeStore:
        def get_user_by_id(self, user_id):
            assert user_id == "user-1"
            return {
                "id": user_id, "email": "a@example.com", "role": "tester",
                "active": True, "session_version": 3,
            }

    @contextmanager
    def fake_open_store():
        yield FakeStore()

    monkeypatch.setattr(auth, "open_store", fake_open_store)
    assert auth.user_from_session(token, now=101) == user


@pytest.mark.parametrize("cypher", [
    "MATCH (w:Workspace {id: $user_id})-[:OWNS]->(p:Paper) RETURN p.title",
    "MATCH (w:Workspace {id: $user_id})-[:OWNS]->(p:Paper)-[:USES]->(d:Dataset) RETURN d.name",
    "MATCH (w:Workspace {id: $user_id})-[:OWNS]->(p:Paper)-[:AUTHORED_BY]->(a:Author)-[:AFFILIATED_WITH {owner_id: $user_id}]->(x:Affiliation) RETURN x.name",
])
def test_owner_scoped_query_accepts_connected_shapes(cypher):
    from smart_extract.query.nl2cypher import is_owner_scoped

    assert is_owner_scoped(cypher)


@pytest.mark.parametrize("cypher", [
    "MATCH (p:Paper) RETURN p.title",
    "MATCH (w:Workspace {id: $user_id})-[:OWNS]->(p:Paper) MATCH (other:Paper) RETURN other",
    "MATCH (w:Workspace {id: $user_id})-[:OWNS]->(p:Paper), (other:Paper) RETURN other",
    "MATCH (w:Workspace {id: $user_id})-[:OWNS]->(p:Paper)-[*]->(other) RETURN other",
    "MATCH (w:Workspace {id: $user_id})-[:OWNS]->(p:Paper) CALL apoc.refactor.rename.label('A','B',[]) RETURN p",
    "MATCH (w:Workspace {id: $user_id})-[:OWNS]->(p:Paper) RETURN [(p)<-[:OWNS]-(other:Workspace) | other.id]",
])
def test_owner_scoped_query_rejects_escape_shapes(cypher):
    from smart_extract.query.nl2cypher import is_owner_scoped

    assert not is_owner_scoped(cypher)


def test_cli_data_command_requires_login(monkeypatch, capsys):
    from smart_extract.cli import main as cli

    monkeypatch.setattr(cli, "load_session", lambda: None)
    assert cli.main(["stats"]) == 1
    assert "sentinel login" in capsys.readouterr().out


def test_cli_stats_passes_authenticated_workspace(monkeypatch):
    from smart_extract.cli import main as cli
    from smart_extract.cli.session import CliSession

    session = CliSession(
        api_url="https://sentinel.example.com/api",
        sentinel_token="app-token",
        cloudflare_token="cf-token",
        email="a@example.com",
        role="tester",
        expires_at="2030-01-01T00:00:00+00:00",
    )
    monkeypatch.setattr(cli, "_require_session", lambda *a, **k: session)
    seen = {"stats": 0}

    class FakeClient:
        def stats(self):
            seen["stats"] += 1
            return {"papers": 2}

    monkeypatch.setattr(cli, "_client", lambda value: FakeClient())
    assert cli.main(["stats"]) == 0
    assert seen == {"stats": 1}


def test_cli_admin_gate_rejects_tester(monkeypatch, capsys):
    from smart_extract.cli import main as cli
    from smart_extract.cli.session import CliSession

    monkeypatch.setattr(cli, "load_session", lambda: CliSession(
        api_url="https://sentinel.example.com/api",
        sentinel_token="token",
        cloudflare_token="cf-token",
        email="a@example.com",
        role="tester",
        expires_at="2030-01-01T00:00:00+00:00",
    ))
    assert cli._require_session(admin=True) is None
    assert "requires an admin" in capsys.readouterr().out


def test_cli_login_stores_remote_session(monkeypatch, capsys):
    from smart_extract.cli import main as cli
    from smart_extract.cli.client import LoginResult

    saved = {}

    class FakeClient:
        def __init__(self, api_url, cloudflare_token=None):
            assert api_url == "http://127.0.0.1:8000"
            assert cloudflare_token is None

        def login(self, email, password):
            assert (email, password) == ("a@example.com", "password")
            return LoginResult(
                access_token="signed-token",
                expires_at="2030-01-01T00:00:00+00:00",
                user={"id": "w", "email": email, "role": "admin"},
            )

    monkeypatch.setattr(cli.getpass, "getpass", lambda *a: "password")
    monkeypatch.setattr(cli, "RemoteClient", FakeClient)
    monkeypatch.setattr(cli, "save_session", lambda value: saved.setdefault("session", value))
    assert cli.main([
        "login", "a@example.com", "--api-url", "http://127.0.0.1:8000"
    ]) == 0
    assert saved["session"].sentinel_token == "signed-token"
    assert saved["session"].api_url == "http://127.0.0.1:8000"
    assert "signed in as" in capsys.readouterr().out


def test_cli_login_uses_cloudflare_for_remote_url(monkeypatch):
    from smart_extract.cli import main as cli
    from smart_extract.cli.client import LoginResult

    seen = {}

    class FakeClient:
        def __init__(self, api_url, cloudflare_token=None):
            seen["client"] = (api_url, cloudflare_token)

        def login(self, email, password):
            return LoginResult(
                access_token="app-token",
                expires_at="2030-01-01T00:00:00+00:00",
                user={"id": "w", "email": email, "role": "tester"},
            )

    monkeypatch.setattr(cli, "cloudflare_access_login", lambda url: "cf-token")
    monkeypatch.setattr(cli, "RemoteClient", FakeClient)
    monkeypatch.setattr(cli.getpass, "getpass", lambda *a: "password")
    monkeypatch.setattr(cli, "save_session", lambda value: seen.setdefault("session", value))
    assert cli.main([
        "login", "a@example.com", "--api-url", "https://sentinel.example.com/api"
    ]) == 0
    assert seen["client"] == ("https://sentinel.example.com/api", "cf-token")
    assert seen["session"].cloudflare_token == "cf-token"


def test_cli_keyring_session_round_trip(monkeypatch):
    from smart_extract.cli import session

    vault = {}
    monkeypatch.setattr(
        session.keyring, "set_password", lambda service, account, token: vault.__setitem__((service, account), token)
    )
    monkeypatch.setattr(
        session.keyring, "get_password", lambda service, account: vault.get((service, account))
    )
    monkeypatch.setattr(
        session.keyring, "delete_password", lambda service, account: vault.pop((service, account))
    )
    assert session.load_session() is None
    expected = session.CliSession(
        api_url="https://sentinel.example.com/api",
        sentinel_token="app-token",
        cloudflare_token="cf-token",
        email="a@example.com",
        role="tester",
        expires_at="2030-01-01T00:00:00+00:00",
    )
    session.save_session(expected)
    assert session.load_session() == expected
    assert session.clear_session() is True
    assert session.load_session() is None


def test_api_token_login_returns_cli_bearer(monkeypatch):
    from datetime import datetime, timezone
    from smart_extract.auth import User
    from smart_extract.api import main as api

    user = User(id="workspace-1", email="a@example.com", role="tester")
    monkeypatch.setattr(api, "authenticate", lambda email, password: user)
    monkeypatch.setattr(api, "issue_session", lambda value: "signed-token")
    monkeypatch.setattr(
        api,
        "session_expires_at",
        lambda token: datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    result = api.token_login(api.LoginRequest(
        email="a@example.com", password="not-stored-by-cli"
    ))
    assert result.access_token == "signed-token"
    assert result.token_type == "bearer"
    assert result.user.id == "workspace-1"


def test_api_admin_dependency_rejects_tester():
    from fastapi import HTTPException
    from smart_extract.auth import User
    from smart_extract.api.main import require_admin

    with pytest.raises(HTTPException) as exc_info:
        require_admin(User(id="w", email="a@example.com", role="tester"))
    assert exc_info.value.status_code == 403


def test_api_prevents_admin_self_disable():
    from fastapi import HTTPException
    from smart_extract.auth import User
    from smart_extract.api import main as api

    admin = User(id="w", email="admin@example.com", role="admin")
    with pytest.raises(HTTPException) as exc_info:
        api.set_user_active(
            "admin@example.com", api.UserActiveRequest(active=False), admin
        )
    assert exc_info.value.status_code == 400


def test_api_registration_always_creates_tester(monkeypatch):
    from smart_extract.auth import User
    from smart_extract.api import main as api

    seen = {}

    def fake_create(email, password, role):
        seen["values"] = (email, password, role)
        return User(id="new-workspace", email=email, role=role)

    monkeypatch.setattr(api.settings, "registration_enabled", True)
    monkeypatch.setattr(api, "create_user", fake_create)
    monkeypatch.setattr(api, "issue_session", lambda user: "token")
    user, token = api._register_tester(api.LoginRequest(
        email="new@example.com", password="long-enough-password"
    ))
    assert seen["values"] == (
        "new@example.com", "long-enough-password", "tester"
    )
    assert user.role == "tester"
    assert token == "token"


def test_api_registration_can_be_disabled(monkeypatch):
    from fastapi import HTTPException
    from smart_extract.api import main as api

    monkeypatch.setattr(api.settings, "registration_enabled", False)
    with pytest.raises(HTTPException) as exc_info:
        api._register_tester(api.LoginRequest(
            email="new@example.com", password="long-enough-password"
        ))
    assert exc_info.value.status_code == 403


def test_cli_register_creates_session_without_cloudflare_locally(monkeypatch):
    from smart_extract.cli import main as cli
    from smart_extract.cli.client import LoginResult

    seen = {}

    class FakeClient:
        def __init__(self, api_url, cloudflare_token=None):
            seen["client"] = (api_url, cloudflare_token)

        def register(self, email, password):
            seen["credentials"] = (email, password)
            return LoginResult(
                access_token="new-token",
                expires_at="2030-01-01T00:00:00+00:00",
                user={"id": "w", "email": email, "role": "tester"},
            )

    monkeypatch.setattr(cli, "RemoteClient", FakeClient)
    monkeypatch.setattr(cli.getpass, "getpass", lambda *a: "long-enough-password")
    monkeypatch.setattr(cli, "save_session", lambda value: seen.setdefault("session", value))
    assert cli.main([
        "register", "new@example.com", "--api-url", "http://127.0.0.1:8000"
    ]) == 0
    assert seen["credentials"] == ("new@example.com", "long-enough-password")
    assert seen["session"].role == "tester"
