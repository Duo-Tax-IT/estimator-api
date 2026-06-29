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
        ▼
   prepare_photos ...................... download + room-classify every photo ONCE (parallel)
        │
        ├──────────────┐  (run in parallel, reuse the prepared photos)
        ▼              ▼
[ Step 1 ] observe   [ Step 1b ] era ... two VISION passes; each batches CONCURRENTLY
        └──────┬───────┘
               ▼
[ Step 1.5 ] support .................. text only: which observations are renovations?
               ▼
[ Step 2 ] match ...................... text only: ground supported findings to catalog
               ▼
[ structural ] run_structure ......... VISION: oldest vs newest exterior photo → extension?
               ▼
        apply_year_guard ............. drop items dated at/before yearBuilt (original build)
               ▼
[ Step 3 ] price_validated ........... deterministic, NO model: BCI + repaint + extension + pricing
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
| 2 | match | `steps/match.py` `run_match` | text | Grounds only the supported findings to catalog items. Output: `validatedCandidates`, `rejectedCandidates`, `unmatchedFindings` (supported but no catalog item — surfaced as unpriced "needs review" rows), `summary`. |
| — | structural | `steps/structure.py` `run_structure` | **vision** | Compares the oldest vs newest dated **exterior** photo (roomType from observe, dates from `sentPhotos`) for a storey/footprint change. Output: `structuralChange`. No-ops when there's no exterior pair. Feeds a deterministic `House Extension` row in Step 3. |
| — | year guard | `price.py` `apply_year_guard` | no | Drops candidates dated `<= yearBuilt` (that's the original build, not a renovation). Dropped ones are kept in `yearGuardRejected`; in v3, when `analyze` flags `gutRenovation.detected` (the build year is unreliable on a gut reno), they resurface as unpriced needs-review rows for manual judgement instead of vanishing. |
| 3 | price | `price.py` `price_validated` | no | Deterministic. BCI factor per state/year, internal-repaint assumption (ladder: never on a brand-new build ≤2 yrs; assumed ≥10 yrs by QS convention; in between only when other renovations exist and paint reads new), **House Extension row** (`_extension_row`, `capExempt`), expand whole-room matches to leaves, dedup, `price_items`, owner split. |

Steps 1 and 1b run **concurrently** (`ThreadPoolExecutor(max_workers=2)`); the
slower one sets the wall-clock. Steps 1.5, 2 and the structural pass run after both
finish.

## The model calls

All model I/O lives in `app/clients/openai_client.py`.

- **observe + era are vision calls** — photos are downloaded + room-classified
  **once** by `prepare_photos` (parallel), then both passes reuse the prepared images
  (era skips the room hints). Each pass splits them into `PHOTO_BATCH` chunks and runs
  those calls **concurrently** (`_run_photo_batches`), merged on one global
  `photoIndex`, so wall-clock is one call's latency and each call's output stays under
  the cap.
- **support + match are text-only** — no photos; they receive prior steps' JSON.
- **structural is a 2-photo vision call** (`compare_structure`) — just the oldest +
  newest exterior photo, labelled OLDER/NEWER. Skipped (no call) when there's no
  exterior pair to compare.
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

- `Renovations`, `Renovations Total` — priced rows, plus any **needs-review rows**
  (`needsReview: true`, no cost) for supported renovations not yet in the catalog
- `Property`, `GFA`, `Summary Description`, `Disclaimer`
- `Usage` — token counts + USD, summed across the model calls. Includes
  `reasoning_tokens` (the thinking slice of `completion_tokens`) for benchmarking
- `Stages` — per-step output for debugging (observations, eraAnalysis,
  renovationSupport, roomHints, paintAssumption, structuralChange,
  extensionAssumption, candidates, toolInput, bci, photos)
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
| `estimator_v2/steps/{observe,era,support,match,structure}.py` | the model steps (`run_*`) |
| `estimator_v2/steps/parsing.py` | shared JSON parse (`_parse`) |
| `estimator_v2/price.py` | year guard + deterministic Step 3 pricing + internal-repaint + House Extension |
| `estimator_v2/preview.py` | `preview_estimate_prompt_v2` (assembles the prompts for debugging) |
| `estimator_v2/playground.py` | `step_*` single-step runners for the playground UI |
| `clients/openai_client.py` | the actual model calls, photo batching, pricing tool |

## Maintenance

This doc reflects the orchestration as of the current code. When the flow changes,
update the relevant section here in the same change — the "Flow at a glance"
diagram, the "Steps" table, and the "Response shape" are the parts that drift.
