"""Step 1 — observe what's visible in the photos."""
from ...clients.openai_client import observe_photos
from ...prompts import get_base_prompt
from ...schemas import EstimateRequest
from .parsing import _parse

OBSERVE_PROMPT_FILE = "observe_prompt.txt"


def run_observe(model: str, prepared: list, req: EstimateRequest) -> tuple:
    """Step 1 — observe what's visible (over photos already prepared once by
    prepare_photos). Returns (observations, usage, roomHints, sentPhotos);
    roomHints/sentPhotos are classifier audit data for Stages."""
    raw, usage, room_hints, sent_photos = observe_photos(
        model, get_base_prompt(OBSERVE_PROMPT_FILE), prepared,
        reasoning_effort=req.reasoning_effort, temperature=req.temperature,
    )
    return _parse(raw, "observation"), usage, room_hints, sent_photos
