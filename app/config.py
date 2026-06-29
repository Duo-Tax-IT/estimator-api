from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service configuration, loaded from environment / .env(.local)."""

    # Read .env first, then .env.local (local overrides; both are git-ignored).
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # The vision model runs on Gemini via Google's OpenAI-compatible endpoint, so
    # the OpenAI SDK is reused with this key + base URL. OPENAI_API_KEY is kept
    # optional for backwards compatibility but no longer used.
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"

    # Path to the text file holding the estimator prompt template.
    # Relative paths resolve from the estimator-api/ service root.
    estimator_prompt_file: str = "estimator_prompt.txt"

    # Shared secret required in the `secret-sauce` header — used by machine
    # callers. The auth gate accepts it as a bypass; browsers use SSO instead.
    api_key: str | None = None

    # Microsoft Entra ID (Azure AD) SSO. When all four are set, the whole app is
    # gated behind interactive login (machine callers still pass via `api_key`).
    # Unset → SSO is off; with `api_key` also unset the gate is a no-op (local dev).
    azure_tenant_id: str | None = None
    azure_client_id: str | None = None
    azure_client_secret: str | None = None
    session_secret: str | None = None  # signs the login session cookie

    # Default Gemini model when the request does not specify one.
    # Set the exact API id here (vision-capable Gemini Flash).
    default_model: str = "gemini-3.5-flash"

    # v3 only: the cheap text model that runs the text-only reasoning steps
    # (support, match) over the master JSON — no vision needed there. Empty =
    # reuse the (expensive) vision `default_model`. Set a cheaper text id to save.
    default_text_model: str = ""

    # Base rpdata (calc.duo.tax) endpoint for a property, keyed by rp_id. The
    # client appends `/photos` for the photos payload and uses the base URL for
    # property attributes. Callers pass `rpId`, never raw photos/attributes.
    # Must contain the `{rp_id}` placeholder.
    rpdata_api_url: str = "https://calc.duo.tax/property/{rp_id}"

    # Optional Authorization header value sent to the rpdata API.
    # calc.duo.tax currently needs none; leave unset.
    rpdata_api_auth: str | None = None

    # calc.duo.tax address-autocomplete endpoint. Called with `?q=<address>`;
    # returns {"suggestions": [{suggestionId (= rp_id), suggestion, ...}]}.
    rpdata_search_url: str = "https://calc.duo.tax/search"

    # Base URL of the megamind API. The estimator-items endpoint path is
    # appended in megamind_client; the catalog is fetched fresh on every estimate.
    megamind_api_url: str = "https://api.megamind.duo.tax"
    # Sent to megamind as the `X-API-KEY` header. Required for the call to
    # succeed; put the real value in .env.local.
    megamind_api_key: str | None = None

    # Base URL of the Salesforce proxy API. The client appends
    # /api/salesforce/query and sends SALESFORCE_API_KEY as the X-API-KEY header.
    salesforce_api_url: str = "http://localhost:5172"
    salesforce_api_key: str | None = None

    # Postgres for the pipeline run harness (app/opportunities). Stores opportunity
    # snapshots + every pipeline estimate; supports parallel workers. e.g.
    # postgresql://user:pass@host:5432/training . Unset → the harness can't run.
    training_db_url: str | None = None

    # Salesforce org base URL (My Domain), used to build clickable Opportunity
    # record links in the /training viewer. e.g. https://acme.lightning.force.com
    salesforce_org_url: str = "https://duotax.lightning.force.com"

    # In-process Places365 room classifier that hints the v2 observe step. Flip
    # off to skip it; it also self-disables (no-op) when torch or the weights are
    # absent, so a deploy without them still runs estimates normally.
    room_classifier_enabled: bool = True
    places365_weights_path: str = "app/models/places365/resnet18_places365.pth.tar"


@lru_cache
def get_settings() -> Settings:
    return Settings()
