import json
from datetime import datetime, timezone

import psycopg

from .config import get_settings

# Store for estimate runs, the learning loop, and diagnostic chat. Lives in the
# same Postgres as the training harness (TRAINING_DB_URL); separate tables.
_initialized = False

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS runs (
        id BIGSERIAL PRIMARY KEY,
        created_at TEXT NOT NULL,
        rp_id TEXT NOT NULL,
        model TEXT,
        reasoning_effort TEXT,
        temperature DOUBLE PRECISION,
        label TEXT,
        address TEXT,
        config TEXT,
        settlement_date TEXT,
        prompt TEXT,
        response TEXT NOT NULL,
        duration_ms INTEGER
    )""",
    """CREATE TABLE IF NOT EXISTS learning_sessions (
        id BIGSERIAL PRIMARY KEY,
        created_at TEXT NOT NULL,
        run_id BIGINT NOT NULL,
        expert_input TEXT NOT NULL,
        analysis TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS chat_messages (
        id BIGSERIAL PRIMARY KEY,
        created_at TEXT NOT NULL,
        run_id BIGINT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS applied_recs (
        session_id BIGINT NOT NULL,
        rec_index INTEGER NOT NULL,
        PRIMARY KEY (session_id, rec_index)
    )""",
)


def _conn() -> psycopg.Connection:
    """Connect to Postgres, creating the tables once per process (idempotent).
    The connection commits + closes when used as a `with` context."""
    global _initialized
    conn = psycopg.connect(get_settings().training_db_url)
    if not _initialized:
        for stmt in _SCHEMA:
            conn.execute(stmt)
        conn.commit()
        _initialized = True
    return conn


def save_run(rp_id, model, reasoning_effort, temperature, label, prompt, response,
             address=None, config=None, settlement_date=None, duration_ms=None) -> int:
    """Append one estimate run for later comparison; returns its id."""
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO runs (created_at, rp_id, model, reasoning_effort,"
            " temperature, label, address, config, settlement_date, prompt, response,"
            " duration_ms)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                datetime.now(timezone.utc).isoformat(),
                rp_id, model, reasoning_effort, temperature, label, address,
                json.dumps(config) if config else None, settlement_date,
                prompt, json.dumps(response), duration_ms,
            ),
        )
        return cur.fetchone()[0]


def get_run(run_id) -> dict | None:
    """One saved run by id (with its full response), or None."""
    with _conn() as conn:
        r = conn.execute(
            "SELECT id, created_at, rp_id, model, reasoning_effort, temperature,"
            " label, address, config, settlement_date, prompt, response, duration_ms"
            " FROM runs WHERE id = %s",
            (run_id,),
        ).fetchone()
    if not r:
        return None
    return {
        "id": r[0], "created_at": r[1], "rp_id": r[2], "model": r[3],
        "reasoning_effort": r[4], "temperature": r[5], "label": r[6],
        "address": r[7], "config": json.loads(r[8]) if r[8] else None,
        "settlement_date": r[9], "prompt": r[10], "response": json.loads(r[11]),
        "duration_ms": r[12],
    }


def save_learning(run_id, expert_input, analysis) -> int:
    """Append one learning session (expert ground truth + AI analysis); returns id."""
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO learning_sessions (created_at, run_id, expert_input, analysis)"
            " VALUES (%s, %s, %s, %s) RETURNING id",
            (datetime.now(timezone.utc).isoformat(), run_id, expert_input,
             json.dumps(analysis)),
        )
        return cur.fetchone()[0]


def list_learning(run_id=None) -> list[dict]:
    """Saved learning sessions, newest first. All runs when run_id is None."""
    where = "WHERE run_id = %s" if run_id else ""
    params = (run_id,) if run_id else ()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, created_at, run_id, expert_input, analysis"
            f" FROM learning_sessions {where} ORDER BY id DESC",
            params,
        ).fetchall()
    return [
        {"id": r[0], "created_at": r[1], "run_id": r[2], "expert_input": r[3],
         "analysis": json.loads(r[4])}
        for r in rows
    ]


def save_chat_message(run_id, role, content) -> int:
    """Append one chat message (role: 'user' | 'assistant') for a run; returns id."""
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO chat_messages (created_at, run_id, role, content)"
            " VALUES (%s, %s, %s, %s) RETURNING id",
            (datetime.now(timezone.utc).isoformat(), run_id, role, content),
        )
        return cur.fetchone()[0]


def list_chat_messages(run_id) -> list[dict]:
    """A run's chat thread, oldest first."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, created_at, role, content FROM chat_messages"
            " WHERE run_id = %s ORDER BY id ASC",
            (run_id,),
        ).fetchall()
    return [
        {"id": r[0], "created_at": r[1], "role": r[2], "content": r[3]} for r in rows
    ]


def list_runs(rp_id=None) -> list[dict]:
    """Saved runs, newest first. All properties when rp_id is None."""
    where = "WHERE rp_id = %s" if rp_id else ""
    params = (rp_id,) if rp_id else ()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, created_at, rp_id, model, reasoning_effort, temperature,"
            f" label, address, config, settlement_date, prompt, response, duration_ms"
            f" FROM runs {where} ORDER BY id DESC",
            params,
        ).fetchall()
    return [
        {
            "id": r[0], "created_at": r[1], "rp_id": r[2], "model": r[3],
            "reasoning_effort": r[4], "temperature": r[5], "label": r[6],
            "address": r[7], "config": json.loads(r[8]) if r[8] else None,
            "settlement_date": r[9], "prompt": r[10], "response": json.loads(r[11]),
            "duration_ms": r[12],
        }
        for r in rows
    ]


def list_applied() -> list[str]:
    """Keys ("sessionId:recIndex") of recommendations marked applied."""
    with _conn() as conn:
        rows = conn.execute("SELECT session_id, rec_index FROM applied_recs").fetchall()
    return [f"{r[0]}:{r[1]}" for r in rows]


def set_applied(session_id, rec_index, applied) -> None:
    """Mark (applied=True) or unmark one recommendation as applied; idempotent."""
    with _conn() as conn:
        if applied:
            conn.execute(
                "INSERT INTO applied_recs (session_id, rec_index) VALUES (%s, %s)"
                " ON CONFLICT (session_id, rec_index) DO NOTHING",
                (session_id, rec_index),
            )
        else:
            conn.execute(
                "DELETE FROM applied_recs WHERE session_id = %s AND rec_index = %s",
                (session_id, rec_index),
            )
