# Standard floor area per room type, in square metres.
SQM_PER_ROOM = {"bedroom": 12, "bathroom": 6, "kitchen": 8}


def calculate_gfa(
    property_gfa: float, bedrooms: int = 0, bathrooms: int = 0, kitchens: int = 0
) -> dict:
    """Break a property's GFA into per-room-type area and the leftover living space.

    Each bedroom is 12sqm, bathroom 6sqm, kitchen 8sqm. Living space is whatever
    GFA remains after subtracting those rooms.
    """
    rooms = {
        "bedroom": bedrooms * SQM_PER_ROOM["bedroom"],
        "bathroom": bathrooms * SQM_PER_ROOM["bathroom"],
        "kitchen": kitchens * SQM_PER_ROOM["kitchen"],
    }
    # Clamp at 0: when the counted rooms already exceed the floor area (small or
    # bad floorArea vs many rooms), there's no leftover living space — and a
    # negative value would later flip sqm costs negative in price_items.
    rooms["livingSpace"] = max(property_gfa - sum(rooms.values()), 0)
    return rooms


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def gfa_from_property(property_data: dict) -> dict | None:
    """GFA breakdown derived from a property's rpdata attributes.

    `floorArea` is the total GFA; `beds`/`baths` are the room counts (one kitchen
    assumed). Returns None when `floorArea` is missing, so the caller can fall
    back (e.g. ask the user for the area). This is plain arithmetic on data we
    already hold — the model never computes it, it just uses the result.
    """
    area = _to_float(property_data.get("floorArea"))
    if not area:
        return None
    return calculate_gfa(
        area,
        bedrooms=int(_to_float(property_data.get("beds"))),
        bathrooms=int(_to_float(property_data.get("baths"))),
        kitchens=1,
    )
