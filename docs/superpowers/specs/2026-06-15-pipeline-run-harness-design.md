# Pipeline Run Harness — Design

**Date:** 2026-06-15
**Status:** Approved design, pending implementation

## Goal

Run any estimator pipeline (v1/v2/v3 and future versions) across the Salesforce
Opportunities, storing every output, then **benchmark each output against the
real user-entered data on that Opportunity** (the ground truth a person filled in
during Fillout). This is an iterative development loop ("run → score vs real data
→ tweak prompt → re-run") that continues until the new pipeline matches reality
well enough. The benchmark is estimate-vs-real-data — **not** pipeline-vs-pipeline
(though running multiple pipelines side by side is supported, each is scored
against the same real data).

## Non-goals

- No HTTP endpoint — the job is long-running (one vision pass per opp), so it
  runs as a CLI you invoke manually.
- No experiments/cohort table — the `version` string is enough grouping.
- No live Salesforce write-back — scores stay in `training.db`.

## Data sources

Each Salesforce Opportunity (`StageName = 'Fillout'` by default) carries the
inputs the estimator needs:

| Opportunity field           | Maps to (`EstimateRequest`) |
|-----------------------------|-----------------------------|
| `RPData_Property_ID__c`     | `rp_id` (required — no id → `skipped`) |
| `Settlement_Date__c`        | `settlement_date`           |
| `Build_Date_OC_Date__c`     | `build_year` (year extracted)|
| `Property_Address__c`       | `address`                   |

The full 92-field record is stored as a snapshot for reproducibility.

## Storage — Postgres (`TRAINING_DB_URL`)

Postgres, not SQLite: the harness is run by **parallel workers**, which means
concurrent writers — SQLite's single-writer lock would throw "database is locked".
All DB access is isolated in `store.py`, so the backend choice doesn't leak into
the runner. `JSONB` columns also give cheap analytics later (`estimate->>'Total'`).

### Table `opportunities` — labelled dataset, one row per opp

| column          | notes                                  |
|-----------------|----------------------------------------|
| `opportunity_id`| TEXT PRIMARY KEY (Salesforce Id)       |
| `job_number`    | TEXT                                   |
| `rp_id`         | TEXT (`RPData_Property_ID__c`)         |
| `snapshot`      | JSON — all 92 SF fields                |
| `synced_at`     | TEXT (ISO UTC)                         |

Stored **once** per opp. Re-running upserts the snapshot (refreshes ground truth)
without duplicating 92 fields on every estimate.

### Table `estimates` — iteration log, many rows per opp

| column          | notes                                          |
|-----------------|------------------------------------------------|
| `id`            | INTEGER PK AUTOINCREMENT                        |
| `opportunity_id`| TEXT → `opportunities.opportunity_id`           |
| `pipeline`      | TEXT — `v1` \| `v2` \| `v3` \| …                |
| `version`       | TEXT — `"{pipeline}@{hash}"`, identity of the run|
| `model`         | TEXT                                            |
| `estimate`      | JSON — the pipeline response (null on error)    |
| `status`        | TEXT — `ok` \| `error` \| `skipped`             |
| `error`         | TEXT — message when status ≠ ok                 |
| `score`         | REAL — nullable; filled by the scoring pass     |
| `score_detail`  | JSON — nullable; per-field comparison breakdown |
| `created_at`    | TEXT (ISO UTC)                                  |

`UNIQUE(opportunity_id, version)` is the idempotency key.

### Parallel workers — claim-then-finish

To split work across worker processes without a queue, each opp is claimed before
it runs: `claim_estimate` atomically upserts the row to `status='running'`
(`ON CONFLICT … DO UPDATE … WHERE status <> 'running'`). The row-level lock
serialises racing workers — the loser gets no row back and skips. The winner runs
the model, then `finish_estimate` writes `ok`/`error`/`skipped`. Running the same
command in N processes therefore distributes the sweep. (Stale `running` rows from
a crashed worker are reclaimed with `--force`.)

### Scoring — estimate vs real data (separate pass)

A `score(version)` pass reads each `ok` estimate, pulls the real values from the
opportunity `snapshot`, computes the error, and writes `score` + `score_detail`.
Kept separate from the run loop so it can be re-run/retuned without re-calling the
model, and so the run loop isn't blocked on a metric definition.

**Two things are scored** (the pipeline's key outputs, in the v3 output shape):

| Pipeline output | Real anchor (Opportunity field) | Metric                         |
|-----------------|---------------------------------|--------------------------------|
| Total build cost| `BuildCost__c`                  | abs % error                    |
| Renovation list | `renovation_build_notes__c`     | qualitative / list overlap     |

`score` holds the headline number (cost % error); `score_detail` holds the
per-output breakdown incl. the renovation-list comparison.

### `version` derivation

`version = f"{pipeline}@{sha[:8]}"` where `sha` hashes the pipeline's prompt
file(s) + model name. Editing a prompt changes the hash → new version → fresh
sweep, with the prior version's rows retained for side-by-side comparison.

## Modules

### `app/opportunities/__init__.py` (done)
`list_opportunities(stage="Fillout")` + `get_opportunity` + `DEFAULT_FIELDS`.

### `app/opportunities/store.py` (~70 lines)
Owns `training.db`: schema creation, `upsert_opportunity(record)`,
`save_estimate(...)`, `estimate_exists(opportunity_id, version)`,
`set_score(estimate_id, score, detail)`, `list_estimates(version=None)`.

### `app/opportunities/scoring.py` (~40 lines)
`score(version)` — for each `ok` estimate, compare against the opportunity
`snapshot`'s real values and write `score` + `score_detail`. Comparison logic
isolated here so the target field / metric can change without touching the runner.

### `app/opportunities/runner.py` (~50 lines)
```
run(pipeline="v3", stage="Fillout", force=False, limit=None) -> summary

  version = derive_version(pipeline, model)
  for opp in list_opportunities(stage):
      upsert_opportunity(opp)
      if not force and estimate_exists(opp.id, version) == ok: continue
      rp_id = opp["RPData_Property_ID__c"]
      if not rp_id: save_estimate(status="skipped", error="no RPData id"); continue
      req = map_to_request(opp)
      try:    result = BUILDERS[pipeline](req)
      except EstimatorError as e: save_estimate(status="error", error=str(e)); continue
      save_estimate(status="ok", estimate=result)
  return {total, ran, skipped, errors}
```
`BUILDERS = {"v1": build_full_estimate, "v2": build_estimate_v2, "v3": build_estimate_v3}`.
A single opp failure never aborts the batch.

CLI entry: `python -m app.opportunities.runner --pipeline v3 [--stage Fillout] [--force] [--limit N]`.

## Legacy import (one-off) — `app/opportunities/migrate_legacy.py`

Copies the live app's SQLite tuning data into Postgres for comparison/training,
without touching the live app (it keeps using `runs.db`):
- `runs` (86) → `legacy_estimates` — past v1/v2/v3 outputs; pipeline inferred from
  the response `Meta`; best-effort `opportunity_id` link where `rp_id` matches a
  synced opp's `RPData_Property_ID__c`.
- `learning_sessions` (9) → `legacy_learning` — expert ground-truth + AI analysis.
- `chat_messages` / `applied_recs` skipped (UI state, not training data).

Idempotent on the original row id (re-run to refresh opportunity links as more
opps sync). `python -m app.opportunities.migrate_legacy`.

## Continuous loop

```
edit new pipeline's prompt
        │
        ▼
version auto-bumps (prompt hash changes)
        │
        ▼
python -m app.opportunities.runner --pipeline v4
        │
        ▼
new rows in estimates; old version's rows kept
        │
        ▼
compare v4 output vs v3 on the same opps → tweak → repeat until right
```
```
