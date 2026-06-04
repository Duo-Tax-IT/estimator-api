from ..estimator import _build_model_input, filter_catalog_for_property
from ..helpers.gfa import gfa_from_property
from ..clients.megamind_client import fetch_renovation_items
from ..clients.openai_client import MAX_PHOTOS, build_input_text
from ..prompts import get_base_prompt
from ..clients.rpdata_client import fetch_property
from ..schemas import EstimateRequest
from .steps import (
    CANDIDATES_PROMPT_FILE,
    ERA_PROMPT_FILE,
    OBSERVE_PROMPT_FILE,
    SUPPORT_PROMPT_FILE,
)


def preview_estimate_prompt_v2(req: EstimateRequest) -> str:
    """The two prompts the v2 pipeline sends, assembled for debugging.

    Mirrors build_estimate_v2's upstream fetches (catalog filtered by property
    type, gfa) minus the photos and model calls. Step 2's `photoObservations`
    are produced at runtime by Step 1, so they're shown as a placeholder.
    """
    property_data = req.property or fetch_property(req.rp_id)
    renovation_items = filter_catalog_for_property(
        fetch_renovation_items(), property_data
    )
    gfa = gfa_from_property(property_data)
    payload = _build_model_input(property_data, renovation_items, req.config or {}, gfa)
    payload["renovationSupportFindings"] = "<filled at runtime from Step 1.5 support assessment>"
    return (
        "=== STEP 1 — OBSERVATION ===\n"
        f"(prompt below + up to {MAX_PHOTOS} property photos sent as images)\n\n"
        + get_base_prompt(OBSERVE_PROMPT_FILE)
        + "\n\n\n=== STEP 1b — ERA ANALYSIS ===\n"
        "(prompt below + the same property photos sent as images)\n\n"
        + get_base_prompt(ERA_PROMPT_FILE)
        + "\n\n\n=== STEP 1.5 — RENOVATION SUPPORT ===\n"
        "(prompt below + property/observations/eraAnalysis from Steps 1/1b)\n\n"
        + get_base_prompt(SUPPORT_PROMPT_FILE)
        + "\n\n\n=== STEP 2 — CANDIDATE MATCHING ===\n"
        "(prompt below + the input data; renovationSupportFindings come from Step 1.5)\n\n"
        + get_base_prompt(CANDIDATES_PROMPT_FILE)
        + "\n\n"
        + build_input_text(payload)
    )
