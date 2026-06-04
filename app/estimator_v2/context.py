from ..config import get_settings
from ..errors import ItemsFetchError, MissingBuildYearError, NoPhotosError
from ..estimator import filter_catalog_for_property
from ..helpers.gfa import gfa_from_property
from ..clients.megamind_client import fetch_renovation_items
from ..helpers.photo_dedup import dedup_photos
from ..clients.openai_client import MAX_PHOTOS
from ..clients.rpdata_client import fetch_photos, fetch_property
from ..schemas import EstimateRequest


def _ensure_build_year(property_data: dict, build_year, required: bool) -> None:
    """yearBuilt drives the year-guard and the paint age gate. Fill it from the
    request's `buildYear` when the property has none. When `required` (every step
    that uses the year — i.e. all but the Step 0 context fetch), raise
    MissingBuildYearError if neither source supplies a valid year."""
    if str(property_data.get("yearBuilt", "")).strip().isdigit():
        return
    if build_year is not None:
        property_data["yearBuilt"] = build_year
        return
    if required:
        raise MissingBuildYearError(
            "This property has no build year. Provide `buildYear` in the request."
        )


def fetch_v2_context(req: EstimateRequest, require_build_year: bool = True) -> dict:
    """Upstream fetch shared by every v2 step: the property, its photos, the
    catalog trimmed to the property type (+ an _id `library`), and the GFA.

    Raises ItemsFetchError / NoPhotosError when megamind or rpdata yield nothing,
    and MissingBuildYearError when the year is required (default) but absent — the
    Step 0 context fetch passes require_build_year=False so it can surface the
    missing year instead of failing.
    """
    renovation_items = fetch_renovation_items()
    if not renovation_items:
        raise ItemsFetchError("Megamind returned no usable renovation items")
    # A request can override the photo set (dev/testing: pick a small subset in the
    # playground) — used as-is. Otherwise hard-cap the raw set (newest-first) BEFORE
    # dedup so a 300+ photo listing can't blow up dedup downloads or the vision
    # output; then drop near-duplicate re-listed shots (URL/ID dedup misses these).
    photos = req.photos or dedup_photos(fetch_photos(req.rp_id)[:MAX_PHOTOS])
    if not photos:
        raise NoPhotosError(f"No usable photos found for rp_id {req.rp_id}")
    property_data = req.property or fetch_property(req.rp_id)
    _ensure_build_year(property_data, req.build_year, require_build_year)
    # Show the model only the kitchen variant that fits this property type.
    renovation_items = filter_catalog_for_property(renovation_items, property_data)
    gfa = gfa_from_property(property_data)
    return {
        "model": req.model or get_settings().default_model,
        "photos": photos,
        "property": property_data,
        "renovationItems": renovation_items,
        "library": {it["_id"]: it for it in renovation_items},
        "gfa": gfa,
    }
