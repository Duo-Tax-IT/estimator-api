"""One-off: copy the live app's SQLite runs.db (runs, learning_sessions,
chat_messages, applied_recs) into Postgres, preserving ids, so the web app's
history carries over after runs_db.py switched to Postgres. Reads SQLite only;
the live file is never modified. Idempotent on id (safe to re-run).

    python -m app.migrate_runs_db
"""
import sqlite3
from pathlib import Path

from . import runs_db

_SQLITE = Path(__file__).parent.parent / "runs.db"

# table -> (its columns, and whether id is a serial sequence to reset afterwards)
_TABLES = {
    "runs": (("id", "created_at", "rp_id", "model", "reasoning_effort", "temperature",
              "label", "address", "config", "settlement_date", "prompt", "response",
              "duration_ms"), True),
    "learning_sessions": (("id", "created_at", "run_id", "expert_input", "analysis"), True),
    "chat_messages": (("id", "created_at", "run_id", "role", "content"), True),
    "applied_recs": (("session_id", "rec_index"), False),
}


def _sqlite_rows(table, cols):
    conn = sqlite3.connect(_SQLITE)
    try:
        return conn.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
    finally:
        conn.close()


def migrate() -> dict:
    counts = {}
    with runs_db._conn() as pg:  # also creates the tables on first use
        for table, (cols, has_serial) in _TABLES.items():
            rows = _sqlite_rows(table, cols)
            placeholders = ", ".join(["%s"] * len(cols))
            conflict = "id" if has_serial else "session_id, rec_index"
            for row in rows:
                pg.execute(
                    f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
                    f" ON CONFLICT ({conflict}) DO NOTHING",
                    row,
                )
            if has_serial:  # advance the id sequence past the copied rows
                pg.execute(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'),"
                    f" COALESCE((SELECT max(id) FROM {table}), 1))"
                )
            counts[table] = len(rows)
    return counts


if __name__ == "__main__":
    print(migrate())
