"""Step 2 — ground the renovation-supported findings to the catalog."""
from ...clients.openai_client import match_candidates
from ...estimator import _build_model_input
from ...prompts import get_base_prompt
from ...schemas import EstimateRequest
from .parsing import _parse

CANDIDATES_PROMPT_FILE = "candidates_prompt.txt"


def run_match(ctx: dict, support: dict, req: EstimateRequest) -> tuple:
    """Step 2 — ground the renovation-supported findings to the catalog. The
    renovation decision and year are already made in Step 1.5; only findings
    flagged `shouldProceedToCatalogMatch` are matched. Returns (candidates,
    usage)."""
    findings = [
        f for f in support.get("renovationSupportFindings", [])
        if f.get("shouldProceedToCatalogMatch")
    ]
    payload = _build_model_input(
        ctx["property"], ctx["renovationItems"], req.config or {}, ctx["gfa"]
    )
    payload["renovationSupportFindings"] = findings
    raw, usage = match_candidates(
        ctx["model"], get_base_prompt(CANDIDATES_PROMPT_FILE), payload,
        reasoning_effort=req.reasoning_effort, temperature=req.temperature,
    )
    return _parse(raw, "candidate matching"), usage
