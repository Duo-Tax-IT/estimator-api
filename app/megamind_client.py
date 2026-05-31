import httpx

from .config import get_settings
from .errors import ItemsFetchError

# Path appended to the megamind base URL (MEGAMIND_API_URL) for the catalog.
_ITEMS_PATH = "/api/external/estimator-items"


def fetch_renovation_items() -> list[dict]:
    """Fetch the renovation-items catalog from megamind.

    This is the authoritative dataset the vision model matches photos against,
    fetched fresh on every estimate. Raises ItemsFetchError if megamind is
    unreachable / unauthorized or returns an unexpected body.
    """
    settings = get_settings()
    if not settings.megamind_api_url:
        raise ItemsFetchError("MEGAMIND_API_URL is not configured")
    if not settings.megamind_api_key:
        raise ItemsFetchError(
            "MEGAMIND_API_KEY is not set (required to fetch renovation items)"
        )

    url = settings.megamind_api_url.rstrip("/") + _ITEMS_PATH
    try:
        resp = httpx.get(
            url,
            headers={"X-API-KEY": settings.megamind_api_key},
            timeout=30,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise ItemsFetchError(
            f"Could not fetch renovation items from megamind: {exc}"
        ) from exc

    try:
        payload = resp.json()
    except ValueError as exc:
        raise ItemsFetchError(
            "Megamind returned non-JSON for renovation items"
        ) from exc

    if not isinstance(payload, list):
        raise ItemsFetchError(
            f"Megamind returned {type(payload).__name__}, expected a list"
        )

    return _map_items(payload)


def _map_items(items: list[dict]) -> list[dict]:
    """Map megamind items into the {_id, name, defaultRate, unit} shape the
    prompt expects (megamind's `id` becomes `_id`).

    Drops soft-deleted items and anything missing an id, name, or rate (without
    which the model cannot match or price it). The audit fields and `sections`
    are dropped to keep the model input compact. To restrict to vetted items,
    also skip `not item.get("isVerified")` below.
    """
    mapped = []
    for item in items:
        if item.get("isDeleted"):
            continue
        item_id = item.get("id")
        name = item.get("name")
        rate = item.get("defaultRate")
        if not item_id or not name or rate is None:
            continue
        mapped.append(
            {
                "_id": item_id,
                "name": name,
                "defaultRate": rate,
                "unit": item.get("unit"),
            }
        )
    return mapped
