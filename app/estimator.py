import json

import openai

from .config import get_settings
from .errors import ItemsFetchError, ModelError, NoPhotosError
from .megamind_client import fetch_renovation_items
from .openai_client import generate_estimate
from .photos_client import fetch_photos
from .prompts import get_base_prompt
from .schemas import EstimateRequest


def _build_model_input(req: EstimateRequest, renovation_items: list[dict]) -> dict:
    """The JSON payload the prompt expects.

    Photos are sent separately as vision images (see openai_client), so they
    are not duplicated here. `renovation_items` is the megamind catalog;
    `property` and `config` are optional context.
    """
    return {
        "property": req.property or {},
        "renovationItems": renovation_items,
        "config": req.config or {},
    }


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _format_renovations(renovations: list[dict]) -> list[dict]:
    """Format each line item's currency fields, leave the rest as-is."""
    formatted = []
    for reno in renovations:
        item = dict(reno)
        if "DefaultRate" in item:
            item["DefaultRate"] = _money(float(item["DefaultRate"]))
        if "FinalCost" in item:
            item["FinalCost"] = _money(float(item["FinalCost"]))
        formatted.append(item)
    return formatted


def build_full_estimate(req: EstimateRequest) -> dict:
    """Detect renovations from a property's photos against the megamind catalog.

    Fetches the renovation-items catalog from megamind and the property's photos
    from calc.duo.tax (by rp_id), has the vision model match them
    (FinalCost = DefaultRate x Quantity), then reshapes/currency-formats the
    output. Raises ItemsFetchError / NoPhotosError when an upstream yields
    nothing usable, and ModelError when the model call or its output fails.
    """
    prompt = get_base_prompt(get_settings().estimator_prompt_file)
    model = req.model or get_settings().default_model

    renovation_items = fetch_renovation_items()
    if not renovation_items:
        raise ItemsFetchError("Megamind returned no usable renovation items")

    photos = fetch_photos(req.rp_id)
    if not photos:
        raise NoPhotosError(f"No usable photos found for rp_id {req.rp_id}")

    try:
        raw = generate_estimate(
            model, prompt, _build_model_input(req, renovation_items), photos
        )
    except openai.OpenAIError as exc:
        raise ModelError(f"Vision model call failed: {exc}") from exc

    try:
        estimate = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ModelError("Vision model returned invalid JSON") from exc

    reno_total = float(estimate.get("Totals", {}).get("TotalRenovation", 0))

    return {
        "Renovations": _format_renovations(estimate.get("Renovations", [])),
        "Renovations Total": _money(reno_total),
        "Summary Description": estimate.get("Summary Description", ""),
        # The model's "Guarantee" field is a fixed disclaimer sentence.
        "Disclaimer": estimate.get("Guarantee", ""),
    }
