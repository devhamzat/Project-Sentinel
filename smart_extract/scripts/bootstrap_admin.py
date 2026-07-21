"""Create the first Sentinel administrator from a trusted server shell."""

from __future__ import annotations

import argparse
import getpass

from smart_extract.auth import AuthError, create_user
from smart_extract.graph.store import open_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create Sentinel's first administrator (run on the API host)."
    )
    parser.add_argument("email")
    args = parser.parse_args(argv)

    with open_store() as store:
        if store.list_users():
            print("FAILED - accounts already exist; use 'sentinel users add' remotely.")
            return 1

    password = getpass.getpass("Password (12+ characters): ")
    if password != getpass.getpass("Confirm password: "):
        print("FAILED - passwords do not match.")
        return 1
    try:
        user = create_user(args.email, password, "admin")
    except AuthError as exc:
        print(f"FAILED - {exc}")
        return 1
    print(f"OK - created first administrator {user.email} ({user.id}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
