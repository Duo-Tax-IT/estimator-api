"""v3 pipeline — one master-JSON vision pass + cheap-text reasoning.

The three v2 vision steps (observe, era, structure) collapse into a single
`run_analyze` call; the text steps (support, match) are reused verbatim from v2
but run on a cheap text model. Context fetch, year-guard and pricing are reused
unchanged, so v3 returns the SAME response shape + Stages keys as v2.
"""
import openai

from ..config import get_settings
from ..errors import ModelError
from ..estimator import _format_renovations, _money
from ..clients.openai_client import merge_usage, prepare_photos
from ..prompts import get_base_prompt
from ..schemas import EstimateRequest, StepRequest
from ..estimator_v2 import DISCLAIMER, DISCLAIMER_WITH_REPAINT, _hash, _needs_review_row
from ..estimator_v2.context import fetch_v2_context
from ..estimator_v2.price import GUT_DISCLAIMER, apply_year_guard, price_validated
from ..estimator_v2.steps import (
    CANDIDATES_PROMPT_FILE, SUPPORT_PROMPT_FILE, run_match, run_support,
)
from ..estimator_v2.playground import step_context, step_price
from .analyze import ANALYZE_PROMPT_FILE, run_analyze


def _text_ctx(ctx: dict, req: EstimateRequest) -> dict:
    """ctx with `model` swapped to the cheap text model, for the text-only
    support/match passes. v2's run_support/run_match read ctx['model'], so they
    are reused untouched — they just see the cheaper model."""
    text_model = req.text_model or get_settings().default_text_model or ctx["model"]
    return {**ctx, "model": text_model}


def build_estimate_v3(req: EstimateRequest) -> dict:
    """Detect renovations via the v3 single-pass pipeline.

    One vision call (run_analyze) produces the master JSON; support + match then
    run on the cheap text model. Same response shape as build_estimate_v2, plus a
    `Stages` key with the identical keys. Same error taxonomy.
    """
    ctx = fetch_v2_context(req)
    text_ctx = _text_ctx(ctx, req)
    try:
        prepared = prepare_photos(ctx["photos"])
        # The single deep pass: pixels are read exactly once here.
        analysis, analysis_usage, room_hints, sent_photos = run_analyze(
            ctx["model"], prepared, req
        )
        observations = {"photoObservations": analysis.get("photoObservations", [])}
        era = {"eraAnalysis": analysis.get("eraAnalysis", [])}
        structural = analysis.get("structureAnalysis") or {}
        gut = analysis.get("gutRenovation") or {}
        # Text-only reasoning over the master JSON, on the cheap text model.
        support, support_usage = run_support(text_ctx, observations, era, req)
        candidates, cand_usage = run_match(text_ctx, support, req)
    except openai.OpenAIError as exc:
        raise ModelError(f"Vision model call failed: {exc}") from exc

    validated = apply_year_guard(
        candidates.get("validatedCandidates", []), candidates, ctx["property"]
    )
    core = price_validated(req, ctx, validated, observations, structural, gut)
    # Not-in-catalog renovations surface as unpriced needs-review rows. On a gut
    # reno the recorded build year is unreliable, so the year-guard's rejects join
    # them — flagged for manual judgement, never auto-priced.
    needs_review = list(candidates.get("unmatchedFindings", []))
    if gut.get("detected"):
        needs_review += candidates.get("yearGuardRejected", [])
    renovations = _format_renovations(core["renovations"]) + [
        _needs_review_row(f) for f in needs_review
    ]

    result = {
        "Renovations": renovations,
        "Renovations Total": _money(core["total"]),
        "Property": ctx["property"],
        "GFA": ctx["gfa"],
        "Summary Description": candidates.get("summary", ""),
        "Disclaimer": (
            (DISCLAIMER_WITH_REPAINT if core["paintDecision"]["applied"] else DISCLAIMER)
            + (" " + GUT_DISCLAIMER if core["gutDecision"]["applied"] else "")
        ),
        # One vision call + two cheap text calls (vs v2's four+ vision calls).
        "Usage": merge_usage(analysis_usage, support_usage, cand_usage),
        "Stages": {
            "observations": observations,
            "eraAnalysis": era,
            "renovationSupport": support,
            "roomHints": room_hints,
            # The model's own dwelling-type read from the photos — an audit
            # signal against rpdata's propertyType, which can be wrong.
            "propertyType": analysis.get("propertyType") or {},
            "paintAssumption": core["paintDecision"],
            "structuralChange": structural,
            "gutRenovation": gut,
            "gutEstimate": core["gutDecision"],
            "extensionAssumption": core["extensionDecision"],
            "candidates": {
                "validatedCandidates": validated,
                "rejectedCandidates": candidates.get("rejectedCandidates", []),
                "unmatchedFindings": candidates.get("unmatchedFindings", []),
            },
            "toolInput": [
                {"_id": e["_id"], "name": e["name"], "area": e["area"], "factor": e["factor"]}
                for e in core["detected"]
            ],
            "bci": {"state": core["state"], "factors": core["factors"]},
            "photos": sent_photos,
        },
        "Meta": {
            "pipeline": "v3",
            "analyzePromptHash": _hash(get_base_prompt(ANALYZE_PROMPT_FILE)),
            "supportPromptHash": _hash(get_base_prompt(SUPPORT_PROMPT_FILE)),
            "candidatesPromptHash": _hash(get_base_prompt(CANDIDATES_PROMPT_FILE)),
            "textModel": text_ctx["model"],
        },
    }
    if req.settlement_date:
        result["Previous Owner Total"] = _money(core["ownerTotals"]["Previous Owner"])
        result["Current Owner Total"] = _money(core["ownerTotals"]["Current Owner"])
    return result


# ── Playground: run a single v3 step in isolation (mirrors v2's playground) ──
# step_context and step_price are reused from v2 verbatim. analyze is the new
# single vision pass; support/match run on the cheap text model.


def _guard(fn, *args):
    """Map a model call's openai error to ModelError, as build_estimate_v3 does."""
    try:
        return fn(*args)
    except openai.OpenAIError as exc:
        raise ModelError(f"Vision model call failed: {exc}") from exc


def step_analyze(req: EstimateRequest) -> dict:
    ctx = fetch_v2_context(req)
    prepared = prepare_photos(ctx["photos"])
    analysis, usage, room_hints, sent_photos = _guard(
        run_analyze, ctx["model"], prepared, req
    )
    return {"analysis": analysis, "roomHints": room_hints,
            "photos": sent_photos, "usage": usage}


def step_support(req: StepRequest) -> dict:
    ctx = _text_ctx(fetch_v2_context(req), req)
    observations = req.observations or {"photoObservations": []}
    era = req.era or {"eraAnalysis": []}
    support, usage = _guard(run_support, ctx, observations, era, req)
    return {"renovationSupport": support, "usage": usage}


def step_match(req: StepRequest) -> dict:
    ctx = _text_ctx(fetch_v2_context(req), req)
    support = req.support or {"renovationSupportFindings": []}
    candidates, usage = _guard(run_match, ctx, support, req)
    return {"candidates": candidates, "usage": usage}
