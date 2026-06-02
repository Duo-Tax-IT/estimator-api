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
- No provider/model swap. Same Gemini-via-OpenAI client and `req.model` override.
- v2 returns the **same response shape** as `/estimate` (plus an extra `Stages`
  key), so the existing result rendering is reused unchanged.

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
already does today). Step 2 emits the `summary`; the `Disclaimer` is a Python
constant `DISCLAIMER` in `estimator_v2.py` holding the exact Guarantee sentence
from `estimator_prompt.txt` ("This assessment is based solely on visual
analysis of provided images and uses a predefined renovation item dataset. No
external cost estimation methods were used."). This removes a model call, cost,
latency, and a failure point with no loss of behavior.

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

`state` is derived the same way as v1: `state = extract_state(req.address)`
(`from .rpdata_client import extract_state`). `estimatedYear` is also written
onto each priced renovation as `Year` (drives `split_by_owner`).

## New / changed files

- **New** `app/estimator_v2.py` — `build_estimate_v2(req)` orchestrator.
  Reuses the catalog/photo/property/gfa fetches; imports
  `_build_model_input`, `_bci_factor`, `split_by_owner`, `_format_renovations`,
  `_money` from `estimator.py`, and `extract_state` from `rpdata_client`.
  Defines the `DISCLAIMER` constant.
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
  "toolInput":    [ { "_id": "...", "name": "...",      // step 3 input
                      "area": 42, "factor": 1.0 }, ... ] // (as passed to price_items)
}
```

`Stages` is always included in v2 and persisted automatically by `_save_run`
(it's part of the returned dict). The frontend ignores unknown keys, so the
backend/frontend contract is unchanged.

## Frontend (`app/static/index.html`)

**Decouple "pick property" from "run", add one button per pipeline.** Today
`selectSuggestion(s)` (index.html:500) immediately POSTs to `/estimate`. That
auto-run is removed.

- `selectSuggestion(s)` now only *selects*: clears suggestions, sets
  `lastSelected`, fills the search box, loads photos, shows a "Selected: …"
  line, clears any prior result/error, and **enables the run buttons**. No model
  call.
- New `runEstimate(version)` does what `selectSuggestion` used to: shows
  "Thinking…", POSTs `buildBody(lastSelected)` to `/estimate` (v1) or
  `/estimate/v2` (v2), renders the result, refreshes saved runs. `version` only
  chooses the endpoint; the request body is identical.
- Two buttons **Run v1** / **Run v2**, disabled until a property is selected.
  Placed after the override card. The result banner notes which version ran.
- Override fields: drop the "set them before picking an address" hint — they can
  now be edited after picking, before running. The `property` override already
  flows through `buildBody` unchanged.
- New collapsed `<details>` "Pipeline stages (debug)" panel, shown only when
  `data.Stages` is present (v2), rendering `Stages` as pretty JSON — mirrors the
  existing Property/Prompt debug panels. `renderResult` hides it when absent so
  v1 results are unaffected.

No change to the backend/response contract: v2 reuses the same `renderResult`
path; `Stages` is the only addition and is read only by the new panel.

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

The backend pipeline is fully isolated — stop calling `/estimate/v2` and the
original pipeline is unaffected. The frontend change (run buttons) is shared:
the **Run v1** button preserves the original behavior, so v1 remains one click
away even if v2 is abandoned.
