"""Step 1.5 — judge which observed items are renovation-supported."""
from ...clients.openai_client import assess_support
from ...prompts import get_base_prompt
from ...schemas import EstimateRequest
from .parsing import _parse

SUPPORT_PROMPT_FILE = "support_prompt.txt"


def run_support(ctx: dict, observations: dict, era: dict, req: EstimateRequest) -> tuple:
    """Step 1.5 — judge which observed items are renovation-supported, against the
    build-year baseline + era evidence (no catalog match yet). Returns
    (support, usage)."""
    payload = {
        "property": ctx["property"],
        "photoObservations": observations.get("photoObservations", []),
        "eraAnalysis": era.get("eraAnalysis", []),
    }
    raw, usage = assess_support(
        ctx["model"], get_base_prompt(SUPPORT_PROMPT_FILE), payload,
        reasoning_effort=req.reasoning_effort, temperature=req.temperature,
    )
    return _parse(raw, "renovation support"), usage
