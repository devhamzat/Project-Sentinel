"""Authentication primitives and Neo4j-backed application users.

The first administrator is provisioned from a trusted server shell; subsequent
accounts use admin-protected API routes. There is deliberately no public
registration endpoint. Passwords use Python's scrypt implementation and
sessions are short-lived HMAC-signed tokens (HttpOnly cookies for browsers,
bearer tokens for the remote CLI).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from smart_extract.config import settings
from smart_extract.graph.store import open_store

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


class AuthError(RuntimeError):
    """Base class for authentication failures safe to show to a client."""


class InvalidCredentials(AuthError):
    """Raised when an email/password or session token is invalid."""


class AuthConfigurationError(AuthError):
    """Raised when deployment authentication settings are unsafe or missing."""


@dataclass(frozen=True)
class User:
    id: str
    email: str
    role: str = "tester"
    session_version: int = 1


def normalise_email(email: str) -> str:
    value = email.strip().lower()
    if len(value) > 254 or not _EMAIL.fullmatch(value):
        raise AuthError("Enter a valid email address.")
    return value


def validate_password(password: str) -> None:
    if len(password) < 12:
        raise AuthError("Password must be at least 12 characters.")
    if len(password.encode("utf-8")) > 1024:
        raise AuthError("Password is too long.")


def hash_password(password: str) -> str:
    validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R,
        p=_SCRYPT_P, dklen=32,
    )
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N,
        _SCRYPT_R,
        _SCRYPT_P,
        _b64(salt),
        _b64(digest),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=_unb64(salt), n=int(n), r=int(r),
            p=int(p), dklen=32,
        )
        return hmac.compare_digest(digest, _unb64(expected))
    except (ValueError, TypeError):
        return False


def create_user(email: str, password: str, role: str = "tester") -> User:
    email = normalise_email(email)
    if role not in {"admin", "tester"}:
        raise AuthError("Role must be 'admin' or 'tester'.")
    password_hash = hash_password(password)
    user_id = secrets.token_urlsafe(18)
    with open_store() as store:
        store.ensure_constraints()
        try:
            row = store.create_user(user_id, email, password_hash, role)
        except Exception as exc:
            if "already exists" in str(exc).lower() or "constraint" in str(exc).lower():
                raise AuthError(f"An account for {email} already exists.") from exc
            raise
    return _user_from_row(row)


def authenticate(email: str, password: str) -> User:
    try:
        email = normalise_email(email)
    except AuthError as exc:
        raise InvalidCredentials("Invalid email or password.") from exc
    with open_store() as store:
        row = store.get_user_by_email(email)
    if not row or not row.get("active", True):
        raise InvalidCredentials("Invalid email or password.")
    if not verify_password(password, row.get("password_hash", "")):
        raise InvalidCredentials("Invalid email or password.")
    return _user_from_row(row)


def issue_session(user: User, now: int | None = None) -> str:
    secret = _auth_secret()
    issued = int(time.time() if now is None else now)
    payload = {
        "sub": user.id,
        "email": user.email,
        "role": user.role,
        "ver": user.session_version,
        "iat": issued,
        "exp": issued + settings.auth_token_ttl_minutes * 60,
        "iss": "project-sentinel",
    }
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = f"{_json64(header)}.{_json64(payload)}"
    signature = hmac.new(
        secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{signing_input}.{_b64(signature)}"


def user_from_session(token: str, now: int | None = None) -> User:
    payload = _verified_session_payload(token, now=now)
    user_id = str(payload["sub"])
    token_version = int(payload["ver"])

    with open_store() as store:
        row = store.get_user_by_id(user_id)
    if not row or not row.get("active", True):
        raise InvalidCredentials("Session is invalid or expired.")
    user = _user_from_row(row)
    if user.session_version != token_version:
        raise InvalidCredentials("Session is invalid or expired.")
    return user


def session_expires_at(token: str, now: int | None = None) -> datetime:
    """Return a verified session's UTC expiry time without loading its user."""
    payload = _verified_session_payload(token, now=now)
    return datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)


def _verified_session_payload(
    token: str, now: int | None = None
) -> dict[str, Any]:
    try:
        header_part, payload_part, signature_part = token.split(".", 2)
        signing_input = f"{header_part}.{payload_part}"
        expected = hmac.new(
            _auth_secret().encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected, _unb64(signature_part)):
            raise InvalidCredentials("Session is invalid or expired.")
        header = json.loads(_unb64(header_part))
        payload: dict[str, Any] = json.loads(_unb64(payload_part))
        current = int(time.time() if now is None else now)
        if header != {"alg": "HS256", "typ": "JWT"}:
            raise InvalidCredentials("Session is invalid or expired.")
        if payload.get("iss") != "project-sentinel" or int(payload["exp"]) <= current:
            raise InvalidCredentials("Session is invalid or expired.")
        str(payload["sub"])
        int(payload["ver"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise InvalidCredentials("Session is invalid or expired.") from exc
    return payload


def _auth_secret() -> str:
    secret = settings.auth_secret.get_secret_value()
    if len(secret) < 32 or secret == "replace-this-with-a-random-secret":
        raise AuthConfigurationError(
            "AUTH_SECRET must be set to a random value of at least 32 characters."
        )
    return secret


def _user_from_row(row: dict[str, Any]) -> User:
    return User(
        id=str(row["id"]), email=str(row["email"]), role=str(row["role"]),
        session_version=int(row.get("session_version", 1)),
    )


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _json64(value: dict[str, Any]) -> str:
    return _b64(json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8"))
