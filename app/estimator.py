import json

import openai

from .config import get_settings
from .errors import BciFetchError, ItemsFetchError, ModelError, NoPhotosError
from .gfa import gfa_from_property
from .megamind_client import fetch_bci_factor, fetch_renovation_items
from .openai_client import build_input_text, generate_estimate
from .pricing import dedup_by_id, expand_to_leaves, price_items
from .prompts import get_base_prompt
from .rpdata_client import extract_state, fetch_photos, fetch_property
from .schemas import EstimateRequest


# The only catalog fields the model needs to match items. Rate and quantity are
# server-side only — the model is forbidden from pricing — so they're withheld to
# keep it from reasoning about cost (price_items still uses the full catalog).
_MODEL_ITEM_FIELDS = ("_id", "name", "unit", "parentName")


def _trim_catalog(items: list[dict]) -> list[dict]:
    return [{k: it.get(k) for k in _MODEL_ITEM_FIELDS} for it in items]


# The catalog's only property-type variants: a unit uses the apartment kitchen,
# a house the house kitchen. Anything else (commercial/unknown) keeps both and
# lets the model choose.
_KITCHEN_VARIANTS = {"Kitchen - House", "Kitchen - Apartment"}
_KITCHEN_FOR_TYPE = {"UNIT": "Kitchen - Apartment", "HOUSE": "Kitchen - House"}


def filter_catalog_for_property(items: list[dict], property_data: dict) -> list[dict]:
    """Drop the inapplicable kitchen variant and its whole subtree so the model
    can't match the wrong one for the property type. A no-op when the type isn't
    UNIT or HOUSE (e.g. commercial/unknown — keep both, don't guess).
    """
    keep = _KITCHEN_FOR_TYPE.get(str(property_data.get("propertyType", "")).upper())
    if not keep:
        return items
    drop_ids = {it["_id"] for it in items if it["name"] in _KITCHEN_VARIANTS - {keep}}
    changed = True
    while changed:  # extend to the dropped parent's descendant subtree, by id
        changed = False
        for it in items:
            if it.get("parentId") in drop_ids and it["_id"] not in drop_ids:
                drop_ids.add(it["_id"])
                changed = True
    return [it for it in items if it["_id"] not in drop_ids]


def _build_model_input(
    property_data: dict, renovation_items: list[dict], config: dict, gfa: dict | None
) -> dict:
    """The JSON payload the prompt expects.

    Photos are sent separately as vision images (see openai_client), so they
    are not duplicated here. `renovationItems` is the megamind catalog, trimmed
    to the fields the model may use; `property_data` is the (caller- or
    rpdata-sourced) attributes, `gfa` is the backend-computed area breakdown the
    model uses to size sqm items, and `config` is optional context.
    """
    return {
        "property": property_data,
        "renovationItems": _trim_catalog(renovation_items),
        "gfa": gfa,
        # Pricing-only flags (room scaling) are dropped — the model never needs
        # them and they'd just clutter the prompt.
        "config": {k: v for k, v in config.items() if k not in _PRICING_CONFIG_KEYS},
    }


def _money(value: float) -> str:
    return f"${value:,.2f}"


def split_by_owner(renovations: list[dict], settlement_date: str | None) -> dict:
    """Tag priced renovations as previous- or current-owner and total each.

    A renovation whose `Year` predates the settlement year (YYYY-MM-DD) is the
    previous owner's; everything else (including unknown years, or when no
    settlement date is given) is the current owner's. Sets `Owner` on each item
    in place and returns {"Previous Owner": <float>, "Current Owner": <float>}.
    Expects numeric `FinalCost` (the priced renovations, before currency formatting).
    """
    head = (settlement_date or "")[:4]
    settle_year = int(head) if head.isdigit() else None
    totals = {"Previous Owner": 0.0, "Current Owner": 0.0}
    for reno in renovations:
        year = str(reno.get("Year", ""))
        is_prev = settle_year and year.isdigit() and int(year) < settle_year
        reno["Owner"] = "Previous Owner" if is_prev else "Current Owner"
        totals[reno["Owner"]] += reno.get("FinalCost", 0) * reno.get("Count", 1)
    return totals


