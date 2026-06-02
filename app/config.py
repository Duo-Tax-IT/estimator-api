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

    # Shared secret required in the `secret-sauce` header. Optional: if unset,
    # the auth dependency is a no-op (handy for local dev).
    api_key: str | None = None

    # Default Gemini model when the request does not specify one.
    # Set the exact API id here (vision-capable Gemini Flash).
    default_model: str = "gemini-3.5-flash"

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
