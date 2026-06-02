import httpx

from .config import get_settings
from .errors import SalesforceFetchError

# Path appended to the Salesforce proxy base URL (SALESFORCE_API_URL).
_QUERY_PATH = "/api/salesforce/query"


def _post(body: dict) -> dict:
    """POST the Salesforce query endpoint with the API key and return parsed JSON.

    Raises SalesforceFetchError if the proxy is unconfigured, unreachable /
    unauthorized, or returns a non-JSON body.
    """
    settings = get_settings()
    if not settings.salesforce_api_url:
        raise SalesforceFetchError("SALESFORCE_API_URL is not configured")
    if not settings.salesforce_api_key:
        raise SalesforceFetchError("SALESFORCE_API_KEY is not set")

    url = settings.salesforce_api_url.rstrip("/") + _QUERY_PATH
    try:
        resp = httpx.post(
            url,
            headers={"X-API-KEY": settings.salesforce_api_key},
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise SalesforceFetchError(f"Salesforce query failed: {exc}") from exc

    try:
        return resp.json()
    except ValueError as exc:
        raise SalesforceFetchError("Salesforce proxy returned non-JSON") from exc


def query(soql: str, use_cache: bool = False) -> list[dict]:
    """Run a SOQL/SOSL query and return all records, following pagination.

    Records keep Salesforce's raw shape (including the `attributes` key) so the
    full result set can be handed straight to the model. Raises
    SalesforceFetchError on transport / parse failures.
    """
    payload = _post({"query": soql, "useCache": use_cache})
    records = payload.get("records", [])
    while not payload.get("done") and payload.get("nextRecordsUrl"):
        payload = _post({"nextRecordsUrl": payload["nextRecordsUrl"]})
        records.extend(payload.get("records", []))
    return records
