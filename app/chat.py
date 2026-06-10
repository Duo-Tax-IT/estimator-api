"""Diagnostic chat about one saved run: multi-turn Q&A grounded in the run's
pipeline trace (and optionally its photos). Explain-only — never changes the run."""

from .clients.openai_client import chat_about_run
from .config import get_settings
from .prompts import get_base_prompt
from .run_context import build_run_context
from .schemas import Photo

CHAT_PROMPT_FILE = "chat_prompt.txt"


def _run_photos(response: dict) -> list[Photo]:
    """The photos the run actually sent (Stages.photos: index→url/date). v1 has none."""
    sent = ((response.get("Stages") or {}).get("photos")) or []
    return [Photo(url=p["url"], date=p.get("date")) for p in sent if p.get("url")]


def build_chat_reply(run: dict, history: list[dict], message: str,
                     include_photos: bool = False, model: str | None = None) -> tuple[str, dict]:
    """Answer `message` about `run`, grounded in its context (and photos if asked).
    `history` is the prior {role, content} thread; returns (reply, usage)."""
    response = run.get("response") or {}
    photos = _run_photos(response) if include_photos else []
    return chat_about_run(
        model or get_settings().default_model,
        get_base_prompt(CHAT_PROMPT_FILE),
        build_run_context(response),
        [*history, {"role": "user", "content": message}],
        photos,
    )
