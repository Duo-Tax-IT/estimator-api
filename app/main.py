from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .errors import ItemsFetchError, ModelError, NoPhotosError, RpDataFetchError
from .estimator import build_full_estimate
from .schemas import EstimateRequest

app = FastAPI(title="Estimator API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_secret(secret_sauce: str | None = Header(default=None)) -> None:
    """Guard endpoints with the shared `secret-sauce` header.

    No-op when API_KEY is unset (local dev).
    """
    api_key = get_settings().api_key
    if api_key and secret_sauce != api_key:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/estimate")
def estimate(req: EstimateRequest, _: None = Depends(require_secret)):
    try:
        return build_full_estimate(req)
    except NoPhotosError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ItemsFetchError, RpDataFetchError, ModelError) as exc:
        # Upstream failed: megamind, calc.duo.tax, or the vision model.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
