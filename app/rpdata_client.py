import io
import re
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .config import get_settings
from .errors import NoPhotosError, RpDataFetchError
from .schemas import Photo

# AU state abbreviations, for pulling the state out of a display address.
_STATE = r"NSW|QLD|VIC|WA|SA|ACT|TAS|NT"

# Preference order for the URL we feed the vision model.
_URL_FIELDS = ("largePhotoUrl", "mediumPhotoUrl", "basePhotoUrl")

# Google street-view / satellite shots arrive in the same payload (as
# digitalAssetType "Image" with maps.googleapis.com URLs) but are useless for
# spotting interior renovations, so we drop them.
_EXCLUDED_URL_HOSTS = ("maps.googleapis.com",)

# rpdata groups a property's attributes under these keys; we flatten both into a
# single `property` dict for the model's context (see fetch_property).
_PROPERTY_ATTR_GROUPS = ("attrCore", "attrAdditional")


def _auth_headers() -> dict:
    """Authorization header for rpdata, when one is configured (else empty)."""
    auth = get_settings().rpdata_api_auth
    return {"Authorization": auth} if auth else {}


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
    try:
        resp = httpx.get(url, headers=_auth_headers(), timeout=30)
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


def extract_state(address: str | None) -> str | None:
    """The AU state abbreviation from a display address, or None.

    Prefers the state token right before a 4-digit postcode (the usual
    '… SUBURB SA 5067' form); else falls back to the last state token found.
    """
    if not address:
        return None
    anchored = re.search(rf"\b({_STATE})\b\s+\d{{4}}\b", address, re.IGNORECASE)
    if anchored:
        return anchored.group(1).upper()
    tokens = re.findall(rf"\b({_STATE})\b", address, re.IGNORECASE)
    return tokens[-1].upper() if tokens else None


def search_addresses(query: str) -> list[dict]:
    """Search calc.duo.tax for address suggestions matching `query`.

    Returns the raw `suggestions` list; each entry carries `suggestion` (the
    display string) and `suggestionId` — which is the property's rp_id. Raises
    RpDataFetchError if rpdata is unreachable or returns an unexpected body.
    """
    settings = get_settings()
    if not settings.rpdata_search_url:
        raise RpDataFetchError("RPDATA_SEARCH_URL is not configured")

    try:
        resp = httpx.get(
            settings.rpdata_search_url,
            params={"q": query},
            headers=_auth_headers(),
            timeout=30,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise RpDataFetchError(
            f"Could not search addresses for {query!r}: {exc}"
        ) from exc

    try:
        payload = resp.json()
    except ValueError as exc:
        raise RpDataFetchError(
            f"RP Data search returned non-JSON for {query!r}"
        ) from exc

    suggestions = payload.get("suggestions") if isinstance(payload, dict) else None
    if not isinstance(suggestions, list):
        raise RpDataFetchError(
            f"RP Data search returned no suggestions list for {query!r}"
        )
    return suggestions


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


def _photo_filename(index: int, photo: Photo) -> str:
    """A stable, sortable name inside the zip: 00_<scanDate>.<ext>."""
    ext = Path(urlparse(photo.url).path).suffix or ".jpg"
    return f"{index:02d}_{photo.date or 'unknown'}{ext}"


def build_photos_zip(rp_id: str) -> bytes:
    """Fetch a property's usable photos and pack them into a zip (in-memory).

    Reuses fetch_photos (same filtered/sorted set the estimator sees). An image
    that fails to download is skipped rather than failing the whole zip.
    """
    photos = fetch_photos(rp_id)
    if not photos:
        raise NoPhotosError(f"No usable photos found for rp_id {rp_id}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, photo in enumerate(photos):
            try:
                resp = httpx.get(photo.url, timeout=30)
                resp.raise_for_status()
            except httpx.HTTPError:
                continue
            zf.writestr(_photo_filename(i, photo), resp.content)
    return buf.getvalue()
