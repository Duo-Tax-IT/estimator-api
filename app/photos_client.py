import httpx

from .config import get_settings
from .errors import PhotosFetchError
from .schemas import Photo

# Preference order for the URL we feed the vision model.
_URL_FIELDS = ("largePhotoUrl", "mediumPhotoUrl", "basePhotoUrl")

# Google street-view / satellite shots arrive in the same payload (as
# digitalAssetType "Image" with maps.googleapis.com URLs) but are useless for
# spotting interior renovations, so we drop them.
_EXCLUDED_URL_HOSTS = ("maps.googleapis.com",)


def fetch_photos(rp_id: str) -> list[Photo]:
    """Fetch a property's photos from calc.duo.tax by rp_id.

    Raises PhotosFetchError if the API is unreachable, returns a non-2xx
    status, or returns a body that isn't the expected JSON array.
    """
    settings = get_settings()
    if not settings.photos_api_url:
        raise PhotosFetchError("PHOTOS_API_URL is not configured")

    url = settings.photos_api_url.format(rp_id=rp_id)
    headers = {}
    if settings.photos_api_auth:
        headers["Authorization"] = settings.photos_api_auth

    try:
        resp = httpx.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise PhotosFetchError(
            f"Could not fetch photos for rp_id {rp_id}: {exc}"
        ) from exc

    try:
        payload = resp.json()
    except ValueError as exc:
        raise PhotosFetchError(
            f"Photos API returned non-JSON for rp_id {rp_id}"
        ) from exc

    if not isinstance(payload, list):
        raise PhotosFetchError(
            f"Photos API returned {type(payload).__name__}, expected a list, "
            f"for rp_id {rp_id}"
        )

    return _map_photos(payload)


def _map_photos(items: list[dict]) -> list[Photo]:
    """Map the calc.duo.tax payload into the Photo shape the model consumes.

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
