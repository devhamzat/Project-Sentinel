"""Phase 0: verify the Neo4j connection.

Run from the repo root:
    python -m smart_extract.scripts.check_neo4j

Prints the server version and a trivial round-trip query result, or a clear
error if the database is unreachable / credentials are wrong.
"""

from __future__ import annotations

import sys

from neo4j import GraphDatabase
from neo4j.exceptions import AuthError, ServiceUnavailable

from smart_extract.config import settings


def check() -> bool:
    """Return True if Neo4j is reachable and answers a query, else False."""
    print(f"Connecting to {settings.neo4j_uri} as {settings.neo4j_user} ...")
    driver = None
    try:
        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        driver.verify_connectivity()
        with driver.session() as session:
            value = session.run("RETURN 1 AS ok").single()["ok"]
        print(f"OK - Neo4j answered round-trip query (RETURN 1 -> {value}).")
        return True
    except AuthError:
        print("FAILED - authentication error. Check NEO4J_USER / NEO4J_PASSWORD in .env.")
        return False
    except ServiceUnavailable:
        print(
            "FAILED - could not reach Neo4j. Is it running, and is NEO4J_URI correct?\n"
            f"  Tried: {settings.neo4j_uri}"
        )
        return False
    except Exception as exc:  # noqa: BLE001 - surface anything else clearly
        print(f"FAILED - unexpected error: {exc}")
        return False
    finally:
        if driver is not None:
            driver.close()


def main() -> int:
    return 0 if check() else 1


if __name__ == "__main__":
    sys.exit(main())
