import httpx

from ..config import get_settings
from ..errors import BciFetchError, EstimatorError, ItemsFetchError

# Path appended to the megamind base URL (MEGAMIND_API_URL) for the catalog.
_ITEMS_PATH = "/api/external/estimator-items"
# AIQS BCI factor endpoint: returns past/present (present fixed server-side to
# 2026-07), with factor 1.0 as the no-scaling fallback for unknown state/index.
_BCI_FACTOR_PATH = "/api/external/aiqs-bci/factor"


def _megamind_get(path: str, error: type[EstimatorError], params: dict | None = None):
    """GET a megamind external endpoint with the API key and return parsed JSON.

    Raises `error` if megamind is unconfigured, unreachable/unauthorized, or
    returns a non-JSON body.
    """
    settings = get_settings()
    if not settings.megamind_api_url:
        raise error("MEGAMIND_API_URL is not configured")
    if not settings.megamind_api_key:
        raise error("MEGAMIND_API_KEY is not set")

    url = settings.megamind_api_url.rstrip("/") + path
    try:
        resp = httpx.get(
            url,
            headers={"X-API-KEY": settings.megamind_api_key},
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise error(f"Could not fetch {path} from megamind: {exc}") from exc

    try:
        return resp.json()
    except ValueError as exc:
        raise error(f"Megamind returned non-JSON for {path}") from exc


def fetch_renovation_items() -> list[dict]:
    """Fetch the renovation-items catalog from megamind.

    This is the authoritative dataset the vision model matches photos against,
    fetched fresh on every estimate. Raises ItemsFetchError if megamind is
    unreachable / unauthorized or returns an unexpected body.
    """
    payload = _megamind_get(_ITEMS_PATH, ItemsFetchError)
    if not isinstance(payload, list):
        raise ItemsFetchError(
            f"Megamind returned {type(payload).__name__}, expected a list"
        )
    return _map_items(payload)


def _map_items(items: list[dict]) -> list[dict]:
    """Map megamind items into the {_id, name, defaultRate, unit} shape the
    prompt expects (megamind's `id` becomes `_id`).

    Drops soft-deleted items and anything missing an id, name, or rate (without
    which the model cannot match or price it). `isVerified` is intentionally
    ignored — the full (non-deleted) catalog is sent. The audit fields and
    `sections` are dropped to keep the model input compact.

    `parentName` is resolved from the full raw payload, so a label-only parent
    (no rate, dropped from the catalog) still names its children's group.
    """
    names = {i.get("id"): i.get("name") for i in items if i.get("id")}
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
                "defaultQuantity": item.get("defaultQuantity"),
                "parentId": item.get("parentId"),
                "parentName": names.get(item.get("parentId")),
            }
        )
    return mapped


def fetch_bci_factor(state: str, date: str) -> float:
    """The AIQS BCI cost-scaling factor for a state + past date.

    `state` is an AU abbreviation (NSW/QLD/…, case-insensitive); `date` is
    `YYYY-MM-DD` and is snapped to the nearest quarter server-side. The present
    period is fixed to 2026-07. Multiply a present-day cost by the result to get
    that date's period equivalent. The endpoint returns 1.0 (no scaling) for an
    unknown state or missing index, so no local fallback is needed. Raises
    BciFetchError only on transport/parse failures.
    """
    payload = _megamind_get(
        _BCI_FACTOR_PATH, BciFetchError, params={"state": state, "date": date}
    )
    return payload.get("factor", 1.0)
