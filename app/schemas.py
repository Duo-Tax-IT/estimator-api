from typing import Any

from pydantic import BaseModel, Field


class Photo(BaseModel):
    """A single property photo passed to the vision model."""

    url: str
    date: str | None = None


class EstimateRequest(BaseModel):
    """Inputs for renovation detection.

    `renovationItems` is the authoritative dataset the vision model matches
    photos against (it may not invent items or alter rates). `config` and
    `property` are optional and forwarded to the model verbatim as context.
    """

    # Either pass photos directly, or pass rp_id to have the service fetch them.
    rp_id: str | None = Field(default=None, alias="rpId")
    photos: list[Photo] = []
    renovation_items: list[dict[str, Any]] = Field(
        default_factory=list, alias="renovationItems"
    )
    config: dict[str, Any] | None = None
    property: dict[str, Any] | None = None
    model: str | None = None

    model_config = {"populate_by_name": True}
