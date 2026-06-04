import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import openai

from .config import get_settings
from .errors import ItemsFetchError, ModelError, NoPhotosError
from .estimator import (
    _bci_factor,
    _build_model_input,
    _format_renovations,
    _money,
    apply_room_counts,
    filter_catalog_for_property,
    split_by_owner,
)
from .helpers.gfa import gfa_from_property
from .clients.megamind_client import fetch_renovation_items
from .helpers.photo_dedup import dedup_photos
from .clients.openai_client import (
    MAX_PHOTOS,
    analyze_era,
    assess_support,
    build_input_text,
    match_candidates,
    merge_usage,
    observe_photos,
)
from .helpers.pricing import dedup_by_id, expand_to_leaves, price_items
from .prompts import get_base_prompt
from .clients.rpdata_client import extract_state, fetch_photos, fetch_property
from .schemas import EstimateRequest, StepRequest

# The fixed Guarantee sentence from estimator_prompt.txt. v2 builds the final
# response in Python (no formatter model call), so the disclaimer is a constant.
DISCLAIMER = (
    "This assessment is based solely on visual analysis of provided images and "
    "uses a predefined renovation item dataset. No external cost estimation "
    "methods were used."
)

OBSERVE_PROMPT_FILE = "observe_prompt.txt"
ERA_PROMPT_FILE = "era_prompt.txt"
SUPPORT_PROMPT_FILE = "support_prompt.txt"
CANDIDATES_PROMPT_FILE = "candidates_prompt.txt"

# Internal-repaint assumption (opt-in via config.assumeInternalRepaint). When the
# property is old enough and the model saw visibly sound paint, assume the rooms
# of that type were repainted, using the per-room areas already in `gfa`.
REPAINT_MIN_AGE = 10
INTERNAL_PAINT_NAME = "Painting - Internal"
# observe `roomType` -> the `gfa` bucket holding that type's area. living/laundry
# have no own bucket — their area sits inside the leftover livingSpace.
_PAINT_AREA_KEY = {
    "bedroom": "bedroom", "bathroom": "bathroom", "kitchen": "kitchen",
    "living": "livingSpace", "laundry": "livingSpace",
}
# Honest disclaimer used only when the repaint assumption fires.
DISCLAIMER_WITH_REPAINT = (
    "This assessment is based on visual analysis of provided images and a "
    f"predefined renovation item dataset, plus an assumed internal repaint for "
    f"properties over {REPAINT_MIN_AGE} years old whose interior paint appears "
    "sound. The repaint is an assumption, not confirmed from the images."
)


