"""Step 1b — forensically date each finish."""
from ...clients.openai_client import analyze_era
from ...prompts import get_base_prompt
from ...schemas import EstimateRequest
from .parsing import _parse

ERA_PROMPT_FILE = "era_prompt.txt"


def run_era(model: str, photos: list, req: EstimateRequest) -> tuple:
    """Step 1b — forensically date each finish. Returns (eraAnalysis, usage)."""
    raw, usage = analyze_era(
        model, get_base_prompt(ERA_PROMPT_FILE), photos,
        reasoning_effort=req.reasoning_effort, temperature=req.temperature,
    )
    return _parse(raw, "era analysis"), usage
