from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .config import get_settings
from .errors import ItemsFetchError, ModelError, NoPhotosError, RpDataFetchError
from .estimator import build_full_estimate
from .rpdata_client import fetch_photos, search_addresses
from .schemas import EstimateRequest

app = FastAPI(title="Estimator API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_STATIC_DIR = Path(__file__).parent / "static"


def require_secret(secret_sauce: str | None = Header(default=None)) -> None:
    """Guard endpoints with the shared `secret-sauce` header.

    No-op when API_KEY is unset (local dev).
    """
    api_key = get_settings().api_key
    if api_key and secret_sauce != api_key:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/")
def index() -> FileResponse:
    """Serve the single-page address-search frontend."""
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/search")
def search(q: str = Query(min_length=1)) -> dict:
    """Proxy calc.duo.tax address autocomplete (keeps the frontend same-origin).

    Returns {"suggestions": [...]}; each suggestion's `suggestionId` is the
    rp_id to pass to /estimate.
    """
    try:
        return {"suggestions": search_addresses(q)}
    except RpDataFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/photos")
def photos(rpId: str = Query(min_length=1)) -> dict:
    """The property's usable photos (filtered/sorted) for the result carousel."""
    try:
        return {"photos": [p.model_dump() for p in fetch_photos(rpId)]}
    except RpDataFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/estimate")
def estimate(req: EstimateRequest, _: None = Depends(require_secret)):
    try:
        return build_full_estimate(req)
    except NoPhotosError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ItemsFetchError, RpDataFetchError, ModelError) as exc:
        # Upstream failed: megamind, calc.duo.tax, or the vision model.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
