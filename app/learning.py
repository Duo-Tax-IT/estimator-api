"""Learning loop: compare a saved run's logs against an expert's ground truth and
have the model recommend what to tune. Read-only against the estimate pipeline."""

import json

from .clients.openai_client import analyze_learning
from .config import get_settings
from .errors import ModelError
from .prompts import get_base_prompt

LEARNING_PROMPT_FILE = "learning_prompt.txt"


def build_learning_analysis(run: dict, expert_input: str, model: str | None = None) -> dict:
    """Compare a saved run against expert ground truth → a tuning-analysis dict.

    `run` is a runs_db row; its `response` holds the final Renovations plus the
    full per-stage `Stages` logs the model attributes discrepancies to. Returns the
    parsed analysis; raises ModelError on unparseable model output.
    """
    response = run.get("response") or {}
    payload = {
        "expertGroundTruth": expert_input,
        "systemRun": {
            "Renovations": response.get("Renovations", []),
            "RenovationsTotal": response.get("Renovations Total"),
            # The match step's own summary of what it detected (Step 2's `summary`).
            "SummaryDescription": response.get("Summary Description"),
            "Property": response.get("Property"),
            "GFA": response.get("GFA"),
            "Stages": response.get("Stages", {}),
            "Meta": response.get("Meta", {}),
        },
    }
    raw, _ = analyze_learning(
        model or get_settings().default_model,
        get_base_prompt(LEARNING_PROMPT_FILE),
        payload,
    )
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ModelError(f"Learning model returned invalid JSON: {(raw or '')[:300]!r}") from exc
