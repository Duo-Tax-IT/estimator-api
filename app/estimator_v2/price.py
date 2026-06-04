from datetime import date

from ..estimator import _bci_factor, apply_room_counts, split_by_owner
from ..helpers.pricing import dedup_by_id, expand_to_leaves, price_items
from ..clients.rpdata_client import extract_state
from ..schemas import EstimateRequest

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


def _internal_paint_row(validated, observations, property_data, config, gfa, library):
    """A synthetic 'Painting - Internal' detected-row when the repaint assumption
    applies, plus a decision record for Stages; (None, decision) otherwise.

    Gated on: config opt-in, property age >= REPAINT_MIN_AGE, and the model seeing
    visibly sound paint (clean/new_like, none worn/poor) in a room type. The area
    reuses the per-room buckets already computed in `gfa`. Year is left unknown
    (no fabricated date -> BCI factor 1.0, current-owner by default); `capExempt`
    keeps it out of the livingSpace sqm cap so it can't shrink real flooring.
    """
    # On by default (the area-based repaint is a major, size-scaling cost most
    # estimates need); send assumeInternalRepaint=false to opt out.
    if not config.get("assumeInternalRepaint", True):
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
