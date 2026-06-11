"""Structural step — detect a storey/footprint change (extension) from the
oldest vs newest exterior photo. Runs after observe (reuses its roomType + the
sent-photo dates); feeds a deterministic House Extension row in pricing."""
import httpx

from ...clients.openai_client import compare_structure
from ...prompts import get_base_prompt
from ...schemas import EstimateRequest
from .parsing import _parse

STRUCTURE_PROMPT_FILE = "structure_prompt.txt"


def _exterior_pair(observations: dict, sent_photos: list) -> tuple | None:
    """Oldest + newest dated exterior photo. roomType comes from observe, the
    capture date from the sent-photo map. None when there aren't two
    distinct-date exterior shots to compare."""
    by_index = {p["photoIndex"]: p for p in sent_photos}
    ext = [
        by_index[o["photoIndex"]]
        for o in observations.get("photoObservations", [])
        if o.get("roomType") == "exterior" and by_index.get(o["photoIndex"], {}).get("date")
    ]
    ext.sort(key=lambda p: p["date"])
    if len(ext) < 2 or ext[0]["date"] == ext[-1]["date"]:
        return None
    return ext[0], ext[-1]


def run_structure(model: str, observations: dict, sent_photos: list, req: EstimateRequest) -> tuple:
    """Structural step — compare the oldest vs newest exterior photo for an
    extension/second-storey. Returns (structural, usage); structural is {} when
    there's no exterior pair to compare or a photo can't be fetched."""
    pair = _exterior_pair(observations, sent_photos)
    if not pair:
        return {}, {}
    try:
        raw, usage = compare_structure(
            model, get_base_prompt(STRUCTURE_PROMPT_FILE), pair[0], pair[1],
            reasoning_effort=req.reasoning_effort, temperature=req.temperature,
        )
    except httpx.HTTPError:
        return {}, {}
    return _parse(raw, "structural delta"), usage
