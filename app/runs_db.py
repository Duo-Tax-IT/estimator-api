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
            config TEXT,
            settlement_date TEXT,
            prompt TEXT,
            response TEXT NOT NULL
        )"""
    )
    # Backfill columns added after a DB was created (throwaway store, no migrations).
    cols = [r[1] for r in conn.execute("PRAGMA table_info(runs)")]
    for col in ("address", "config", "settlement_date"):
        if col not in cols:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {col} TEXT")
    return conn


def save_run(rp_id, model, reasoning_effort, temperature, label, prompt, response,
             address=None, config=None, settlement_date=None):
    """Append one estimate run for later comparison."""
    with _conn() as conn:
        conn.execute(
            "INSERT INTO runs (created_at, rp_id, model, reasoning_effort,"
            " temperature, label, address, config, settlement_date, prompt, response)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                rp_id, model, reasoning_effort, temperature, label, address,
                json.dumps(config) if config else None, settlement_date,
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
            f" label, address, config, settlement_date, prompt, response"
            f" FROM runs {where} ORDER BY id DESC",
            params,
        ).fetchall()
    return [
        {
            "id": r[0], "created_at": r[1], "rp_id": r[2], "model": r[3],
            "reasoning_effort": r[4], "temperature": r[5], "label": r[6],
            "address": r[7], "config": json.loads(r[8]) if r[8] else None,
            "settlement_date": r[9], "prompt": r[10], "response": json.loads(r[11]),
        }
        for r in rows
    ]
