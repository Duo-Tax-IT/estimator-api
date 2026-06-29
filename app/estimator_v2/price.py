from datetime import date

from ..estimator import _bci_factor, split_by_owner
from ..helpers.pricing import dedup_by_id, expand_to_leaves, price_items
from ..clients.rpdata_client import extract_state
from ..schemas import EstimateRequest

# Internal-repaint assumption (QS convention, opt-in via config.assumeInternalRepaint).
# An old property whose interior paint reads sound is assumed repainted, sized from
# the per-room areas already in `gfa`.
REPAINT_MIN_AGE = 10
NEW_BUILD_MAX_AGE = 2  # builds this recent never get the repaint assumption
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
    f"properties over {REPAINT_MIN_AGE} years old, or younger renovated "
    "properties whose interior paint appears fresh. The repaint is an "
    "assumption, not confirmed from the images."
)


def _internal_paint_row(validated, observations, property_data, config, gfa, library):
    """A synthetic 'Painting - Internal' detected-row when the repaint assumption
    applies, plus a decision record for Stages; (None, decision) otherwise.

    Gated on config opt-in, then an age/renovation ladder: a brand-new build
    never gets the assumption (fresh paint is the original finish); an old
    property gets it by QS convention (rooms count unless visibly worn/poor);
    a young property gets it only when other renovations exist AND paint reads
    `new_like` (the repaint rode along with the reno). The area reuses the
    per-room buckets already computed in `gfa`.
    Year is left unknown (BCI factor 1.0, current-owner by default); `capExempt`
    keeps it out of the livingSpace sqm cap so it can't shrink real flooring.
    """
    # On by default (the area-based repaint is a major, size-scaling cost most
    # estimates need); send assumeInternalRepaint=false to opt out.
    if not config.get("assumeInternalRepaint", True):
        return None, {"applied": False, "reason": "disabled"}
    built = str(property_data.get("yearBuilt", "")).strip()
    age = date.today().year - int(built) if built.isdigit() else None
    # Brand-new build: fresh paint is the builder's original finish.
    if age is not None and age <= NEW_BUILD_MAX_AGE:
        return None, {"applied": False, "reason": f"brand-new build ({built})"}
    old = age is None or age >= REPAINT_MIN_AGE
    # A young property only gets the assumption when other renovations exist —
    # a repaint then plausibly rode along with the reno.
    if not old and not validated:
        return None, {"applied": False, "reason": f"young property ({built}), no other renovations"}
    # Old: QS convention — any room not visibly worn/poor counts, cues or not.
    # Young-but-renovated: only rooms that actually read new_like count.
    fresh = ("average", "clean", "new_like", "unknown") if old else ("new_like",)
    paint = next((it for it in library.values() if it["name"] == INTERNAL_PAINT_NAME), None)
    if not paint or not gfa:
        return None, {"applied": False, "reason": "no paint item or no gfa"}
    if any(c.get("_id") == paint["_id"] for c in validated):
        return None, {"applied": False, "reason": "already detected by model"}
    # Room types whose photos pass the gate (none worn/poor); `fresh` is the
    # accepted conditions for this rung of the ladder.
    keys, rooms = set(), []
    for room_type, key in _PAINT_AREA_KEY.items():
        shots = [
            p for p in observations.get("photoObservations", [])
            if p.get("roomType") == room_type
        ]
        if not shots or any(p.get("condition") in ("worn", "poor") for p in shots):
            continue
        if any(p.get("condition") in fresh for p in shots):
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
        "applied": True, "reason": f"fresh paint in {rooms}",
        "rooms": rooms, "areas": areas, "totalArea": total,
    }
    return row, decision


EXTENSION_NAME = "House Extension"


def _extension_row(structural, property_data, state, factors, library):
    """A deterministic 'House Extension' sqm row when the structural step finds a
    storey/footprint increase the finish-based steps can't see. Mirrors the paint
    assumption: sized off the model's added-area estimate, `capExempt` so it
    neither shrinks nor is shrunk by the livingSpace floor cap. (None, decision)
    otherwise. Guarded like the year-guard: an addition dated at/before the build
    is the original build, not an extension."""
    added = float(structural.get("estimatedAddedAreaSqm") or 0)
    storeys_up = (structural.get("newStoreys") or 0) - (structural.get("oldStoreys") or 0)
    detected = structural.get("secondStoreyAdded") or storeys_up >= 1 or structural.get("majorExtension")
    if not detected or added <= 0:
        return None, {"applied": False, "reason": "no structural area increase"}
    year, built = str(structural.get("estimatedYear") or ""), str(property_data.get("yearBuilt", "")).strip()
    if year.isdigit() and built.isdigit() and int(year) <= int(built):
        return None, {"applied": False, "reason": f"estimatedYear {year} <= yearBuilt {built}"}
    item = next((it for it in library.values() if it["name"] == EXTENSION_NAME), None)
    if not item:
        return None, {"applied": False, "reason": f"no '{EXTENSION_NAME}' catalog item"}
    row = {"_id": item["_id"], "name": item["name"], "area": added,
           "factor": _bci_factor(state, year, factors), "Year": year, "capExempt": True}
    decision = {"applied": True, "reason": f"second-storey/extension (+{added} m²)",
                "area": added, "year": year, "confidence": structural.get("confidence"),
                "evidence": structural.get("evidence", [])}
    return row, decision


# Speculative $/sqm rate for a full (gut) renovation — a PLACEHOLDER to verify and
# tune (ideally from completed jobs' BuildCost ÷ GFA). Override per-run via
# config.gutRatePerSqm.
GUT_RATE_PER_SQM = 2000.0

