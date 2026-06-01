import httpx

from .config import get_settings
from .errors import RpDataFetchError
from .schemas import Photo

# Preference order for the URL we feed the vision model.
_URL_FIELDS = ("largePhotoUrl", "mediumPhotoUrl", "basePhotoUrl")

# Google street-view / satellite shots arrive in the same payload (as
# digitalAssetType "Image" with maps.googleapis.com URLs) but are useless for
# spotting interior renovations, so we drop them.
_EXCLUDED_URL_HOSTS = ("maps.googleapis.com",)

# rpdata groups a property's attributes under these keys; we flatten both into a
# single `property` dict for the model's context (see fetch_property).
_PROPERTY_ATTR_GROUPS = ("attrCore", "attrAdditional")


def _property_url(rp_id: str) -> str:
    """Base rpdata URL for a property (e.g. https://calc.duo.tax/property/<rp_id>)."""
    settings = get_settings()
    if not settings.rpdata_api_url:
        raise RpDataFetchError("RPDATA_API_URL is not configured")
    return settings.rpdata_api_url.format(rp_id=rp_id)


def _get_json(url: str, rp_id: str, what: str):
    """GET `url` and return the parsed JSON body.

    Raises RpDataFetchError if rpdata is unreachable, returns a non-2xx status,
    or returns a body that isn't valid JSON. `what` names the resource for
    error messages (e.g. "photos", "property").
    """
    settings = get_settings()
    headers = {}
    if settings.rpdata_api_auth:
        headers["Authorization"] = settings.rpdata_api_auth

    try:
        resp = httpx.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise RpDataFetchError(
            f"Could not fetch {what} for rp_id {rp_id}: {exc}"
        ) from exc

    try:
        return resp.json()
    except ValueError as exc:
        raise RpDataFetchError(
            f"RP Data API returned non-JSON {what} for rp_id {rp_id}"
        ) from exc


def fetch_photos(rp_id: str) -> list[Photo]:
    """Fetch a property's photos from rpdata (calc.duo.tax) by rp_id."""
    payload = _get_json(_property_url(rp_id).rstrip("/") + "/photos", rp_id, "photos")
    if not isinstance(payload, list):
        raise RpDataFetchError(
            f"RP Data API returned {type(payload).__name__}, expected a list, "
            f"for rp_id {rp_id}"
        )
    return _map_photos(payload)


def fetch_property(rp_id: str) -> dict:
    """Fetch a property's attributes from rpdata and flatten them into one dict.

    The rpdata payload groups attributes under `attrCore` and `attrAdditional`;
    both are merged into a single flat dict used as the model's `property`
    context when the caller doesn't supply their own.
    """
    payload = _get_json(_property_url(rp_id), rp_id, "property")
    if not isinstance(payload, dict):
        raise RpDataFetchError(
            f"RP Data API returned {type(payload).__name__}, expected an object, "
            f"for rp_id {rp_id}"
        )
    merged: dict = {}
    for group in _PROPERTY_ATTR_GROUPS:
        section = payload.get(group)
        if isinstance(section, dict):
            merged.update(section)
    return merged


def _map_photos(items: list[dict]) -> list[Photo]:
    """Map the rpdata payload into the Photo shape the model consumes.

    Keeps only real images (digitalAssetType == "Image", not noPhotoAvailable),
    drops Google street-view/satellite shots, and orders newest-first so the
    MAX_PHOTOS cap in openai_client keeps the most recent interiors rather than
    stale exterior photos.
    """
    photos = []
    for item in items:
        if item.get("digitalAssetType") != "Image" or item.get("noPhotoAvailable"):
            continue
        url = next((item[f] for f in _URL_FIELDS if item.get(f)), None)
        if not url:
            continue
        if any(host in url for host in _EXCLUDED_URL_HOSTS):
            continue
        photos.append(Photo(url=url, date=item.get("scanDate")))
    # Newest first; photos without a date sort last.
    photos.sort(key=lambda p: p.date or "", reverse=True)
    return photos
