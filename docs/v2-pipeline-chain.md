# /estimate/v2 Pipeline Chain

Steps 1 (observe) and 1b (era) run **in parallel** (independent vision passes over
the same photos). **Step 1.5 (renovation support)** then validates which observed
items are renovation-supported against the build-year baseline, and **Step 2
(match)** grounds only the supported findings to the catalog — it no longer judges
renovation-vs-original itself. A separate **structural pass** compares the oldest vs
newest exterior photo for a storey/footprint change (an extension the finish-based
steps can't see) and prices it as a deterministic `House Extension` row.

See `observe_prompt.txt`, `era_prompt.txt`, `support_prompt.txt`,
`candidates_prompt.txt`, `structure_prompt.txt`, and `app/estimator_v2.py`.

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
   │  out: validatedCandidates[] · rejectedCandidates[] · unmatchedFindings[] · summary         │
   │       (unmatchedFindings = supported but no catalog item → unpriced "needs review" rows)   │
   └───────────────────────────────┬──────────────────────────────────────────────────────┘
                                    │ validatedCandidates
                                    ▼
   ┌──────────────────────────────────────────────────────────────────────────────────────┐
   │  STRUCTURAL PASS   🛰 compare_structure()   ← branches off observations, feeds price      │
   │  in:  oldest + newest dated exterior photo (roomType from observe, dates from sent map)   │
   │  job: storey/footprint change between the two? → estimatedAddedAreaSqm, year, confidence  │
   │  out: structuralChange  → deterministic capExempt "House Extension" sqm row (price.py)     │
   └───────────────────────────────┬──────────────────────────────────────────────────────┘
                                    ▼
   ┌──────────────────────────────────────────────────────────────────────────────────────┐
   │  PY YEAR-GUARD (deterministic)   estimator_v2.py                                         │
   │  drop any candidate with estimatedYear ≤ yearBuilt  → rejectedCandidates ("orig build")  │
   └───────────────────────────────┬──────────────────────────────────────────────────────┘
                                    ▼
   ┌──────────────────────────────────────────────────────────────────────────────────────┐
   │  STEP 3 — PRICE (deterministic)                                                          │
   │  + internal-repaint assumption (opt-in)  + House Extension row (structural, capExempt)    │
   │  → expand_to_leaves → dedup → price_items  + BCI factor (state × year) → split_by_owner    │
   └───────────────────────────────┬──────────────────────────────────────────────────────┘
                                    ▼
   ┌──────────────────────────────────────────────────────────────────────────────────────┐
   │  STEP 4 — FORMAT (deterministic)   →  Response                                           │
   │  Renovations · Totals · Property · GFA · Summary · Disclaimer · Usage                    │
   │  Stages{ observations, eraAnalysis, renovationSupport, roomHints, paintAssumption,       │
   │          structuralChange, extensionAssumption, candidates, toolInput, bci, photos }     │
   │  Meta{ pipeline, observe/era/support/candidates/structure prompt hashes }                 │
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
- **Structural pass:** detection (storey/footprint change) is separate from pricing —
  the structural step only finds the change; the deterministic `House Extension` row is
  built in `price.py` (`_extension_row`), `capExempt` so it neither shrinks nor is shrunk
  by the livingSpace floor cap. It no-ops cleanly when there aren't two distinct-date
  exterior photos to compare.
- **Photo cap + batching:** the raw photo set is hard-capped at `MAX_PHOTOS` (100,
  newest-first) before dedup. `prepare_photos` then downloads + room-classifies the set
  **once** (in parallel), and Observe and Era both reuse it — no photo is fetched or
  classified twice (Era skips the room hints; it dates fabrication, not rooms). Each
  pass splits the prepared photos into `PHOTO_BATCH` (20) chunks and runs those vision
  calls **concurrently**, merging on a global `photoIndex` — so wall-clock is one call's
  latency, not the sum, and a photo-heavy property still can't truncate the JSON against
  `MAX_OUTPUT_TOKENS`.
- **Cost:** observe + era + support + match + structural. Support/match are single text
  calls; observe/era are one vision call per photo batch; structural is one 2-photo vision
  call (skipped when there's no exterior pair). Usage is summed across all calls
  (`merge_usage`).
- **Known follow-up:** Match grounds from `observedItem`/`roomType` only; if grounding
  quality suffers, re-add `photoObservations` to the match payload (one line).
