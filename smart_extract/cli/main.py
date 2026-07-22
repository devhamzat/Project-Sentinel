"""Remote command-line client for a deployed Project Sentinel API.

The CLI never opens Neo4j or runs extraction locally.  It keeps one encrypted
OS-credential-store session and sends every command to the configured API.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from datetime import datetime

from smart_extract.cli.client import (
    RemoteAuthenticationError,
    RemoteClient,
    RemoteError,
    cloudflare_access_login,
    normalise_api_url,
    should_use_cloudflare,
)
from smart_extract.cli.session import (
    CliSession,
    CliSessionError,
    clear_session,
    load_session,
    save_session,
)
DEFAULT_API_URL = os.environ.get("SENTINEL_API_URL", "http://127.0.0.1:8000")


def _client(session: CliSession) -> RemoteClient:
    return RemoteClient(
        session.api_url,
        sentinel_token=session.sentinel_token,
        cloudflare_token=session.cloudflare_token,
    )


def _require_session(*, admin: bool = False) -> CliSession | None:
    try:
        session = load_session()
    except CliSessionError as exc:
        print(f"FAILED - {exc}")
        return None
    if not session:
        print("FAILED - no active session. Run 'sentinel login' first.")
        return None
    if admin and session.role != "admin":
        print("FAILED - this command requires an admin account.")
        return None
    return session


def _report_error(exc: RemoteError) -> int:
    if isinstance(exc, RemoteAuthenticationError):
        try:
            clear_session()
        except CliSessionError:
            pass
        print(f"FAILED - {exc} Run 'sentinel login' again.")
    else:
        print(f"FAILED - {exc}")
    return 1


def _cmd_login(
    email: str | None,
    api_url: str,
    cloudflare: bool | None,
) -> int:
    try:
        api_url = normalise_api_url(api_url)
        use_cloudflare = should_use_cloudflare(api_url) if cloudflare is None else cloudflare
        cf_token = None
        if use_cloudflare:
            print(f"Opening Cloudflare Access for {api_url} ...")
            cf_token = cloudflare_access_login(api_url)
        email = email or input("Email: ").strip()
        password = getpass.getpass(f"Sentinel password for {email}: ")
        result = RemoteClient(api_url, cloudflare_token=cf_token).login(email, password)
        session = CliSession(
            api_url=api_url,
            sentinel_token=result.access_token,
            cloudflare_token=cf_token,
            email=str(result.user["email"]),
            role=str(result.user["role"]),
            expires_at=result.expires_at,
        )
        save_session(session)
    except (RemoteError, CliSessionError, KeyError) as exc:
        print(f"FAILED - {exc}")
        return 1
    print(f"OK - signed in as {session.email} ({session.role}).")
    print(f"API: {session.api_url}")
    print(f"Session expires {_display_expiry(session.expires_at)}.")
    return 0


def _cmd_register(
    email: str | None,
    api_url: str,
    cloudflare: bool | None,
) -> int:
    try:
        api_url = normalise_api_url(api_url)
        use_cloudflare = should_use_cloudflare(api_url) if cloudflare is None else cloudflare
        cf_token = None
        if use_cloudflare:
            print(f"Opening Cloudflare Access for {api_url} ...")
            cf_token = cloudflare_access_login(api_url)
        email = email or input("Email: ").strip()
        password = _password_pair()
        if password is None:
            return 1
        result = RemoteClient(api_url, cloudflare_token=cf_token).register(email, password)
        session = CliSession(
            api_url=api_url,
            sentinel_token=result.access_token,
            cloudflare_token=cf_token,
            email=str(result.user["email"]),
            role=str(result.user["role"]),
            expires_at=result.expires_at,
        )
        save_session(session)
    except (RemoteError, CliSessionError, KeyError) as exc:
        print(f"FAILED - {exc}")
        return 1
    print(f"OK - created and signed in as {session.email}.")
    print(f"API: {session.api_url}")
    return 0


def _cmd_logout() -> int:
    try:
        session = load_session()
        if session:
            try:
                _client(session).logout()
            except RemoteError:
                # Logout is primarily removal of the local bearer credential.
                pass
        removed = clear_session()
    except CliSessionError as exc:
        # A legacy locally-signed token cannot be decoded as a remote session,
        # but logout must still be able to remove it during migration.
        try:
            removed = clear_session()
        except CliSessionError:
            print(f"FAILED - {exc}")
            return 1
    print("OK - signed out." if removed else "No active CLI session.")
    return 0


def _cmd_whoami(session: CliSession) -> int:
    try:
        user = _client(session).me()
    except RemoteError as exc:
        return _report_error(exc)
    print(f"Email:   {user['email']}")
    print(f"Role:    {user['role']}")
    print(f"API:     {session.api_url}")
    print(f"Expires: {_display_expiry(session.expires_at)}")
    return 0


def _cmd_ingest(path: str, session: CliSession) -> int:
    try:
        result = _client(session).ingest(path)
    except RemoteError as exc:
        return _report_error(exc)
    counts = result["counts"]
    label = result.get("arxiv_id") or result.get("title") or result.get("source_path")
    print(f"Read {result['source_kind']} source (id: {label}).")
    print(f"  title:    {result.get('title') or '(none)'}")
    print(f"  authors:  {counts['authors']}   affiliations: {counts['affiliations']}")
    print(
        f"  keywords: {counts['keywords']}   datasets: {counts['datasets']} (USES)   "
        f"methods: {counts['methods']}"
    )
    validation = result.get("validation", {})
    if not validation.get("spacy_validated", True):
        print("  note: spaCy model not installed; author/affiliation validation skipped.")
    for field in ("dropped_datasets", "dropped_authors", "dropped_affiliations"):
        if validation.get(field):
            print(f"  filtered {field.replace('dropped_', '')}: {validation[field]}")
    if result.get("chunks_error"):
        print(f"  note: semantic index skipped - {result['chunks_error']}")
    elif result.get("chunks_indexed"):
        print(f"  indexed {result['chunks_indexed']} passage(s) for semantic search.")
    print(
        f"OK - stored Paper '{result.get('title') or label}' with "
        f"{counts['authors']} author(s), {counts['datasets']} dataset(s)."
    )
    return 0


def _cmd_ask(question: str, session: CliSession) -> int:
    try:
        result = _client(session).ask(question)
    except RemoteError as exc:
        return _report_error(exc)
    if result.get("answer"):
        print(result["answer"] + "\n")
    print(f"Cypher: {result['cypher']}")
    if not result["rows"]:
        print("(no rows)")
        return 0
    print()
    for row in result["rows"]:
        print("  " + ", ".join(f"{key}={value}" for key, value in row.items()))
    print(f"\n{len(result['rows'])} row(s).")
    return 0


def _cmd_search(query: str, k: int, session: CliSession) -> int:
    try:
        result = _client(session).search(query, k)
    except RemoteError as exc:
        return _report_error(exc)
    if result.get("answer"):
        print(result["answer"] + "\n")
    if not result["chunks"]:
        print("(no matching passages)")
        return 0
    for chunk in result["chunks"]:
        label = f" (arXiv {chunk['arxiv_id']})" if chunk.get("arxiv_id") else ""
        locator = f", p.{chunk['page']}" if chunk.get("page") else ""
        preview = " ".join(chunk["text"].split())
        if len(preview) > 300:
            preview = preview[:300] + "..."
        print(
            f"[{chunk['score']:.3f}] {chunk['title']}{label} - "
            f"passage #{chunk['chunk_index']}{locator}"
        )
        print(f"    {preview}\n")
    return 0


def _cmd_stats(session: CliSession) -> int:
    try:
        counts = _client(session).stats()
    except RemoteError as exc:
        return _report_error(exc)
    for key, count in counts.items():
        print(f"  {key:16} {count}")
    return 0


def _password_pair(prompt: str = "Password (12+ characters): ") -> str | None:
    password = getpass.getpass(prompt)
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("FAILED - passwords do not match.")
        return None
    return password


def _cmd_users(args: argparse.Namespace, session: CliSession) -> int:
    client = _client(session)
    try:
        if args.user_command == "list":
            rows = client.list_users()
            if not rows:
                print("(no accounts)")
            for row in rows:
                status = "active" if row.get("active", True) else "disabled"
                print(f"{row['email']:36} {row['role']:8} {status:8} {row['id']}")
            return 0
        if args.user_command == "add":
            password = _password_pair()
            if password is None:
                return 1
            user = client.add_user(args.email, password, args.role)
            print(f"OK - created {user['role']} account {user['email']} ({user['id']}).")
            return 0
        if args.user_command == "claim":
            result = client.claim_user_papers(args.email)
            print(f"OK - assigned {result['claimed']} previously unowned paper(s) to {args.email}.")
            return 0
        if args.user_command == "reset-password":
            password = _password_pair("New password (12+ characters): ")
            if password is None:
                return 1
            client.reset_user_password(args.email, password)
            print(f"OK - reset the password for {args.email}.")
            return 0
        if args.user_command in {"disable", "enable"}:
            active = args.user_command == "enable"
            client.set_user_active(args.email, active)
            print(f"OK - {'enabled' if active else 'disabled'} {args.email}.")
            return 0
    except RemoteError as exc:
        return _report_error(exc)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sentinel",
        description="Remote client for a deployed Project Sentinel API.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="start a secure remote CLI session")
    login.add_argument("email", nargs="?", help="Sentinel account email")
    login.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help="API root, e.g. https://sentinel.example.com/api",
    )
    login.add_argument(
        "--cloudflare",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="use Cloudflare Access (automatic for non-local URLs)",
    )
    register = sub.add_parser("register", help="create a tester account and sign in")
    register.add_argument("email", nargs="?", help="new account email")
    register.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help="API root, e.g. https://sentinel.example.com/api",
    )
    register.add_argument(
        "--cloudflare",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="use Cloudflare Access (automatic for non-local URLs)",
    )
    sub.add_parser("logout", help="remove the active remote session")
    sub.add_parser("whoami", help="verify and show the active remote account")

    ingest = sub.add_parser("ingest", help="upload a PDF or photo for ingestion")
    ingest.add_argument("path")
    ask = sub.add_parser("ask", help="ask a natural-language graph question")
    ask.add_argument("question")
    search = sub.add_parser("search", help="find passages by meaning")
    search.add_argument("query")
    search.add_argument("-k", type=int, default=5, help="number of passages (default 5)")
    sub.add_parser("stats", help="show active-workspace counts")

    users = sub.add_parser("users", help="manage deployment accounts (admin only)")
    user_sub = users.add_subparsers(dest="user_command", required=True)
    add = user_sub.add_parser("add", help="create an account as an administrator")
    add.add_argument("email")
    add.add_argument("--role", choices=("admin", "tester"), default="tester")
    user_sub.add_parser("list", help="list provisioned accounts")
    claim = user_sub.add_parser("claim", help="assign legacy unowned papers")
    claim.add_argument("email")
    reset = user_sub.add_parser("reset-password", help="replace an account password")
    reset.add_argument("email")
    disable = user_sub.add_parser("disable", help="revoke an account immediately")
    disable.add_argument("email")
    enable = user_sub.add_parser("enable", help="re-enable a revoked account")
    enable.add_argument("email")
    return parser


def _display_expiry(value: str) -> str:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime(
            "%Y-%m-%d %H:%M %Z"
        )
    except ValueError:
        return value


def _force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    args = build_parser().parse_args(argv)
    if args.command == "login":
        return _cmd_login(args.email, args.api_url, args.cloudflare)
    if args.command == "register":
        return _cmd_register(args.email, args.api_url, args.cloudflare)
    if args.command == "logout":
        return _cmd_logout()
    session = _require_session(admin=args.command == "users")
    if not session:
        return 1
    if args.command == "whoami":
        return _cmd_whoami(session)
    if args.command == "ingest":
        return _cmd_ingest(args.path, session)
    if args.command == "ask":
        return _cmd_ask(args.question, session)
    if args.command == "search":
        return _cmd_search(args.query, args.k, session)
    if args.command == "stats":
        return _cmd_stats(session)
    if args.command == "users":
        return _cmd_users(args, session)
    return 1


if __name__ == "__main__":
    sys.exit(main())
