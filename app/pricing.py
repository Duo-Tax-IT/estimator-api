def _name_index(library: dict) -> dict:
    """Catalog keyed by name, but only for names that are unique — many child
    items share a name (e.g. "Tapware"), so an ambiguous name can't be matched.
    """
    counts: dict = {}
    for it in library.values():
        counts[it["name"]] = counts.get(it["name"], 0) + 1
    return {it["name"]: it for it in library.values() if counts[it["name"]] == 1}


def price_items(
    items: list[dict], library: dict, living_space: float | None = None
) -> dict:
    """Price detected renovation items from the authoritative catalog.

    Each item carries `_id`, an optional `name`, for `sqm` items an `area` (m²),
    and an optional `factor` (the AIQS BCI cost-scaling factor, default 1.0).
    Rate, unit and quantity are read from `library` (the megamind catalog keyed
    by `_id`) — never from the model — so pricing can't be altered. sqm areas
    are scaled down proportionally if their total exceeds `living_space`, then:
    `FinalCost = DefaultRate × Quantity × factor`.

    An item is matched by `_id`; if that misses (the model mistyped it), it
    falls back to its `name` when that name is unique in the catalog. Items that
    still don't match are skipped (nothing to price).
    Returns {"renovations": [...], "total": <float>} with numeric fields.
    """
    by_name = _name_index(library)
    priced, sqm_items = [], []
    for item in items:
        lib = library.get(item.get("_id")) or by_name.get(item.get("name"))
        if not lib:
            continue
        unit = lib.get("unit")
        if unit == "sqm":
            quantity = float(item.get("area") or 1)
        else:
            quantity = lib.get("defaultQuantity") or 1
        row = {
            "_id": lib["_id"],
            "Name": lib["name"],
            "Unit": unit,
            "DefaultRate": lib["defaultRate"],
            "Quantity": quantity,
            "Factor": item.get("factor", 1.0),
            "parentName": lib.get("parentName"),
        }
        priced.append(row)
        if unit == "sqm":
            sqm_items.append(row)

    used = sum(r["Quantity"] for r in sqm_items)
    if living_space and used > living_space:
        for r in sqm_items:
            r["Quantity"] *= living_space / used

    for r in priced:
        r["FinalCost"] = float(r["DefaultRate"]) * r["Quantity"] * r["Factor"]
    return {"renovations": priced, "total": sum(r["FinalCost"] for r in priced)}
