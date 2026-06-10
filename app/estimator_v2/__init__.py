import hashlib
from concurrent.futures import ThreadPoolExecutor

import openai

from ..errors import ModelError
from ..estimator import _format_renovations, _money
from ..clients.openai_client import merge_usage
from ..prompts import get_base_prompt
from ..schemas import EstimateRequest
from .context import fetch_v2_context
from .price import (
    DISCLAIMER_WITH_REPAINT, _internal_paint_row, apply_year_guard, price_validated,
)
from .preview import preview_estimate_prompt_v2
from .steps import (
    CANDIDATES_PROMPT_FILE,
    ERA_PROMPT_FILE,
    OBSERVE_PROMPT_FILE,
    SUPPORT_PROMPT_FILE,
    run_era,
    run_match,
    run_observe,
    run_support,
)
from .playground import (
    step_context, step_era, step_match, step_observe, step_price, step_support,
)

# The fixed Guarantee sentence from estimator_prompt.txt. v2 builds the final
# response in Python (no formatter model call), so the disclaimer is a constant.
DISCLAIMER = (
    "This assessment is based solely on visual analysis of provided images and "
    "uses a predefined renovation item dataset. No external cost estimation "
    "methods were used."
)


def _hash(text: str) -> str:
    """Short stable version id for a prompt, so saved runs can be bucketed by
    prompt version when comparing system output against expert output."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def build_estimate_v2(req: EstimateRequest) -> dict:
    """Detect renovations via the multi-step v2 pipeline.

    Composes the step functions: fetch context → observe ∥ era (parallel vision
    passes) → match → year-guard → price. Returns the same response shape as
    build_full_estimate, plus a `Stages` key holding each step's output for
    debugging. Same error taxonomy: NoPhotosError, ItemsFetchError, ModelError.
    """
    ctx = fetch_v2_context(req)
    try:
        # Steps 1 & 1b are independent vision passes over the same photos, so they
        # run in parallel — the slower one sets the wall-clock, not obs + era.
        with ThreadPoolExecutor(max_workers=2) as pool:
            obs_f = pool.submit(run_observe, ctx["model"], ctx["photos"], req)
            era_f = pool.submit(run_era, ctx["model"], ctx["photos"], req)
            observations, obs_usage, room_hints, sent_photos = obs_f.result()
            era, era_usage = era_f.result()
        # Step 1.5 — validate which observations are renovation-supported (uses
        # both observe + era), then Step 2 grounds only the supported ones.
        support, support_usage = run_support(ctx, observations, era, req)
        candidates, cand_usage = run_match(ctx, support, req)
    except openai.OpenAIError as exc:
        raise ModelError(f"Vision model call failed: {exc}") from exc

    validated = apply_year_guard(
        candidates.get("validatedCandidates", []), candidates, ctx["property"]
    )
    core = price_validated(req, ctx, validated, observations)

    result = {
        "Renovations": _format_renovations(core["renovations"]),
        "Renovations Total": _money(core["total"]),
        "Property": ctx["property"],
        "GFA": ctx["gfa"],
        "Summary Description": candidates.get("summary", ""),
        "Disclaimer": DISCLAIMER_WITH_REPAINT if core["paintDecision"]["applied"] else DISCLAIMER,
        # Combined token counts + USD cost across the four model calls.
        "Usage": merge_usage(obs_usage, era_usage, support_usage, cand_usage),
        "Stages": {
            "observations": observations,
            # Forensic per-element era dating (Step 1b) — the dated fabrication
            # cues the support step weighed against yearBuilt.
            "eraAnalysis": era,
            # Step 1.5 renovation-support findings — the gated judgment (and
            # estimatedRenovationYear) Match grounded to the catalog.
            "renovationSupport": support,
            # Room classifier predictions per photo (photoIndex matches the
            # observe model's image order) — auditable vs observations.roomType.
            "roomHints": room_hints,
            # Internal-repaint assumption audit: whether it fired and the per-room
            # areas (from gfa) that made up the assumed paint area.
            "paintAssumption": core["paintDecision"],
            "candidates": {
                "validatedCandidates": validated,
                "rejectedCandidates": candidates.get("rejectedCandidates", []),
            },
            "toolInput": [
                {"_id": e["_id"], "name": e["name"], "area": e["area"], "factor": e["factor"]}
                for e in core["detected"]
            ],
            # AIQS BCI audit: the state used and the factor applied per renovation
            # year (1.0 = no scaling / unavailable). FinalCost = rate × qty × factor.
            "bci": {"state": core["state"], "factors": core["factors"]},
            # Index→url/date for the photos actually sent (skips ones that failed
            # to fetch), so each evidence `photoIndex` resolves to a real image.
            "photos": sent_photos,
        },
        # Provenance for a self-learning loop: which pipeline + prompt versions
        # produced this run, so a signal can be attributed to a prompt version.
        "Meta": {
            "pipeline": "v2",
            "observePromptHash": _hash(get_base_prompt(OBSERVE_PROMPT_FILE)),
            "eraPromptHash": _hash(get_base_prompt(ERA_PROMPT_FILE)),
            "supportPromptHash": _hash(get_base_prompt(SUPPORT_PROMPT_FILE)),
            "candidatesPromptHash": _hash(get_base_prompt(CANDIDATES_PROMPT_FILE)),
        },
    }
    if req.settlement_date:
        result["Previous Owner Total"] = _money(core["ownerTotals"]["Previous Owner"])
        result["Current Owner Total"] = _money(core["ownerTotals"]["Current Owner"])
    return result
