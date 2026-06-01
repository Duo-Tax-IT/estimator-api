from typing import Any

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
    """

    rp_id: str = Field(alias="rpId", min_length=1)
    config: dict[str, Any] | None = None
    property: dict[str, Any] | None = None
    model: str | None = None

    model_config = {"populate_by_name": True}
