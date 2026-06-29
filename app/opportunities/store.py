"""Postgres store for the pipeline run harness.

Two tables: `opportunities` holds each opp's real-data snapshot once (benchmark
ground truth); `estimates` holds every pipeline run, keyed
`UNIQUE(opportunity_id, version)`.

Parallel-worker safe via claim-then-finish: a worker atomically claims an opp by
flipping its row to `running` (claim_estimate); only the winner runs the model and
records the outcome (finish_estimate). `score`/`score_detail` are reserved for a
later (prompt-driven) scoring pass and stay null until then.
"""
import re
from urllib.parse import unquote

import psycopg
from psycopg.types.json import Json

from ..config import get_settings


def _clean_address(raw: str | None) -> str | None:
    """Property_Address__c is a Salesforce formula field holding an HTML maps link.
    Pull the human address out of its `?q=<address>` part; fall back to stripping tags."""
    if not raw:
        return raw
    m = re.search(r'q=([^"&]+)', raw)
    return unquote(m.group(1)).strip() if m else re.sub(r"<[^>]+>", "", raw).strip()


def _href(raw: str | None) -> str | None:
    """Extract the URL from a Salesforce HTML-anchor field (e.g. RP_Data_Link__c)."""
    if not raw:
        return None
    m = re.search(r'href="([^"]+)"', raw)
    return m.group(1) if m else None


def _links(opportunity_id: str, snapshot: dict | None) -> dict:
    """Quick-preview links for a run: the Salesforce record + the RP Data property."""
    org = get_settings().salesforce_org_url.rstrip("/")
    return {
        "salesforce": f"{org}/lightning/r/Opportunity/{opportunity_id}/view",
        "caesar": f"https://caesar.duo.tax/Opportunity/{opportunity_id}",
        "rp_data": _href((snapshot or {}).get("RP_Data_Link__c")),
    }

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS opportunities (
        opportunity_id TEXT PRIMARY KEY,
        job_number TEXT,
        rp_id TEXT,
        snapshot JSONB NOT NULL,
        synced_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS estimates (
        id BIGSERIAL PRIMARY KEY,
        opportunity_id TEXT NOT NULL,
        pipeline TEXT NOT NULL,
        version TEXT NOT NULL,
        model TEXT,
        estimate JSONB,
        status TEXT NOT NULL,
        error TEXT,
        score DOUBLE PRECISION,
        score_detail JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (opportunity_id, version)
    )""",
)


def _conn() -> psycopg.Connection:
    url = get_settings().training_db_url
    if not url:
        raise RuntimeError("TRAINING_DB_URL is not set")
    return psycopg.connect(url)


def init_db() -> None:
    """Create the tables if they don't exist (idempotent)."""
    with _conn() as conn:
        for stmt in _SCHEMA:
            conn.execute(stmt)


def upsert_opportunity(record: dict) -> None:
    """Store/refresh one opportunity's ground-truth snapshot (the real user data)."""
    with _conn() as conn:
        conn.execute(
            "INSERT INTO opportunities (opportunity_id, job_number, rp_id, snapshot, synced_at)"
            " VALUES (%s, %s, %s, %s, now())"
            " ON CONFLICT (opportunity_id) DO UPDATE SET job_number=EXCLUDED.job_number,"
            " rp_id=EXCLUDED.rp_id, snapshot=EXCLUDED.snapshot, synced_at=EXCLUDED.synced_at",
            (record["Id"], record.get("Job_Number__c"), record.get("RPData_Property_ID__c"),
             Json(record)),
        )


def claim_estimate(opportunity_id, pipeline, version, model, force=False) -> bool:
    """Atomically claim (opp, version) for this worker by flipping the row to
    `running`. Returns True if claimed (caller runs the pipeline), False if another
    worker holds it or it's already `ok` (skip). `force` re-claims anything,
    including a stale `running` row left by a crashed/stopped worker.

    The row-level lock on the conflicting upsert serialises racing workers: the
    loser sees `status='running'` in the WHERE and gets no row back.
    """
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO estimates (opportunity_id, pipeline, version, model, status)"
            " VALUES (%s, %s, %s, %s, 'running')"
            " ON CONFLICT (opportunity_id, version) DO UPDATE SET status='running',"
            " model=EXCLUDED.model, estimate=NULL, error=NULL, created_at=now()"
            " WHERE %s OR (estimates.status <> 'running' AND estimates.status <> 'ok')"
            " RETURNING id",
            (opportunity_id, pipeline, version, model, force),
        )
        return cur.fetchone() is not None


def finish_estimate(opportunity_id, version, status, estimate=None, error=None) -> None:
    """Record the outcome of a claimed run (status: ok | error | skipped)."""
    with _conn() as conn:
        conn.execute(
            "UPDATE estimates SET status=%s, estimate=%s, error=%s, created_at=now()"
            " WHERE opportunity_id=%s AND version=%s",
            (status, Json(estimate) if estimate is not None else None, error,
             opportunity_id, version),
        )


def done_opportunity_ids() -> set[str]:
    """Opportunity ids that already have an estimate (any version/status), so a
    fresh batch can skip them and pull the next, never-processed opps."""
    with _conn() as conn:
        rows = conn.execute("SELECT DISTINCT opportunity_id FROM estimates").fetchall()
    return {r[0] for r in rows}


def list_estimate_summaries() -> list[dict]:
    """Lightweight list for the UI (no estimate JSON), newest first. Joins each
    estimate to its opportunity for the display address."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT e.id, e.opportunity_id, o.snapshot->>'Property_Address__c' AS address,"
            " e.pipeline, e.version, e.status, e.error, e.created_at"
            " FROM estimates e LEFT JOIN opportunities o USING (opportunity_id)"
            " ORDER BY e.id DESC"
        ).fetchall()
    cols = ("id", "opportunity_id", "address", "pipeline", "version", "status",
            "error", "created_at")
    out = [dict(zip(cols, r)) for r in rows]
    for o in out:
        o["address"] = _clean_address(o["address"])
    return out


def get_estimate(estimate_id: int) -> dict | None:
    """One estimate (full output) + its opportunity snapshot (ground truth), or None."""
    with _conn() as conn:
        r = conn.execute(
            "SELECT e.id, e.opportunity_id, e.pipeline, e.version, e.model, e.estimate,"
            " e.status, e.error, e.created_at, o.snapshot"
            " FROM estimates e LEFT JOIN opportunities o USING (opportunity_id)"
            " WHERE e.id = %s",
            (estimate_id,),
        ).fetchone()
    if not r:
        return None
    cols = ("id", "opportunity_id", "pipeline", "version", "model", "estimate",
            "status", "error", "created_at", "snapshot")
    out = dict(zip(cols, r))
    out["links"] = _links(out["opportunity_id"], out["snapshot"])
    return out


def list_estimates(version: str | None = None) -> list[dict]:
    """Stored estimates, newest first. All versions when version is None.
    JSONB columns come back already parsed into dicts/lists."""
    where = "WHERE version = %s" if version else ""
    params = (version,) if version else ()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, opportunity_id, pipeline, version, model, estimate, status, error,"
            f" score, score_detail, created_at FROM estimates {where} ORDER BY id DESC",
            params,
        ).fetchall()
    cols = ("id", "opportunity_id", "pipeline", "version", "model", "estimate", "status",
            "error", "score", "score_detail", "created_at")
    return [dict(zip(cols, r)) for r in rows]
