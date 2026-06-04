# /estimate/v2 Pipeline Chain

Steps 1 (observe) and 1b (era) run **in parallel** (independent vision passes over
the same photos). **Step 1.5 (renovation support)** then validates which observed
items are renovation-supported against the build-year baseline, and **Step 2
(match)** grounds only the supported findings to the catalog — it no longer judges
renovation-vs-original itself.

See `observe_prompt.txt`, `era_prompt.txt`, `support_prompt.txt`,
`candidates_prompt.txt`, and `app/estimator_v2.py`.

```
                        ┌─────────────── UPSTREAM FETCHES (deterministic) ───────────────┐
                        │  Megamind catalog · rpdata photos · rpdata property             │
                        │  → filter_catalog_for_property · gfa_from_property               │
                        └───────────────────────────────┬─────────────────────────────────┘
                                                         │  photos, property, catalog, gfa
                        ┌────────────────────────────────┴────────────────────────────────┐
                        │            PARALLEL (ThreadPoolExecutor, max_workers=2)           │
                        ▼                                                                   ▼
   ┌────────────────────────────────────────────┐   ┌────────────────────────────────────────────┐
   │  STEP 1 — OBSERVE      🛰 observe_photos()   │   │  STEP 1b — ERA        🛰 analyze_era()       │
   │  in:  photos (+ room-classifier hints)      │   │  in:  photos only (no build year)           │
   │  out: photoObservations[]                   │   │  out: eraAnalysis[]                          │
   └───────────────────────┬─────────────────────┘   └─────────────────────┬──────────────────────┘
                           │ observations              eraAnalysis           │
                           └────────────────────┬───────────────────────────┘
                                                ▼  (barrier: support needs both)
   ┌──────────────────────────────────────────────────────────────────────────────────────┐
   │  STEP 1.5 — RENOVATION SUPPORT   📝 assess_support()                                     │
   │  in:  property(yearBuilt) · photoObservations · eraAnalysis                              │
   │  job: "does the evidence support a renovation?" — status/strength/year per observed item │
   │  out: renovationSupportFindings[] { observedItem, supportStatus, estimatedRenovationYear,│
   │       supportBasis, limitations, shouldProceedToCatalogMatch }                           │
   └───────────────────────────────┬──────────────────────────────────────────────────────┘
                                    │ findings  (Python gate: keep shouldProceedToCatalogMatch only)
                                    ▼
   ┌──────────────────────────────────────────────────────────────────────────────────────┐
   │  STEP 2 — MATCH             📝 match_candidates()      ← grounding only                   │
   │  in:  renovationSupportFindings (gated) · catalog · property · gfa · config               │
   │  job: map each supported finding → closest catalog item; scope whole-room vs component;   │
   │       size sqm areas. Uses the finding's estimatedRenovationYear. Does NOT re-judge.      │
   │  out: validatedCandidates[] · rejectedCandidates[] · summary                              │
   └───────────────────────────────┬──────────────────────────────────────────────────────┘
                                    │ validatedCandidates
                                    ▼
   ┌──────────────────────────────────────────────────────────────────────────────────────┐
   │  PY YEAR-GUARD (deterministic)   estimator_v2.py                                         │
   │  drop any candidate with estimatedYear ≤ yearBuilt  → rejectedCandidates ("orig build")  │
   └───────────────────────────────┬──────────────────────────────────────────────────────┘
                                    ▼
   ┌──────────────────────────────────────────────────────────────────────────────────────┐
   │  STEP 3 — PRICE (deterministic)                                                          │
   │  + internal-repaint assumption (opt-in)  → expand_to_leaves → dedup → price_items        │
   │  + BCI factor (state × year)  → apply_room_counts → split_by_owner                        │
   └───────────────────────────────┬──────────────────────────────────────────────────────┘
                                    ▼
   ┌──────────────────────────────────────────────────────────────────────────────────────┐
   │  STEP 4 — FORMAT (deterministic)   →  Response                                           │
   │  Renovations · Totals · Property · GFA · Summary · Disclaimer · Usage                    │
   │  Stages{ observations, eraAnalysis, renovationSupport, roomHints, paintAssumption,       │
   │          candidates, toolInput, bci, roomScaling, photos }                               │
   │  Meta{ pipeline, observe/era/support/candidates prompt hashes }                           │
   └──────────────────────────────────────────────────────────────────────────────────────┘
```

**Legend:** 🛰 = vision/model call (sends photos) · 📝 = text/model call.

## Playground

`/playground` runs each step in isolation with editable handoff between steps:
Context (0) → Observe (1) ∥ Era (1b) → **Support (1.5)** → Match (2) → Price (3).
Observe/Era auto-fill Support's inputs; Support auto-fills Match; Match auto-fills
Price. Endpoints: `/estimate/v2/step/{context,observe,era,support,match,price}`.

## Notes
- **Separation of concerns:** the renovation judgment lives only in Step 1.5; Match
  is now pure catalog grounding + scope + area. The `shouldProceedToCatalogMatch`
  gate is applied deterministically in Python (`run_match`), not left to the model.
- **Photo cap + batching:** the raw photo set is hard-capped at `MAX_PHOTOS` (100,
  newest-first) before dedup. Observe and Era then process photos in batches of
  `PHOTO_BATCH` (40) per call and merge the results with a global `photoIndex`, so a
  photo-heavy property can't truncate the JSON against `MAX_OUTPUT_TOKENS`.
- **Cost:** observe + era + support + match. Support/match are single text calls;
  observe/era are one vision call per photo batch. Usage is summed across all calls
  (`merge_usage`).
- **Known follow-up:** Match grounds from `observedItem`/`roomType` only; if grounding
  quality suffers, re-add `photoObservations` to the match payload (one line).
