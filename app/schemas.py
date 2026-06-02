from typing import Any, Literal

from pydantic import BaseModel, Field


class Photo(BaseModel):
    """A single property photo passed to the vision model (internal shape)."""

    url: str
    date: str | None = None


class EstimateRequest(BaseModel):
    """Inputs for renovation detection.

    The caller passes `rpId`; the service fetches the property's photos from
    rpdata (calc.duo.tax) and the authoritative renovation-items catalog from
    megamind. `property` is an optional override: when omitted, the service
    fetches the property's attributes from rpdata. `config` is optional context
    forwarded to the model verbatim.

    `model` and the model settings are optional per-request overrides: `model`
    swaps the OpenAI model, `reasoning_effort` tunes reasoning-class models
    (gpt-5.x / o-series), and `temperature` tunes classic chat models. Each
    falls back to the service default when omitted.
    """

    rp_id: str = Field(alias="rpId", min_length=1)
    config: dict[str, Any] | None = None
    property: dict[str, Any] | None = None
    model: str | None = None
    reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = Field(
        default=None, alias="reasoningEffort"
    )
    temperature: float | None = Field(default=None, ge=0, le=2)
    # Free-text tag saved with the run, to mark what you're testing (e.g. "v3").
    label: str | None = None
    # Display address for the picked property, saved so a run can be re-opened.
    address: str | None = None
    # Settlement date (YYYY-MM-DD), e.g. from Salesforce Opportunity
    # Settlement_Date__c. Renovations dated before it are the previous owner's.
    settlement_date: str | None = Field(default=None, alias="settlementDate")

    model_config = {"populate_by_name": True}
