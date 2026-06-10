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
    # Build-year fallback: filled into the property's `yearBuilt` when rpdata has
    # none. Required (no property year + no buildYear → MissingBuildYearError),
    # because the year-guard and paint age gate depend on it.
    build_year: int | None = Field(default=None, alias="buildYear")
    # Dev/testing override: when set, these exact photos are sent to the model
    # instead of fetching + dedup + cap (lets the playground pick a small subset
    # so a run isn't 100 photos). Omitted → normal fetch.
    photos: list[Photo] | None = None

    model_config = {"populate_by_name": True}


class LearnRequest(BaseModel):
    """A learning-loop request: compare run `runId` against the expert's text."""

    run_id: int = Field(alias="runId")
    expert_input: str = Field(alias="expertInput", min_length=1)
    model: str | None = None

    model_config = {"populate_by_name": True}


class ChatRequest(BaseModel):
    """A diagnostic-chat message about run `runId` (explain-only). `includePhotos`
    re-sends the run's photos so the model can re-inspect them."""

    run_id: int = Field(alias="runId")
    message: str = Field(min_length=1)
    include_photos: bool = Field(default=False, alias="includePhotos")
    model: str | None = None

    model_config = {"populate_by_name": True}


class StepRequest(EstimateRequest):
    """EstimateRequest plus the editable intermediate outputs the /playground
    feeds between steps, so each pipeline step can run on hand-tweaked input.

    `observations` and `era` are the full step-1/1b objects ({"photoObservations":
    [...]} / {"eraAnalysis": [...]}); `validatedCandidates` is the post-match list
    the price step prices.
    """

    observations: dict[str, Any] | None = None
    era: dict[str, Any] | None = None
    support: dict[str, Any] | None = Field(default=None, alias="renovationSupport")
    validated_candidates: list[dict[str, Any]] | None = Field(
        default=None, alias="validatedCandidates"
    )
