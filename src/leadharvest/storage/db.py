"""SQLite connection and versioned migrations."""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path


def _load_migrations() -> list[tuple[int, str]]:
    """storage/migrations/NNN_name.sql, applied in order. Add files; never edit applied ones."""
    folder = resources.files("leadharvest.storage.migrations")
    found = []
    for entry in folder.iterdir():
        name = entry.name
        if name.endswith(".sql") and name[:3].isdigit():
            found.append((int(name[:3]), entry.read_text("utf-8")))
    return sorted(found)


MIGRATIONS: list[tuple[int, str]] = _load_migrations()


def connect(path: Path | str) -> sqlite3.Connection:
    """Open the database, apply pragmas, and run pending migrations.

    One connection per thread. Foreign keys must be enabled per connection (SQLite default: off).
    """
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    migrate(conn)
    return conn


def current_version(conn: sqlite3.Connection) -> int:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return int(row[0] or 0)


def migrate(conn: sqlite3.Connection) -> int:
    version = current_version(conn)
    for target, sql in MIGRATIONS:
        if target <= version:
            continue
        conn.execute("BEGIN")
        try:
            for statement in _split_sql(sql):
                conn.execute(statement)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (target,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        version = target
    return version


def _split_sql(sql: str) -> list[str]:
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]