def _hash(text: str) -> str:
    """Short stable version id for a prompt, so saved runs can be bucketed by
    prompt version when comparing system output against expert output."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _parse(raw: str, stage: str) -> dict:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        # Surface what the model actually returned so the failure is diagnosable
        # (the head usually shows a leading prose line or an empty/garbled reply).
        text = raw or ""
        snippet = text[:300] + (" …" if len(text) > 300 else "")
        print(f"[v2] {stage} returned unparseable output ({len(text)} chars): {snippet!r}")
        raise ModelError(
            f"Vision model returned invalid JSON in {stage}. "
            f"It returned {len(text)} chars starting: {snippet!r}"
        ) from exc


def preview_estimate_prompt_v2(req: EstimateRequest) -> str:
    """The two prompts the v2 pipeline sends, assembled for debugging.

    Mirrors build_estimate_v2's upstream fetches (catalog filtered by property
    type, gfa) minus the photos and model calls. Step 2's `photoObservations`
    are produced at runtime by Step 1, so they're shown as a placeholder.
    """
    property_data = req.property or fetch_property(req.rp_id)
    renovation_items = filter_catalog_for_property(
        fetch_renovation_items(), property_data
    )
    gfa = gfa_from_property(property_data)
    payload = _build_model_input(property_data, renovation_items, req.config or {}, gfa)
    payload["renovationSupportFindings"] = "<filled at runtime from Step 1.5 support assessment>"
    return (
        "=== STEP 1 — OBSERVATION ===\n"
        f"(prompt below + up to {MAX_PHOTOS} property photos sent as images)\n\n"
        + get_base_prompt(OBSERVE_PROMPT_FILE)
        + "\n\n\n=== STEP 1b — ERA ANALYSIS ===\n"
        "(prompt below + the same property photos sent as images)\n\n"
        + get_base_prompt(ERA_PROMPT_FILE)
        + "\n\n\n=== STEP 1.5 — RENOVATION SUPPORT ===\n"
        "(prompt below + property/observations/eraAnalysis from Steps 1/1b)\n\n"
        + get_base_prompt(SUPPORT_PROMPT_FILE)
        + "\n\n\n=== STEP 2 — CANDIDATE MATCHING ===\n"
        "(prompt below + the input data; renovationSupportFindings come from Step 1.5)\n\n"
        + get_base_prompt(CANDIDATES_PROMPT_FILE)
        + "\n\n"
        + build_input_text(payload)
    )


def _internal_paint_row(validated, observations, property_data, config, gfa, library):
    """A synthetic 'Painting - Internal' detected-row when the repaint assumption
    applies, plus a decision record for Stages; (None, decision) otherwise.

    Gated on: config opt-in, property age >= REPAINT_MIN_AGE, and the model seeing
    visibly sound paint (clean/new_like, none worn/poor) in a room type. The area
    reuses the per-room buckets already computed in `gfa`. Year is left unknown
    (no fabricated date -> BCI factor 1.0, current-owner by default); `capExempt`
    keeps it out of the livingSpace sqm cap so it can't shrink real flooring.
    """
    if not config.get("assumeInternalRepaint"):
        return None, {"applied": False, "reason": "disabled"}
    built = str(property_data.get("yearBuilt", "")).strip()
    if not built.isdigit():
        return None, {"applied": False, "reason": "no yearBuilt"}
    age = date.today().year - int(built)
    if age < REPAINT_MIN_AGE:
        return None, {"applied": False, "reason": f"age {age} < {REPAINT_MIN_AGE}"}
    paint = next((it for it in library.values() if it["name"] == INTERNAL_PAINT_NAME), None)
    if not paint or not gfa:
        return None, {"applied": False, "reason": "no paint item or no gfa"}
    if any(c.get("_id") == paint["_id"] for c in validated):
        return None, {"applied": False, "reason": "already detected by model"}
    # Room types whose photos show sound, fresh paint (none worn/poor).
    keys, rooms = set(), []
    for room_type, key in _PAINT_AREA_KEY.items():
        shots = [
            p for p in observations.get("photoObservations", [])
            if p.get("roomType") == room_type
        ]
        if not shots or any(p.get("condition") in ("worn", "poor") for p in shots):
            continue
        if any(p.get("condition") in ("clean", "new_like") for p in shots):
            keys.add(key)
            rooms.append(room_type)
    areas = {k: round(gfa.get(k, 0), 1) for k in keys}
    total = round(sum(areas.values()), 1)
    if total <= 0:
        return None, {"applied": False, "reason": "no rooms with fresh paint"}
    row = {
        "_id": paint["_id"], "name": paint["name"], "area": total,
        "factor": 1.0, "Year": "", "capExempt": True,
    }
    decision = {
        "applied": True, "reason": f"age {age}; fresh paint in {rooms}",
        "rooms": rooms, "areas": areas, "totalArea": total,
    }
    return row, decision


def fetch_v2_context(req: EstimateRequest) -> dict:
    """Upstream fetch shared by every v2 step: the property, its photos, the
    catalog trimmed to the property type (+ an _id `library`), and the GFA.

    Raises ItemsFetchError / NoPhotosError when megamind or rpdata yield nothing.
    """
    renovation_items = fetch_renovation_items()
    if not renovation_items:
        raise ItemsFetchError("Megamind returned no usable renovation items")
    # Hard-cap the raw set (newest-first) BEFORE dedup so a 300+ photo listing
    # can't blow up dedup downloads or the vision output; then drop near-duplicate
    # re-listed shots (URL/ID dedup misses these — same photo, fresh asset id).
    photos = dedup_photos(fetch_photos(req.rp_id)[:MAX_PHOTOS])
    if not photos:
        raise NoPhotosError(f"No usable photos found for rp_id {req.rp_id}")
    property_data = req.property or fetch_property(req.rp_id)
    # Show the model only the kitchen variant that fits this property type.
    renovation_items = filter_catalog_for_property(renovation_items, property_data)
    gfa = gfa_from_property(property_data)
    return {
        "model": req.model or get_settings().default_model,
        "photos": photos,
        "property": property_data,
        "renovationItems": renovation_items,
        "library": {it["_id"]: it for it in renovation_items},
        "gfa": gfa,
    }


def run_observe(model: str, photos: list, req: EstimateRequest) -> tuple:
    """Step 1 — observe what's visible. Returns (observations, usage, roomHints,
    sentPhotos); roomHints/sentPhotos are classifier audit data for Stages."""
    raw, usage, room_hints, sent_photos = observe_photos(
        model, get_base_prompt(OBSERVE_PROMPT_FILE), photos,
        reasoning_effort=req.reasoning_effort, temperature=req.temperature,
    )
    return _parse(raw, "observation"), usage, room_hints, sent_photos


def run_era(model: str, photos: list, req: EstimateRequest) -> tuple:
    """Step 1b — forensically date each finish. Returns (eraAnalysis, usage)."""
    raw, usage = analyze_era(
        model, get_base_prompt(ERA_PROMPT_FILE), photos,
        reasoning_effort=req.reasoning_effort, temperature=req.temperature,
    )
    return _parse(raw, "era analysis"), usage


def run_support(ctx: dict, observations: dict, era: dict, req: EstimateRequest) -> tuple:
    """Step 1.5 — judge which observed items are renovation-supported, against the
    build-year baseline + era evidence (no catalog match yet). Returns
    (support, usage)."""
    payload = {
        "property": ctx["property"],
        "photoObservations": observations.get("photoObservations", []),
        "eraAnalysis": era.get("eraAnalysis", []),
    }
    raw, usage = assess_support(
        ctx["model"], get_base_prompt(SUPPORT_PROMPT_FILE), payload,
        reasoning_effort=req.reasoning_effort, temperature=req.temperature,
    )
    return _parse(raw, "renovation support"), usage


def run_match(ctx: dict, support: dict, req: EstimateRequest) -> tuple:
    """Step 2 — ground the renovation-supported findings to the catalog. The
    renovation decision and year are already made in Step 1.5; only findings
    flagged `shouldProceedToCatalogMatch` are matched. Returns (candidates,
    usage)."""
    findings = [
        f for f in support.get("renovationSupportFindings", [])
        if f.get("shouldProceedToCatalogMatch")
    ]
    payload = _build_model_input(
        ctx["property"], ctx["renovationItems"], req.config or {}, ctx["gfa"]
    )
    payload["renovationSupportFindings"] = findings
    raw, usage = match_candidates(
        ctx["model"], get_base_prompt(CANDIDATES_PROMPT_FILE), payload,
        reasoning_effort=req.reasoning_effort, temperature=req.temperature,
    )
    return _parse(raw, "candidate matching"), usage


def apply_year_guard(validated: list, candidates: dict, property_data: dict) -> list:
    """Drop candidates dated at/before original construction — that's the original
    build, not a renovation (guards "new build + modern finish" false positives).
    Rejected ones are appended to `candidates['rejectedCandidates']`."""
    year_built = str(property_data.get("yearBuilt", "")).strip()
    if not year_built.isdigit():
        return validated
    rejects = candidates.setdefault("rejectedCandidates", [])
    kept = []
    for c in validated:
        y = str(c.get("estimatedYear", ""))
        if y.isdigit() and int(y) <= int(year_built):
            rejects.append({
                "candidateName": c.get("name"),
                "matchedItemId": c.get("_id"),
                "reason": f"estimatedYear {y} <= yearBuilt {year_built} (original build)",
                "evidence": "",
            })
        else:
            kept.append(c)
    return kept


def price_validated(
    req: EstimateRequest, ctx: dict, validated: list, observations: dict
) -> dict:
    """Step 3 — price (deterministic; same expand/dedup/price path as v1).

    A whole-room match (a 0-rate parent) is expanded to its leaf items, then
    de-duplicated so a parent + child match can't double-count. Applies the BCI
    factor, room counts and owner split. Returns the priced rows plus the audit
    bits the Stages debug / playground surface (state, factors, paint, counts)."""
    property_data, library, gfa = ctx["property"], ctx["library"], ctx["gfa"]
    living = gfa["livingSpace"] if gfa else None
    state = extract_state(req.address)
    factors: dict = {}
    detected = [
        {
            "_id": c.get("_id"),
            "name": c.get("name"),
            "area": c.get("areaForTool"),
            "factor": _bci_factor(state, c.get("estimatedYear"), factors),
            "Year": c.get("estimatedYear"),
        }
        for c in validated
    ]
    # Internal-repaint assumption (opt-in): inject a paint row before pricing so
    # it expands/prices like any item; recorded in paintAssumption.
    paint_row, paint_decision = _internal_paint_row(
        validated, observations, property_data, req.config or {}, gfa, library
    )
    if paint_row:
        detected.append(paint_row)
    detected = dedup_by_id(expand_to_leaves(detected, library))
    priced = price_items(detected, library, living)
    renovations = priced["renovations"]
    years = {e["_id"]: e.get("Year") for e in detected}
    for reno in renovations:
        reno["Year"] = years.get(reno["_id"], "")

    # Count a room-scoped reno once per such room (opt-in); returns the scaled
    # total. Sets Count on each row, which split_by_owner also honours.
    total, room_scale_reasons = apply_room_counts(renovations, property_data, req.config or {})
    # Tags each renovation's Owner in place; must run before _format_renovations.
    owner_totals = split_by_owner(renovations, req.settlement_date)
    room_counts = {
        (r.get("groupPath") or [r["Name"]])[0]: r["Count"]
        for r in renovations if r.get("Count", 1) != 1
    }
    return {
        "renovations": renovations,
        "total": total,
        "ownerTotals": owner_totals,
        "detected": detected,
        "state": state,
        "factors": factors,
        "paintDecision": paint_decision,
        "roomCounts": room_counts,
        "roomScaleReasons": room_scale_reasons,
    }


def build_estimate_v2(req: EstimateRequest) -> dict:
    """Detect renovations via the multi-step v2 pipeline.

    Composes the step functions: fetch context → observe ∥ era (parallel vision
    passes) → match → year-guard → price. Returns the same response shape as
    build_full_estimate, plus a `Stages` key holding each step's output for
    debugging. Same error taxonomy: NoPhotosError, ItemsFetchError, ModelError.
    """
    ctx = fetch_v2_context(req)
    try:
        # Steps 1 & 1b are independent vision passes over the same photos, so they
        # run in parallel — the slower one sets the wall-clock, not obs + era.
        with ThreadPoolExecutor(max_workers=2) as pool:
            obs_f = pool.submit(run_observe, ctx["model"], ctx["photos"], req)
            era_f = pool.submit(run_era, ctx["model"], ctx["photos"], req)
            observations, obs_usage, room_hints, sent_photos = obs_f.result()
            era, era_usage = era_f.result()
        # Step 1.5 — validate which observations are renovation-supported (uses
        # both observe + era), then Step 2 grounds only the supported ones.
        support, support_usage = run_support(ctx, observations, era, req)
        candidates, cand_usage = run_match(ctx, support, req)
    except openai.OpenAIError as exc:
        raise ModelError(f"Vision model call failed: {exc}") from exc

    validated = apply_year_guard(
        candidates.get("validatedCandidates", []), candidates, ctx["property"]
    )
    core = price_validated(req, ctx, validated, observations)

    result = {
        "Renovations": _format_renovations(core["renovations"]),
        "Renovations Total": _money(core["total"]),
        "Property": ctx["property"],
        "GFA": ctx["gfa"],
        "Summary Description": candidates.get("summary", ""),
        "Disclaimer": DISCLAIMER_WITH_REPAINT if core["paintDecision"]["applied"] else DISCLAIMER,
        # Combined token counts + USD cost across the four model calls.
        "Usage": merge_usage(obs_usage, era_usage, support_usage, cand_usage),
        "Stages": {
            "observations": observations,
            # Forensic per-element era dating (Step 1b) — the dated fabrication
            # cues the support step weighed against yearBuilt.
            "eraAnalysis": era,
            # Step 1.5 renovation-support findings — the gated judgment (and
            # estimatedRenovationYear) Match grounded to the catalog.
            "renovationSupport": support,
            # Room classifier predictions per photo (photoIndex matches the
            # observe model's image order) — auditable vs observations.roomType.
            "roomHints": room_hints,
            # Internal-repaint assumption audit: whether it fired and the per-room
            # areas (from gfa) that made up the assumed paint area.
            "paintAssumption": core["paintDecision"],
            "candidates": {
                "validatedCandidates": validated,
                "rejectedCandidates": candidates.get("rejectedCandidates", []),
            },
            "toolInput": [
                {"_id": e["_id"], "name": e["name"], "area": e["area"], "factor": e["factor"]}
                for e in core["detected"]
            ],
            # AIQS BCI audit: the state used and the factor applied per renovation
            # year (1.0 = no scaling / unavailable). FinalCost = rate × qty × factor.
            "bci": {"state": core["state"], "factors": core["factors"]},
            # Room scaling audit: the manual multipliers / auto flag requested,
            # and what was actually applied per group.
            "roomScaling": {
                "manual": (req.config or {}).get("roomScale") or {},
                "auto": bool((req.config or {}).get("assumeAllRoomsRenovated")),
                "applied": core["roomCounts"],
                # Per room type, why it did / didn't scale — the deterministic audit.
                "reasons": core["roomScaleReasons"],
            },
            # Index→url/date for the photos actually sent (skips ones that failed
            # to fetch), so each evidence `photoIndex` resolves to a real image.
            "photos": sent_photos,
        },
        # Provenance for a self-learning loop: which pipeline + prompt versions
        # produced this run, so a signal can be attributed to a prompt version.
        "Meta": {
            "pipeline": "v2",
            "observePromptHash": _hash(get_base_prompt(OBSERVE_PROMPT_FILE)),
            "eraPromptHash": _hash(get_base_prompt(ERA_PROMPT_FILE)),
            "supportPromptHash": _hash(get_base_prompt(SUPPORT_PROMPT_FILE)),
            "candidatesPromptHash": _hash(get_base_prompt(CANDIDATES_PROMPT_FILE)),
        },
    }
    if req.settlement_date:
        result["Previous Owner Total"] = _money(core["ownerTotals"]["Previous Owner"])
        result["Current Owner Total"] = _money(core["ownerTotals"]["Current Owner"])
    return result


# ── Playground: run a single step in isolation on (optionally hand-edited) input ──
# Each returns plain JSON so the /playground UI can show the output and feed it
# into the next step. `req.observations` / `req.era` / `req.validatedCandidates`
# let a step run on data the user tweaked rather than the previous step's output.


def _guard(fn, *args):
    """Map a model call's openai error to ModelError, as build_estimate_v2 does."""
    try:
        return fn(*args)
    except openai.OpenAIError as exc:
        raise ModelError(f"Vision model call failed: {exc}") from exc


