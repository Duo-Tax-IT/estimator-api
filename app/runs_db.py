import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# Temp/throwaway store for estimate runs, used to compare versions while tuning.
# Lives at the service root; git-ignored.
_DB = Path(__file__).parent.parent / "runs.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            rp_id TEXT NOT NULL,
            model TEXT,
            reasoning_effort TEXT,
            temperature REAL,
            label TEXT,
            address TEXT,
            prompt TEXT,
            response TEXT NOT NULL
        )"""
    )
    # Add `address` to DBs created before it existed (throwaway store, no migrations).
    cols = [r[1] for r in conn.execute("PRAGMA table_info(runs)")]
    if "address" not in cols:
        conn.execute("ALTER TABLE runs ADD COLUMN address TEXT")
    return conn


def save_run(rp_id, model, reasoning_effort, temperature, label, prompt, response, address=None):
    """Append one estimate run for later comparison."""
    with _conn() as conn:
        conn.execute(
            "INSERT INTO runs (created_at, rp_id, model, reasoning_effort,"
            " temperature, label, address, prompt, response)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                rp_id, model, reasoning_effort, temperature, label, address,
                prompt, json.dumps(response),
            ),
        )


def list_runs(rp_id=None) -> list[dict]:
    """Saved runs, newest first. All properties when rp_id is None."""
    where = "WHERE rp_id = ?" if rp_id else ""
    params = (rp_id,) if rp_id else ()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, created_at, rp_id, model, reasoning_effort, temperature,"
            f" label, address, prompt, response FROM runs {where} ORDER BY id DESC",
            params,
        ).fetchall()
    return [
        {
            "id": r[0], "created_at": r[1], "rp_id": r[2], "model": r[3],
            "reasoning_effort": r[4], "temperature": r[5], "label": r[6],
            "address": r[7], "prompt": r[8], "response": json.loads(r[9]),
        }
        for r in rows
    ]
