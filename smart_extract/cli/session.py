"""Secure storage for the remote CLI's single active session."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

_SERVICE = "project-sentinel-cli"
_ACCOUNT = "active-session"


class CliSessionError(RuntimeError):
    """Raised when the operating-system credential store is unavailable."""


@dataclass(frozen=True)
class CliSession:
    api_url: str
    sentinel_token: str
    cloudflare_token: str | None
    email: str
    role: str
    expires_at: str


def save_session(session: CliSession) -> None:
    try:
        keyring.set_password(
            _SERVICE,
            _ACCOUNT,
            json.dumps(asdict(session), separators=(",", ":")),
        )
    except KeyringError as exc:
        raise CliSessionError(
            "Could not save the session in the operating-system credential store."
        ) from exc


def load_session() -> CliSession | None:
    try:
        value = keyring.get_password(_SERVICE, _ACCOUNT)
    except KeyringError as exc:
        raise CliSessionError(
            "Could not read the session from the operating-system credential store."
        ) from exc
    if value is None:
        return None
    try:
        payload = json.loads(value)
        return CliSession(**payload)
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        raise CliSessionError(
            "The saved session uses the old local-CLI format. Run 'sentinel logout' "
            "and then 'sentinel login' to create a remote session."
        ) from exc


def clear_session() -> bool:
    try:
        if keyring.get_password(_SERVICE, _ACCOUNT) is None:
            return False
        keyring.delete_password(_SERVICE, _ACCOUNT)
        return True
    except PasswordDeleteError:
        return False
    except KeyringError as exc:
        raise CliSessionError(
            "Could not remove the session from the operating-system credential store."
        ) from exc