# A renovation's top-level group → its room type. A detected room reno can be
# counted more than once: manually (config.roomScale, e.g. {"bathroom": 2}) or
# automatically per the property's room count (config.assumeAllRoomsRenovated).
_ROOM_OF_GROUP = {
    "Bathroom": "bathroom",
    "Bathroom - Additional Items": "bathroom",
    "Kitchen - House": "kitchen",
    "Kitchen - Apartment": "kitchen",
    "Kitchen - Additional Items": "kitchen",
    "Built-in Wardrobes": "bedroom",
}
# Property attribute holding each room type's count (auto option). Kitchen → 1.
_ROOM_COUNT_ATTR = {"bathroom": "baths", "bedroom": "beds"}

# Pricing-only config keys — kept out of the model input so the prompt stays
# clean (they steer pricing, the model never needs them).
_PRICING_CONFIG_KEYS = {"roomScale", "assumeAllRoomsRenovated"}


def _as_num(value, default: float = 1.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def apply_room_counts(
    renovations: list[dict], property_data: dict, config: dict
) -> float:
    """Tag each renovation with a `Count` and return the count-scaled total.

    A room-scoped renovation (kitchen / bathroom / bedroom) can be counted more
    than once:
      • Manual — `config['roomScale']` maps a room type to a multiplier, e.g.
        {"bathroom": 2, "kitchen": 1}. Takes precedence; dial the numbers by hand.
      • Auto — when `config['assumeAllRoomsRenovated']` is set, the room is
        counted once per such room in the property (bathrooms→`baths`,
        bedrooms→`beds`).
    Line-item quantities stay one room's worth; the multiplier hits the total
    (and the UI subtotal) via `FinalCost × Count`. `Count` defaults to 1.
    `CountOf` (the room type) is set on scaled rows for the UI label.
    """
    manual = config.get("roomScale") or {}
    auto = bool(config.get("assumeAllRoomsRenovated"))
    total = 0.0
    for reno in renovations:
        root = (reno.get("groupPath") or [reno.get("Name")])[0]
        rtype = _ROOM_OF_GROUP.get(root)
        if rtype:
            # Tag the room type so the UI can apply manual multipliers live.
            reno["RoomType"] = rtype
        count, label = 1.0, None
        if rtype and rtype in manual:
            count, label = max(_as_num(manual.get(rtype)), 0.0), rtype
        elif rtype and auto and rtype in _ROOM_COUNT_ATTR:
            count = max(_as_num(property_data.get(_ROOM_COUNT_ATTR[rtype]), 1), 1.0)
            label = rtype
        reno["Count"] = count
        if count != 1:
            reno["CountOf"] = label
        total += float(reno.get("FinalCost", 0)) * count
    return total


def _bci_factor(state: str | None, year, cache: dict) -> float:
    """AIQS BCI cost-scaling factor for a renovation year + state; 1.0 otherwise.

    Best-effort: a missing state/year or a BCI fetch failure falls back to 1.0
    (no scaling) rather than failing the estimate. `cache` memoises by year so a
    run hits the endpoint once per distinct year. The year is dated to 1 July.
    """
    if not state or not year or not str(year).isdigit():
        return 1.0
    if year not in cache:
        try:
            cache[year] = fetch_bci_factor(state, f"{year}-07-01")
        except BciFetchError:
            cache[year] = 1.0
    return cache[year]


def _format_renovations(renovations: list[dict]) -> list[dict]:
    """Format each line item's currency fields, leave the rest as-is."""
    formatted = []
    for reno in renovations:
        item = dict(reno)
        if "DefaultRate" in item:
            item["DefaultRate"] = _money(float(item["DefaultRate"]))
        if "FinalCost" in item:
            item["FinalCost"] = _money(float(item["FinalCost"]))
        formatted.append(item)
    return formatted


def preview_estimate_prompt(req: EstimateRequest) -> str:
    """The exact prompt text the model would receive for this request — debug.

    Same upstream fetches as build_full_estimate (renovation items + property),
    minus the photos and the model call.
    """
    prompt = get_base_prompt(get_settings().estimator_prompt_file)
    renovation_items = fetch_renovation_items()
    property_data = req.property or fetch_property(req.rp_id)
    gfa = gfa_from_property(property_data)
    model_input = _build_model_input(
        property_data, renovation_items, req.config or {}, gfa
    )
    return prompt + "\n\n" + build_input_text(model_input)


def build_full_estimate(req: EstimateRequest) -> dict:
    """Detect renovations from a property's photos against the megamind catalog.

    Fetches the renovation-items catalog from megamind and the property's photos
    from rpdata (by rp_id) — plus its attributes when the caller supplies no
    `property` override — has the vision model match them
    (FinalCost = DefaultRate x Quantity), then reshapes/currency-formats the
    output. Raises ItemsFetchError / NoPhotosError when an upstream yields
    nothing usable, and ModelError when the model call or its output fails.
    """
    prompt = get_base_prompt(get_settings().estimator_prompt_file)
    model = req.model or get_settings().default_model

    renovation_items = fetch_renovation_items()
    if not renovation_items:
        raise ItemsFetchError("Megamind returned no usable renovation items")

    photos = fetch_photos(req.rp_id)
    if not photos:
        raise NoPhotosError(f"No usable photos found for rp_id {req.rp_id}")

    # Use the caller-supplied property as an override; otherwise fall back to
    # the attributes rpdata holds for this rp_id.
    property_data = req.property or fetch_property(req.rp_id)

    # Show the model only the kitchen variant that fits this property type.
    renovation_items = filter_catalog_for_property(renovation_items, property_data)

    # GFA is plain arithmetic on the property's attributes — computed here and
    # handed to the model as context, not via a tool call. livingSpace caps the
    # total sqm area both during the model's pricing call and the final pricing.
    gfa = gfa_from_property(property_data)
    living = gfa["livingSpace"] if gfa else None

    # The full catalog keyed by _id. The model is sent a trimmed copy (no rates),
    # but pricing — here and in the model's tool call — needs the full records.
    library = {it["_id"]: it for it in renovation_items}

    try:
        raw, usage = generate_estimate(
            model,
            prompt,
            _build_model_input(property_data, renovation_items, req.config or {}, gfa),
            photos,
            library=library,
            living_space=living,
            reasoning_effort=req.reasoning_effort,
            temperature=req.temperature,
        )
    except openai.OpenAIError as exc:
        raise ModelError(f"Vision model call failed: {exc}") from exc

    try:
        estimate = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ModelError("Vision model returned invalid JSON") from exc

    # The model only detects items (_id, sqm area as Quantity, Year); all pricing
    # is computed from the catalog by price_items — the same function the model
    # tool-calls — so the model can't set rates, quantities or costs. `Name` is
    # passed alongside `_id` so price_items can recover an item the model matched
    # but whose _id it transcribed wrong.
    detected = estimate.get("Renovations", [])
    # Scale each item's cost by the AIQS BCI factor for the property's state and
    # the item's renovation year (best-effort; 1.0 when unavailable). A whole-room
    # match (a 0-rate parent, e.g. "Kitchen - House") is expanded to its leaf
    # items, then de-duplicated so a parent + child match can't double-count.
    state = extract_state(req.address)
    factors: dict = {}
    items = [
        {
            "_id": r.get("_id"),
            "name": r.get("Name"),
            "area": r.get("Quantity"),
            "factor": _bci_factor(state, r.get("Year"), factors),
            "Year": r.get("Year"),
        }
        for r in detected
    ]
    items = dedup_by_id(expand_to_leaves(items, library))
    priced = price_items(items, library, living)
    renovations = priced["renovations"]
    years = {e["_id"]: e.get("Year") for e in items}
    for reno in renovations:
        reno["Year"] = years.get(reno["_id"], "")

    # Count a room-scoped reno once per such room (opt-in); returns the scaled
    # total. Sets Count on each row, which split_by_owner also honours.
    total = apply_room_counts(renovations, property_data, req.config or {})
    # Tags each renovation's Owner in place; must run before _format_renovations.
    owner_totals = split_by_owner(renovations, req.settlement_date)

    result = {
        "Renovations": _format_renovations(renovations),
        "Renovations Total": _money(total),
        "Property": property_data,
        "GFA": gfa,
        "Summary Description": estimate.get("Summary Description", ""),
        # The model's "Guarantee" field is a fixed disclaimer sentence.
        "Disclaimer": estimate.get("Guarantee", ""),
        # Token counts + USD cost for this run; saved with the run for the UI.
        "Usage": usage,
    }
    # Only split when a settlement date was given (else every item is current).
    if req.settlement_date:
        result["Previous Owner Total"] = _money(owner_totals["Previous Owner"])
        result["Current Owner Total"] = _money(owner_totals["Current Owner"])
    return result
