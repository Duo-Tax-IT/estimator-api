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

    openai_api_key: str

    # Path to the text file holding the estimator prompt template.
    # Relative paths resolve from the estimator-api/ service root.
    estimator_prompt_file: str = "estimator_prompt.txt"

    # Shared secret required in the `secret-sauce` header. Optional: if unset,
    # the auth dependency is a no-op (handy for local dev).
    api_key: str | None = None

    # Default OpenAI model when the request does not specify one.
    # gpt-5.4-mini is a vision-capable reasoning model.
    default_model: str = "gpt-5.4-mini"

    # calc.duo.tax endpoint that returns a property's photos for an rp_id. This
    # is the SOLE source of photos: callers pass `rpId`, never raw photos. Must
    # contain the `{rp_id}` placeholder.
    photos_api_url: str = "https://calc.duo.tax/property/{rp_id}/photos"

    # Optional Authorization header value sent to the photos API.
    # calc.duo.tax currently needs none; leave unset.
    photos_api_auth: str | None = None

    # Base URL of the megamind API. The estimator-items endpoint path is
    # appended in megamind_client; the catalog is fetched fresh on every estimate.
    megamind_api_url: str = "https://api.megamind.duo.tax"
    # Sent to megamind as the `X-API-KEY` header. Required for the call to
    # succeed; put the real value in .env.local.
    megamind_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
