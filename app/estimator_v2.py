import json
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
from .gfa import gfa_from_property
from .megamind_client import fetch_renovation_items
from .openai_client import (
    MAX_PHOTOS,
    build_input_text,
    match_candidates,
    merge_usage,
    observe_photos,
)
from .pricing import dedup_by_id, expand_to_leaves, price_items
from .prompts import get_base_prompt
from .rpdata_client import extract_state, fetch_photos, fetch_property
from .schemas import EstimateRequest

# The fixed Guarantee sentence from estimator_prompt.txt. v2 builds the final
# response in Python (no formatter model call), so the disclaimer is a constant.
DISCLAIMER = (
    "This assessment is based solely on visual analysis of provided images and "
    "uses a predefined renovation item dataset. No external cost estimation "
    "methods were used."
)

OBSERVE_PROMPT_FILE = "observe_prompt.txt"
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
    payload["photoObservations"] = "<filled at runtime from Step 1 observations>"
    return (
        "=== STEP 1 — OBSERVATION ===\n"
        f"(prompt below + up to {MAX_PHOTOS} property photos sent as images)\n\n"
        + get_base_prompt(OBSERVE_PROMPT_FILE)
        + "\n\n\n=== STEP 2 — CANDIDATE MATCHING ===\n"
        "(prompt below + the input data; photoObservations come from Step 1)\n\n"
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


def build_estimate_v2(req: EstimateRequest) -> dict:
    """Detect renovations via the multi-step v2 pipeline.

    Step 1 observes the photos, Step 2 matches those observations to the catalog
    (two model calls); pricing (price_items + BCI factor) and the final shaping
    are deterministic. Returns the same response shape as build_full_estimate,
    plus a `Stages` key holding each step's output for debugging. Same error
    taxonomy: NoPhotosError, ItemsFetchError, ModelError.
    """
    model = req.model or get_settings().default_model

    renovation_items = fetch_renovation_items()
    if not renovation_items:
        raise ItemsFetchError("Megamind returned no usable renovation items")

    photos = fetch_photos(req.rp_id)
    if not photos:
        raise NoPhotosError(f"No usable photos found for rp_id {req.rp_id}")

    property_data = req.property or fetch_property(req.rp_id)
    # Show the model only the kitchen variant that fits this property type.
    renovation_items = filter_catalog_for_property(renovation_items, property_data)
    gfa = gfa_from_property(property_data)
    living = gfa["livingSpace"] if gfa else None
    library = {it["_id"]: it for it in renovation_items}

    try:
        # Step 1 — observe what's visible (no matching). Also returns the room
        # classifier's per-photo predictions for the Stages debug record.
        obs_raw, obs_usage, room_hints = observe_photos(
            model,
            get_base_prompt(OBSERVE_PROMPT_FILE),
            photos,
            reasoning_effort=req.reasoning_effort,
            temperature=req.temperature,
        )
        observations = _parse(obs_raw, "observation")
        # Step 2 — match observations to the catalog.
        payload = _build_model_input(
            property_data, renovation_items, req.config or {}, gfa
        )
        payload["photoObservations"] = observations.get("photoObservations", [])
        cand_raw, cand_usage = match_candidates(
            model,
            get_base_prompt(CANDIDATES_PROMPT_FILE),
            payload,
            reasoning_effort=req.reasoning_effort,
            temperature=req.temperature,
        )
        candidates = _parse(cand_raw, "candidate matching")
    except openai.OpenAIError as exc:
        raise ModelError(f"Vision model call failed: {exc}") from exc

    validated = candidates.get("validatedCandidates", [])
    # Drop candidates dated at/before original construction — that's the original
    # build, not a renovation (guards "new build + modern finish" false positives).
    # Rejected ones move to rejectedCandidates so the Stages debug shows why.
    year_built = str(property_data.get("yearBuilt", "")).strip()
    if year_built.isdigit():
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
        validated = kept

    # Step 3 — price (deterministic; same expand/dedup/price path as v1). A
    # whole-room match (a 0-rate parent) is expanded to its leaf items, then
    # de-duplicated so a parent + child match can't double-count.
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
    # it expands/prices like any item; recorded in Stages.paintAssumption.
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
    total = apply_room_counts(renovations, property_data, req.config or {})
    # Tags each renovation's Owner in place; must run before _format_renovations.
    owner_totals = split_by_owner(renovations, req.settlement_date)
    room_counts = {
        (r.get("groupPath") or [r["Name"]])[0]: r["Count"]
        for r in renovations if r.get("Count", 1) != 1
    }

    # Step 4 — format (deterministic reshape; v1 shape + Stages debug).
    result = {
        "Renovations": _format_renovations(renovations),
        "Renovations Total": _money(total),
        "Property": property_data,
        "GFA": gfa,
        "Summary Description": candidates.get("summary", ""),
        "Disclaimer": DISCLAIMER_WITH_REPAINT if paint_decision["applied"] else DISCLAIMER,
        # Combined token counts + USD cost across both model calls.
        "Usage": merge_usage(obs_usage, cand_usage),
        "Stages": {
            "observations": observations,
            # Room classifier predictions per photo (photoIndex matches the
            # observe model's image order) — auditable vs observations.roomType.
            "roomHints": room_hints,
            # Internal-repaint assumption audit: whether it fired and the per-room
            # areas (from gfa) that made up the assumed paint area.
            "paintAssumption": paint_decision,
            "candidates": {
                "validatedCandidates": validated,
                "rejectedCandidates": candidates.get("rejectedCandidates", []),
            },
            "toolInput": [
                {"_id": e["_id"], "name": e["name"], "area": e["area"], "factor": e["factor"]}
                for e in detected
            ],
            # AIQS BCI audit: the state used and the factor applied per renovation
            # year (1.0 = no scaling / unavailable). FinalCost = rate × qty × factor.
            "bci": {"state": state, "factors": factors},
            # Room scaling audit: the manual multipliers / auto flag requested,
            # and what was actually applied per group.
            "roomScaling": {
                "manual": (req.config or {}).get("roomScale") or {},
                "auto": bool((req.config or {}).get("assumeAllRoomsRenovated")),
                "applied": room_counts,
            },
        },
    }
    if req.settlement_date:
        result["Previous Owner Total"] = _money(owner_totals["Previous Owner"])
        result["Current Owner Total"] = _money(owner_totals["Current Owner"])
    return result
