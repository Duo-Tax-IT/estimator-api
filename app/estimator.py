import json

from .config import get_settings
from .openai_client import generate_estimate
from .photos_client import fetch_photos
from .prompts import get_base_prompt
from .schemas import EstimateRequest


def _build_model_input(req: EstimateRequest) -> dict:
    """The JSON payload the prompt expects.

    Photos are sent separately as vision images (see openai_client), so they
    are not duplicated here. `property` is optional context.
    """
    return {
        "property": req.property or {},
        "renovationItems": req.renovation_items,
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
    """Detect renovations from photos against the supplied dataset.

    The model matches photos to `renovationItems`, prices each line as
    FinalCost = DefaultRate x Quantity, and returns Totals.TotalRenovation plus
    a summary and disclaimer. We only format currency and reshape the output.
    """
    prompt = get_base_prompt(get_settings().estimator_prompt_file)
    model = req.model or get_settings().default_model

    # Photos passed directly take precedence; otherwise fetch them by rp_id.
    photos = req.photos
    if not photos and req.rp_id:
        photos = fetch_photos(req.rp_id)

    raw = generate_estimate(model, prompt, _build_model_input(req), photos)
    estimate = json.loads(raw)

    reno_total = float(estimate.get("Totals", {}).get("TotalRenovation", 0))

    return {
        "Renovations": _format_renovations(estimate.get("Renovations", [])),
        "Renovations Total": _money(reno_total),
        "Summary Description": estimate.get("Summary Description", ""),
        # The model's "Guarantee" field is a fixed disclaimer sentence.
        "Disclaimer": estimate.get("Guarantee", ""),
    }
