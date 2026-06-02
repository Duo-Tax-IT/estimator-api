def _name_index(library: dict) -> dict:
    """Catalog keyed by name, but only for names that are unique — many child
    items share a name (e.g. "Tapware"), so an ambiguous name can't be matched.
    """
    counts: dict = {}
    for it in library.values():
        counts[it["name"]] = counts.get(it["name"], 0) + 1
    return {it["name"]: it for it in library.values() if counts[it["name"]] == 1}


def expand_to_leaves(items: list[dict], library: dict) -> list[dict]:
    """Expand any matched parent (a grouping row, e.g. "Kitchen - House", priced
    at 0) into its descendant leaf items, so a whole-room match prices from its
    parts. The catalog tree is nested and names repeat (two "Joinery" groups), so
    it is walked by `parentId`, not name.

    A matched leaf is returned unchanged; a matched parent contributes its leaves,
    each inheriting the entry's other fields (year, factor, …) with `area` cleared
    (leaves are priced by their own catalog unit/quantity). An `_id` not in the
    catalog is returned unchanged.
    """
    children: dict = {}
    for it in library.values():
        if it.get("parentId"):
            children.setdefault(it["parentId"], []).append(it)

    def leaves(item: dict) -> list[dict]:
        kids = children.get(item["_id"])
        if not kids:
            return [item]
        return [leaf for kid in kids for leaf in leaves(kid)]

    out = []
    for entry in items:
        lib = library.get(entry.get("_id"))
        descendants = leaves(lib) if lib else None
        if descendants and descendants != [lib]:  # entry matched a parent
            for leaf in descendants:
                out.append({**entry, "_id": leaf["_id"], "name": leaf["name"], "area": None})
        else:
            out.append(entry)
    return out


def dedup_by_id(items: list[dict]) -> list[dict]:
    """Keep the first entry per `_id` — a parent + child match, or a repeat, must
    not double-count."""
    seen, out = set(), []
    for entry in items:
        key = entry.get("_id")
        if key not in seen:
            seen.add(key)
            out.append(entry)
    return out


def _ancestry(item: dict, library: dict) -> list[str]:
    """Ancestor names from the root down to the item's immediate parent, resolved
    by walking `parentId` through the catalog. Empty for a top-level item. Lets
    the UI nest a grandchild (e.g. Kitchen - House › Joinery › Benchtop) instead
    of flattening it under its immediate parent only.
    """
    path: list[str] = []
    seen: set = set()
    cur = library.get(item.get("parentId"))
    while cur and cur["_id"] not in seen:
        seen.add(cur["_id"])
        path.append(cur["name"])
        cur = library.get(cur.get("parentId"))
    return list(reversed(path))


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
            "groupPath": _ancestry(lib, library),
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
