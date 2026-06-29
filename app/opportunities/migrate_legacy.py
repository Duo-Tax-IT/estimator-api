"""One-off importer: copy the live app's SQLite tuning data (runs.db) into the
training Postgres as read-only `legacy_*` tables, so past pipeline outputs and the
expert ground-truth sit next to the harness data for comparison/training.

Only COPIES — the live app keeps using runs.db untouched. Idempotent on the
original row id, so it's safe to re-run (e.g. after more opportunities sync, to
pick up newly matchable opportunity links).

    python -m app.opportunities.migrate_legacy
"""
from psycopg.types.json import Json

from .. import runs_db
from . import store

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS legacy_estimates (
        id BIGINT PRIMARY KEY,
        created_at TIMESTAMPTZ,
        rp_id TEXT,
        opportunity_id TEXT,
        pipeline TEXT,
        model TEXT,
        reasoning_effort TEXT,
        temperature DOUBLE PRECISION,
        label TEXT,
        address TEXT,
        settlement_date TEXT,
        prompt TEXT,
        estimate JSONB,
        duration_ms INTEGER
    )""",
    """CREATE TABLE IF NOT EXISTS legacy_learning (
        id BIGINT PRIMARY KEY,
        created_at TIMESTAMPTZ,
        run_id BIGINT,
        expert_input TEXT,
        analysis JSONB
    )""",
)


def _pipeline(response: dict) -> str:
    """Infer which pipeline produced a saved run from its response shape."""
    meta = response.get("Meta") or {}
    if meta.get("pipeline"):
        return meta["pipeline"]
    return "v2" if "Stages" in response else "v1"


def _match_opportunity(conn, rp_id: str | None) -> str | None:
    """Best-effort link: the opportunity whose snapshot has this rp_id, if synced."""
    if not rp_id:
        return None
    row = conn.execute(
        "SELECT opportunity_id FROM opportunities"
        " WHERE snapshot->>'RPData_Property_ID__c' = %s LIMIT 1",
        (rp_id,),
    ).fetchone()
    return row[0] if row else None


def migrate() -> dict:
    """Copy runs + learning sessions into Postgres. Returns counts."""
    store.init_db()  # ensure `opportunities` exists for the link lookup
    runs = runs_db.list_runs()
    sessions = runs_db.list_learning()
    with store._conn() as conn:
        for stmt in _SCHEMA:
            conn.execute(stmt)
        for r in runs:
            conn.execute(
                "INSERT INTO legacy_estimates (id, created_at, rp_id, opportunity_id, pipeline,"
                " model, reasoning_effort, temperature, label, address, settlement_date, prompt,"
                " estimate, duration_ms) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT (id) DO UPDATE SET opportunity_id=EXCLUDED.opportunity_id",
                (r["id"], r["created_at"], r["rp_id"], _match_opportunity(conn, r["rp_id"]),
                 _pipeline(r["response"]), r["model"], r["reasoning_effort"], r["temperature"],
                 r["label"], r["address"], r["settlement_date"], r["prompt"],
                 Json(r["response"]), r["duration_ms"]),
            )
        for s in sessions:
            conn.execute(
                "INSERT INTO legacy_learning (id, created_at, run_id, expert_input, analysis)"
                " VALUES (%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
                (s["id"], s["created_at"], s["run_id"], s["expert_input"], Json(s["analysis"])),
            )
        linked = conn.execute(
            "SELECT count(*) FROM legacy_estimates WHERE opportunity_id IS NOT NULL"
        ).fetchone()[0]
    return {"runs": len(runs), "learning": len(sessions), "linked_to_opportunity": linked}


if __name__ == "__main__":
    print(migrate())
