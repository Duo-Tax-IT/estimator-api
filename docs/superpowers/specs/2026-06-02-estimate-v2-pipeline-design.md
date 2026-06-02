# `/estimate/v2` — Multi-step Renovation Detection Pipeline

**Date:** 2026-06-02
**Status:** Approved (design)

## Goal

Add a second, isolated renovation-detection pipeline behind a new endpoint
`POST /estimate/v2`, so the current single-call pipeline can stay in place for
rollback and side-by-side comparison. The new pipeline splits the model's work
into discrete stages and stores each stage's output for debugging.

## Why

The current pipeline (`build_full_estimate` → `generate_estimate`) does
observation, catalog-matching, and pricing in **one model call** with an
in-loop `calculate_renovations` tool. Splitting observation from matching is
intended to reduce hallucination/order-bias: the model first describes only
what is visible, then a second pass matches those observations to the catalog
and rejects weak candidates with explicit reasons.

## Non-goals

- No change to `/estimate`, `estimator.py`, `openai_client.generate_estimate`,
  or `estimator_prompt.txt`. They are left byte-for-byte as-is.
- No frontend changes. v2 returns the **same response shape** as `/estimate`
  (plus an extra `Stages` key the frontend ignores).
- No provider/model swap. Same Gemini-via-OpenAI client and `req.model` override.

## Pipeline (2 model calls)

| Step | What | How |
|---|---|---|
| 1. Observe | Per-photo description of visible fixtures/surfaces/materials/wear/cues. **No matching, no pricing, no year.** | Model call (vision). New `observe_prompt.txt`. |
| 2. Validate & match | Observations + trimmed catalog + gfa + config → `validatedCandidates`, `rejectedCandidates` (with reason), and a `summary`. | Model call (text-only). New `candidates_prompt.txt`. |
| 3. Price | Map validated candidates → `price_items` input, apply AIQS BCI factor by year. | **Reuse** `price_items` + `_bci_factor`. No model, no tool-loop. |
| 4. Format | Reshape priced results into the current response shape. | **Reuse** `_format_renovations`, `split_by_owner`, `_money`. Pure Python. |

**Design decision — Step 4 is NOT a model call.** The spec's original 4-step
diagram had an LLM "final formatter". Because v2 returns the deterministic
current response shape, formatting is plain Python (as `build_full_estimate`
already does today). Step 2 emits the `summary`; the disclaimer is the fixed
Guarantee sentence. This removes a model call, cost, latency, and a failure
point with no loss of behavior.

## Stage data flow

```
fetch (catalog, photos, property, gfa)        # reused upstream calls
  → Step 1: observe_photos(model, observe_prompt, photos)
            -> { photoObservations: [...] }
  → Step 2: match_candidates(model, candidates_prompt,
              { photoObservations, renovationItems(trimmed), gfa, config })
            -> { validatedCandidates: [...], rejectedCandidates: [...], summary }
  → Step 3: price_items(
              [{ _id, name, area: areaForTool, factor: bci(estimatedYear) } ...],
              library, livingSpace)
  → Step 4: reshape -> current response shape + Stages
```

### Step 2 candidate → `price_items` field mapping

| Step 2 field | `price_items` item field |
|---|---|
| `_id` | `_id` |
| `name` | `name` (recovers a mistyped `_id`) |
| `areaForTool` (sqm items, else null) | `area` |
| `estimatedYear` → `_bci_factor(state, year)` | `factor` |

`estimatedYear` is also written onto each priced renovation as `Year` (drives
`split_by_owner`).

## New / changed files

- **New** `app/estimator_v2.py` — `build_estimate_v2(req)` orchestrator.
  Reuses the catalog/photo/property/gfa fetches; imports
  `_build_model_input`, `_bci_factor`, `split_by_owner`, `_format_renovations`,
  `_money` from `estimator.py`.
- **New** in `app/openai_client.py` — `observe_photos(...)`,
  `match_candidates(...)`, and a shared `_chat_json(...)` helper (single
  create call, `json_object` response_format, **no tools**, usage logged).
  Both reuse existing `_client`, `_image_data_url`, `build_input_text`,
  `_is_reasoning_model`, `_log_usage`. `generate_estimate` untouched.
- **New** `observe_prompt.txt`, `candidates_prompt.txt` (repo root, read via
  `get_base_prompt`). Adapted from the user's Step 1/Step 2 prompts so Step 2's
  output fields map directly into `price_items` and include `summary`.
- **Edit** `app/main.py` — add `POST /estimate/v2` calling `build_estimate_v2`,
  reusing `require_secret` and `_save_run`.

## Response shape

Identical to `/estimate`:
`Renovations`, `Renovations Total`, `Property`, `GFA`, `Summary Description`,
`Disclaimer`, and (when `settlementDate` given) `Previous Owner Total` /
`Current Owner Total` — **plus**:

```jsonc
"Stages": {
  "observations": { "photoObservations": [ ... ] },   // step 1 raw
  "candidates":   { "validatedCandidates": [ ... ],
                    "rejectedCandidates": [ ... ] },   // step 2 raw
  "toolInput":    [ { "_id": "...", "area": 42 }, ... ] // step 3 input
}
```

`Stages` is always included in v2 and persisted automatically by `_save_run`
(it's part of the returned dict). The frontend ignores unknown keys, so the
backend/frontend contract is unchanged.

## Error handling

Same error taxonomy as `/estimate`:
- No photos → `NoPhotosError` → 422.
- Empty catalog / upstream fetch failures → `ItemsFetchError` /
  `RpDataFetchError` → 502.
- Model call failure or invalid JSON from either stage → `ModelError` → 502.

Each model stage parses its JSON and raises `ModelError` on invalid JSON,
naming the stage ("observation" / "candidate matching") so failures are
attributable.

## Testing

- Unit: `build_estimate_v2` with `observe_photos` / `match_candidates` /
  fetches monkeypatched — assert response shape matches `/estimate`, `Stages`
  populated, candidate→`price_items` mapping (incl. sqm `areaForTool`→`area`),
  and `Year`/owner-split behavior.
- Unit: invalid JSON from each stage → `ModelError`.
- Endpoint: `POST /estimate/v2` returns 200 with `Stages`; auth + error codes
  match `/estimate`.

## Rollback

Stop calling `/estimate/v2`. No existing code path is modified, so the original
pipeline is unaffected.