def step_context(req: EstimateRequest) -> dict:
    """Step 0 — the upstream fetch: what the pipeline starts from."""
    ctx = fetch_v2_context(req)
    return {
        "model": ctx["model"],
        "property": ctx["property"],
        "gfa": ctx["gfa"],
        "photoCount": len(ctx["photos"]),
        "catalogCount": len(ctx["renovationItems"]),
        "photos": [p.model_dump() for p in ctx["photos"]],
    }


def step_observe(req: EstimateRequest) -> dict:
    ctx = fetch_v2_context(req)
    observations, usage, room_hints, sent_photos = _guard(
        run_observe, ctx["model"], ctx["photos"], req
    )
    return {"observations": observations, "roomHints": room_hints,
            "photos": sent_photos, "usage": usage}


def step_era(req: EstimateRequest) -> dict:
    ctx = fetch_v2_context(req)
    era, usage = _guard(run_era, ctx["model"], ctx["photos"], req)
    return {"era": era, "usage": usage}


def step_support(req: StepRequest) -> dict:
    ctx = fetch_v2_context(req)
    observations = req.observations or {"photoObservations": []}
    era = req.era or {"eraAnalysis": []}
    support, usage = _guard(run_support, ctx, observations, era, req)
    return {"renovationSupport": support, "usage": usage}


