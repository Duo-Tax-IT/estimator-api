from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service configuration, loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    openai_api_key: str

    # Path to the text file holding the estimator prompt template.
    # Relative paths resolve from the estimator-api/ service root.
    estimator_prompt_file: str = "estimator_prompt.txt"

    # Shared secret required in the `secret-sauce` header. Optional: if unset,
    # the auth dependency is a no-op (handy for local dev).
    api_key: str | None = None

    # Default OpenAI model when the request does not specify one.
    default_model: str = "gpt-4.1"

    # Endpoint that returns a property's photos given an rp_id. Must contain
    # the `{rp_id}` placeholder, e.g. "https://api.example.com/property/{rp_id}/photos".
    photos_api_url: str | None = None

    # Optional value sent as the Authorization header to the photos API.
    photos_api_auth: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
