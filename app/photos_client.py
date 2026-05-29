import httpx

from .config import get_settings
from .schemas import Photo

# Preference order for the URL we feed the vision model.
_URL_FIELDS = ("largePhotoUrl", "mediumPhotoUrl", "basePhotoUrl")


def fetch_photos(rp_id: str) -> list[Photo]:
    """Fetch a property's photos from the configured photos API by rp_id."""
    settings = get_settings()
    if not settings.photos_api_url:
        raise RuntimeError("PHOTOS_API_URL is not configured")

    url = settings.photos_api_url.format(rp_id=rp_id)
    headers = {}
    if settings.photos_api_auth:
        headers["Authorization"] = settings.photos_api_auth

    resp = httpx.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return _map_photos(resp.json())


def _map_photos(items: list[dict]) -> list[Photo]:
    """Map the photos-API payload into the Photo shape the model consumes."""
    photos = []
    for item in items:
        if item.get("digitalAssetType") != "Image" or item.get("noPhotoAvailable"):
            continue
        url = next((item[f] for f in _URL_FIELDS if item.get(f)), None)
        if not url:
            continue
        photos.append(Photo(url=url, date=item.get("scanDate")))
    return photos
