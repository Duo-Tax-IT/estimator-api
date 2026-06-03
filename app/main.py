from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response

from .config import get_settings
from .errors import ItemsFetchError, ModelError, NoPhotosError, RpDataFetchError
from .estimator import build_full_estimate, preview_estimate_prompt
from .estimator_v2 import build_estimate_v2, preview_estimate_prompt_v2
from .prompts import get_base_prompt
from .rpdata_client import build_photos_zip, fetch_photos, search_addresses
from .runs_db import list_runs, save_run
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


@app.get("/photos/download")
def photos_download(rpId: str = Query(min_length=1)) -> Response:
    """Download all usable photos for a property as a single zip."""
    try:
        data = build_photos_zip(rpId)
    except NoPhotosError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RpDataFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{rpId}.zip"'},
    )


@app.post("/debug/prompt", response_class=PlainTextResponse)
def debug_prompt(req: EstimateRequest, _: None = Depends(require_secret)) -> str:
    """The assembled prompt (template + injected input) the model would get — debug."""
    try:
        return preview_estimate_prompt(req)
    except (ItemsFetchError, RpDataFetchError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/debug/prompt/v2", response_class=PlainTextResponse)
def debug_prompt_v2(req: EstimateRequest, _: None = Depends(require_secret)) -> str:
    """The v2 pipeline's two prompts (observe + candidate-match) — debug."""
    try:
        return preview_estimate_prompt_v2(req)
    except (ItemsFetchError, RpDataFetchError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _save_run(req: EstimateRequest, result: dict) -> None:
    """Log the run for later comparison. Best-effort: never break the estimate."""
    try:
        save_run(
            rp_id=req.rp_id,
            model=req.model or get_settings().default_model,
            reasoning_effort=req.reasoning_effort,
            temperature=req.temperature,
            label=req.label,
            address=req.address,
            prompt=get_base_prompt(get_settings().estimator_prompt_file),
            response=result,
        )
    except Exception:
        pass


def _run_estimate(builder, req: EstimateRequest) -> dict:
    """Run an estimate builder, map upstream failures to HTTP, and save the run."""
    try:
        result = builder(req)
    except NoPhotosError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ItemsFetchError, RpDataFetchError, ModelError) as exc:
        # Upstream failed: megamind, calc.duo.tax, or the vision model.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    _save_run(req, result)
    return result


@app.post("/estimate")
def estimate(req: EstimateRequest, _: None = Depends(require_secret)):
    return _run_estimate(build_full_estimate, req)


@app.post("/estimate/v2")
def estimate_v2(req: EstimateRequest, _: None = Depends(require_secret)):
    """The multi-step (observe -> match -> price) pipeline. Same response shape
    as /estimate, plus a `Stages` debug key."""
    return _run_estimate(build_estimate_v2, req)


@app.get("/runs")
def runs(rpId: str | None = Query(default=None)) -> dict:
    """Saved estimate runs (newest first). Omit rpId to list every property's runs."""
    return {"runs": list_runs(rpId)}
