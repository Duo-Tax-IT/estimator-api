# v2 Estimation Orchestration

How a renovation estimate is produced by the v2 pipeline. The orchestrator is
`build_estimate_v2(req)` in `app/estimator_v2/__init__.py`; it only composes the
steps below — each step lives in its own file.

> Keep this doc in sync: whenever the flow changes (a step added/removed/reordered,
> a model call changed, the response shape changed), update this file in the same
> change. See "Maintenance" at the bottom.

## Flow at a glance

```
build_estimate_v2(req)
        │
        ▼
[ Step 0 ] fetch_v2_context ............ property, photos, catalog, gfa
        │
        ├──────────────┐  (run in parallel, same photos)
        ▼              ▼
[ Step 1 ] observe   [ Step 1b ] era ... two VISION passes over the photos
        └──────┬───────┘
               ▼
[ Step 1.5 ] support .................. text only: which observations are renovations?
               ▼
[ Step 2 ] match ...................... text only: ground supported findings to catalog
               ▼
        apply_year_guard ............. drop items dated at/before yearBuilt (original build)
               ▼
[ Step 3 ] price_validated ........... deterministic, NO model: BCI + repaint + pricing
               ▼
        assemble response ............ Renovations, totals, Stages, Meta
```

## Steps

| # | Step | File | Model? | Notes |
|---|------|------|--------|-------|
| 0 | context | `context.py` `fetch_v2_context` | no | Fetches property, photos (capped at `MAX_PHOTOS`, deduped), catalog trimmed to the property type (+ `library` keyed by `_id`), and `gfa`. Raises `ItemsFetchError` / `NoPhotosError`. |
| 1 | observe | `steps/observe.py` `run_observe` | **vision** | Describes what's visible per photo. Output: 1 `photoObservations` entry per photo, plus room-classifier `roomHints` and `sentPhotos` (Stages audit). |
| 1b | era | `steps/era.py` `run_era` | **vision** | Forensic dating of finishes. Output: `eraAnalysis`, **N entries per photo** (one per datable element). Gets no build year. |
| 1.5 | support | `steps/support.py` `run_support` | text | Judges which observations are renovation-supported, using observations + era + `yearBuilt`. Flags `shouldProceedToCatalogMatch`. |
| 2 | match | `steps/match.py` `run_match` | text | Grounds only the supported findings to catalog items. Output: `validatedCandidates`, `rejectedCandidates`, `summary`. |
| — | year guard | `price.py` `apply_year_guard` | no | Drops candidates dated `<= yearBuilt` (that's the original build, not a renovation). |
| 3 | price | `price.py` `price_validated` | no | Deterministic. BCI factor per state/year, internal-repaint assumption, expand whole-room matches to leaves, dedup, `price_items`, room-count scaling, owner split. |

Steps 1 and 1b run **concurrently** (`ThreadPoolExecutor(max_workers=2)`); the
slower one sets the wall-clock. Steps 1.5 and 2 run after both finish.

## The four model calls

All model I/O lives in `app/clients/openai_client.py`.

- **observe + era are vision calls** — the same photos are downloaded and sent to
  the model **twice** (once each), inlined as base64. They are **batched**
  `PHOTO_BATCH` photos per call (`_run_photo_batches`) and merged with one global
  `photoIndex`, so each call's output stays under the cap.
- **support + match are text-only** — no photos; they receive prior steps' JSON.
- Every call is capped at `MAX_OUTPUT_TOKENS`. Hitting it raises a `ModelError`
  that **names the stage** (e.g. "…hit the cap in renovation support…"), so you
  can tell which step overflowed.
- Gemini's "thinking" tokens are billed as output and **share the
  `MAX_OUTPUT_TOKENS` cap**. We do NOT cap thinking (it carries the judgment in
  era/support/match). Instead `PHOTO_BATCH` is kept small so each call's JSON is
  tiny and most of the cap stays free for reasoning.

Key knobs (`openai_client.py`):

| Constant | Value | Meaning |
|---|---|---|
| `MAX_PHOTOS` | 100 | Photos pulled into the pipeline / sent to the model |
| `PHOTO_BATCH` | 20 | Photos per vision call (observe/era split into batches) |
| `MAX_OUTPUT_TOKENS` | 65536 | Per-call output ceiling (shared by JSON **and** thinking) |

## Response shape (returned by `build_estimate_v2`)

- `Renovations`, `Renovations Total`
- `Property`, `GFA`, `Summary Description`, `Disclaimer`
- `Usage` — token counts + USD, summed across the four model calls. Includes
  `reasoning_tokens` (the thinking slice of `completion_tokens`) for benchmarking
- `Stages` — per-step output for debugging (observations, eraAnalysis,
  renovationSupport, roomHints, paintAssumption, candidates, toolInput, bci,
  roomScaling, photos)
- `Meta` — pipeline + prompt-version hashes (provenance for the learning loop)
- `Previous Owner Total` / `Current Owner Total` — only when `settlement_date` is set

## Errors

| Error | When |
|---|---|
| `ItemsFetchError` | catalog (megamind) returned nothing |
| `NoPhotosError` | no usable photos for the property |
| `ModelError` | a model call failed, was truncated, or returned unparseable JSON |

## File map

| File | Responsibility |
|---|---|
| `estimator_v2/__init__.py` | orchestrator `build_estimate_v2` + response assembly (`DISCLAIMER`, `_hash`) |
| `estimator_v2/context.py` | Step 0 upstream fetch |
| `estimator_v2/steps/{observe,era,support,match}.py` | the four model steps (`run_*`) |
| `estimator_v2/steps/parsing.py` | shared JSON parse (`_parse`) |
| `estimator_v2/price.py` | year guard + deterministic Step 3 pricing + internal-repaint |
| `estimator_v2/preview.py` | `preview_estimate_prompt_v2` (assembles the prompts for debugging) |
| `estimator_v2/playground.py` | `step_*` single-step runners for the playground UI |
| `clients/openai_client.py` | the actual model calls, photo batching, pricing tool |

## Maintenance

This doc reflects the orchestration as of the current code. When the flow changes,
update the relevant section here in the same change — the "Flow at a glance"
diagram, the "Steps" table, and the "Response shape" are the parts that drift.
