import openai

from ..errors import ModelError
from ..estimator import _format_renovations, _money
from ..schemas import EstimateRequest, StepRequest
from .steps import run_era, run_match, run_observe, run_support
from .context import fetch_v2_context
from .price import apply_year_guard, price_validated

# ── Playground: run a single step in isolation on (optionally hand-edited) input ──
# Each returns plain JSON so the /playground UI can show the output and feed it
# into the next step. `req.observations` / `req.era` / `req.validatedCandidates`
# let a step run on data the user tweaked rather than the previous step's output.


def _guard(fn, *args):
    """Map a model call's openai error to ModelError, as build_estimate_v2 does."""
    try:
        return fn(*args)
    except openai.OpenAIError as exc:
        raise ModelError(f"Vision model call failed: {exc}") from exc


def step_context(req: EstimateRequest) -> dict:
    """Step 0 — the upstream fetch: what the pipeline starts from. Build year is
    NOT required here, so a missing year surfaces in the output instead of erroring
    (the gate kicks in from the observe step on)."""
    ctx = fetch_v2_context(req, require_build_year=False)
    return {
        "model": ctx["model"],
        "property": ctx["property"],
        "gfa": ctx["gfa"],
        "photoCount": len(ctx["photos"]),
        "catalogCount": len(ctx["renovationItems"]),
        "photos": [p.model_dump() for p in ctx["photos"]],
    }


def step_observe(req: EstimateRequest) -> dict:
    ctx = fetch_v2_context(req)
    observations, usage, room_hints, sent_photos = _guard(
        run_observe, ctx["model"], ctx["photos"], req
    )
    return {"observations": observations, "roomHints": room_hints,
            "photos": sent_photos, "usage": usage}


def step_era(req: EstimateRequest) -> dict:
    ctx = fetch_v2_context(req)
    era, usage = _guard(run_era, ctx["model"], ctx["photos"], req)
    return {"era": era, "usage": usage}


def step_support(req: StepRequest) -> dict:
    ctx = fetch_v2_context(req)
    observations = req.observations or {"photoObservations": []}
    era = req.era or {"eraAnalysis": []}
    support, usage = _guard(run_support, ctx, observations, era, req)
    return {"renovationSupport": support, "usage": usage}


def step_match(req: StepRequest) -> dict:
    ctx = fetch_v2_context(req)
    support = req.support or {"renovationSupportFindings": []}
    candidates, usage = _guard(run_match, ctx, support, req)
    return {"candidates": candidates, "usage": usage}


def step_price(req: StepRequest) -> dict:
    ctx = fetch_v2_context(req)
    candidates = {"validatedCandidates": req.validated_candidates or [],
                  "rejectedCandidates": []}
    validated = apply_year_guard(
        candidates["validatedCandidates"], candidates, ctx["property"]
    )
    core = price_validated(req, ctx, validated, req.observations or {})
    result = {
        "Renovations": _format_renovations(core["renovations"]),
        "Renovations Total": _money(core["total"]),
        # What the deterministic year-guard dropped as original build.
        "yearGuardRejected": candidates["rejectedCandidates"],
        "bci": {"state": core["state"], "factors": core["factors"]},
        "roomScaling": {
            "manual": (req.config or {}).get("roomScale") or {},
            "auto": bool((req.config or {}).get("assumeAllRoomsRenovated")),
            "applied": core["roomCounts"],
            "reasons": core["roomScaleReasons"],
        },
    }
    if req.settlement_date:
        result["Previous Owner Total"] = _money(core["ownerTotals"]["Previous Owner"])
        result["Current Owner Total"] = _money(core["ownerTotals"]["Current Owner"])
    return result
