"""Apply db/migrations/*.sql in order, once each (tracked in schema_migrations)."""

import sys

import psycopg

from .config import MIGRATIONS_DIR, settings


def apply(url: str | None = None, verbose: bool = True) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(url or settings.database_url, autocommit=True) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz DEFAULT now())"
        )
        done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            if verbose:
                print(f"applying {path.name}")
            # Each file runs in its own transaction except statements that can't (caggs);
            # psycopg in autocommit executes the multi-statement script as one implicit batch.
            conn.execute(path.read_text())
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
            applied.append(path.name)
    return applied


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else None
    names = apply(url)
    print(f"{len(names)} migration(s) applied")
