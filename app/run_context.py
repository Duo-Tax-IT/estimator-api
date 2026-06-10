"""Single source of truth for what the model sees about a saved run: its final
output plus the full per-stage logs. Shared by the learning loop and the chat."""


def build_run_context(response: dict) -> dict:
    """A run's final renovations + per-stage trace, as a model-facing context dict."""
    response = response or {}
    return {
        "Renovations": response.get("Renovations", []),
        "RenovationsTotal": response.get("Renovations Total"),
        # The match step's own summary of what it detected (Step 2's `summary`).
        "SummaryDescription": response.get("Summary Description"),
        "Property": response.get("Property"),
        "GFA": response.get("GFA"),
        "Stages": response.get("Stages", {}),
        "Meta": response.get("Meta", {}),
    }