GUT_DISCLAIMER = (
    "A full (gut) renovation was detected. The 'Full Renovation' line is a "
    "speculative whole-dwelling estimate sized from floor area — NOT an itemised "
    "measure. Verify the rate and amount before relying on it."
)


def _gut_row(gut: dict, gfa: dict | None, state, factors: dict, rate: float,
             itemized_total: float = 0.0):
    """A speculative whole-dwelling row when the analyze step flags a full (gut)
    renovation, sized off total GFA × `rate` (BCI-scaled at the gut's year).

    To avoid double-counting, the detected items are treated as measured components
    of the gut, so this row is only the BALANCE to the whole-dwelling estimate
    (whole − itemized). total then = itemized + balance = the whole-dwelling figure.
    Flagged `needsReview`. (None, decision) when no gut is detected."""
    if not gut.get("detected") or not gfa:
        return None, {"applied": False, "reason": "no gut renovation detected"}
    area = round(sum(gfa.values()), 1)  # buckets sum to the full floor area
    if area <= 0:
        return None, {"applied": False, "reason": "no GFA"}
    year = str(gut.get("estimatedYear") or "")
    factor = _bci_factor(state, year, factors)
    whole = rate * area * factor
    balance = max(0.0, whole - itemized_total)  # detected items already cover the rest
    evidence = "; ".join(gut.get("evidence") or [])
    reason = (
        f"Full (gut) renovation detected ({gut.get('confidence') or 'unknown'} confidence). "
        + (f"Why: {evidence}. " if evidence else "")
        + f"Whole-dwelling estimate = GFA {area:g} m² × ${rate:,.0f}/m²"
        + (f" × BCI {factor:.2f}{f' ({year})' if year else ''}" if factor != 1.0 else "")
        + f" = ${whole:,.0f}; ${itemized_total:,.0f} captured by the detected items "
          f"above, so this balance = ${balance:,.0f}. Speculative — verify."
    )
    row = {
        "_id": None, "Name": "Full Renovation balance (ESTIMATE — verify)", "Unit": "sqm",
        "DefaultRate": rate, "Quantity": area, "Factor": factor,
        "parentName": None, "groupPath": [], "FinalCost": balance,
        "Year": year, "needsReview": True, "Reason": reason,
    }
    decision = {"applied": True, "rate": rate, "area": area, "year": year,
                "factor": factor, "confidence": gut.get("confidence"),
                "wholeDwelling": whole, "itemized": itemized_total, "balance": balance,
                "reason": reason}
    return row, decision


def apply_year_guard(validated: list, candidates: dict, property_data: dict) -> list:
    """Drop candidates dated at/before original construction — that's the original
    build, not a renovation (guards "new build + modern finish" false positives).
    Rejected ones are appended to `candidates['rejectedCandidates']`; the original
    candidate objects are also kept in `candidates['yearGuardRejected']` so a
    gut-reno pass can resurface them as needs-review rows."""
    year_built = str(property_data.get("yearBuilt", "")).strip()
    if not year_built.isdigit():
        return validated
    rejects = candidates.setdefault("rejectedCandidates", [])
    dropped = candidates.setdefault("yearGuardRejected", [])
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
            dropped.append(c)
        else:
            kept.append(c)
    return kept


def price_validated(
    req: EstimateRequest, ctx: dict, validated: list, observations: dict,
    structural: dict | None = None, gut: dict | None = None,
) -> dict:
    """Step 3 — price (deterministic; same expand/dedup/price path as v1).

    A whole-room match (a 0-rate parent) is expanded to its leaf items, then
    de-duplicated so a parent + child match can't double-count. Injects the
    internal-repaint assumption, applies the BCI factor and owner split. Returns the
    priced rows plus the audit bits the Stages debug / playground surface (state,
    factors, paint)."""
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
    # Structural addition (second storey / extension): a deterministic capExempt
    # House Extension row the finish-based steps can't surface, sized off the
    # structural step's added-area estimate.
    ext_row, ext_decision = _extension_row(
        structural or {}, property_data, state, factors, library
    )
    if ext_row:
        detected.append(ext_row)
    detected = dedup_by_id(expand_to_leaves(detected, library))
    priced = price_items(detected, library, living)
    renovations = priced["renovations"]
    years = {e["_id"]: e.get("Year") for e in detected}
    for reno in renovations:
        reno["Year"] = years.get(reno["_id"], "")

    # Speculative whole-dwelling row when a full (gut) renovation is detected. Sized
    # off total GFA, but only the BALANCE over the detected items (which are its
    # components) — so the total reaches the whole-dwelling figure without double
    # counting. Appended after the per-item Year pass (it carries its own Year).
    rate = (req.config or {}).get("gutRatePerSqm", GUT_RATE_PER_SQM)
    itemized_total = sum(r.get("FinalCost", 0) for r in renovations)
    gut_row, gut_decision = _gut_row(gut or {}, gfa, state, factors, rate, itemized_total)
    if gut_row:
        renovations.append(gut_row)

    total = sum(r.get("FinalCost", 0) for r in renovations)
    # Tags each renovation's Owner in place; must run before _format_renovations.
    owner_totals = split_by_owner(renovations, req.settlement_date)
    return {
        "renovations": renovations,
        "total": total,
        "ownerTotals": owner_totals,
        "detected": detected,
        "state": state,
        "factors": factors,
        "paintDecision": paint_decision,
        "extensionDecision": ext_decision,
        "gutDecision": gut_decision,
    }
