"""v3 single pass — one vision call returns the master JSON (observe + era +
structure) that the v2 pipeline produced in three separate vision calls."""
from ..clients.openai_client import analyze_photos
from ..prompts import get_base_prompt
from ..schemas import EstimateRequest
from ..estimator_v2.steps.parsing import _parse

ANALYZE_PROMPT_FILE = "analyze_prompt.txt"


def run_analyze(model: str, prepared: list, req: EstimateRequest) -> tuple:
    """One vision pass over all prepared photos → the master JSON
    {photoObservations, eraAnalysis, structureAnalysis}. Returns
    (analysis, usage, roomHints, sentPhotos)."""
    raw, usage, room_hints, sent_photos = analyze_photos(
        model, get_base_prompt(ANALYZE_PROMPT_FILE), prepared,
        reasoning_effort=req.reasoning_effort, temperature=req.temperature,
    )
    return _parse(raw, "photo analysis"), usage, room_hints, sent_photos
