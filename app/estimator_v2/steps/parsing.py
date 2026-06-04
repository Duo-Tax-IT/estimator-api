"""Shared model-output parsing for the chain steps."""
import json

from ...errors import ModelError


def _parse(raw: str, stage: str) -> dict:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        # Surface what the model actually returned so the failure is diagnosable
        # (the head usually shows a leading prose line or an empty/garbled reply).
        text = raw or ""
        snippet = text[:300] + (" …" if len(text) > 300 else "")
        print(f"[v2] {stage} returned unparseable output ({len(text)} chars): {snippet!r}")
        raise ModelError(
            f"Vision model returned invalid JSON in {stage}. "
            f"It returned {len(text)} chars starting: {snippet!r}"
        ) from exc