def step_match(req: StepRequest) -> dict:
    ctx = fetch_v2_context(req)
    support = req.support or {"renovationSupportFindings": []}
    candidates, usage = _guard(run_match, ctx, support, req)
    return {"candidates": candidates, "usage": usage}


def step_price(req: StepRequest) -> dict:
    ctx = fetch_v2_context(req)
    candidates = {"validatedCandidates": req.validated_candidates or [],
                  "rejectedCandidates": []}
    validated = apply_year_guard(
        candidates["validatedCandidates"], candidates, ctx["property"]
    )
    core = price_validated(req, ctx, validated, req.observations or {})
    result = {
        "Renovations": _format_renovations(core["renovations"]),
        "Renovations Total": _money(core["total"]),
        # What the deterministic year-guard dropped as original build.
        "yearGuardRejected": candidates["rejectedCandidates"],
        "bci": {"state": core["state"], "factors": core["factors"]},
        "roomScaling": {
            "manual": (req.config or {}).get("roomScale") or {},
            "auto": bool((req.config or {}).get("assumeAllRoomsRenovated")),
            "applied": core["roomCounts"],
            "reasons": core["roomScaleReasons"],
        },
    }
    if req.settlement_date:
        result["Previous Owner Total"] = _money(core["ownerTotals"]["Previous Owner"])
        result["Current Owner Total"] = _money(core["ownerTotals"]["Current Owner"])
    return result
