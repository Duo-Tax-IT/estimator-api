import json
from functools import lru_cache

from openai import OpenAI

from .config import get_settings
from .schemas import Photo

# The vision model is sent at most this many photos per request.
MAX_PHOTOS = 60

# Cap on tokens the model may produce. For reasoning models this budget covers
# BOTH the internal reasoning and the visible JSON output, so it is set high
# enough that reasoning never starves the answer (which would return empty).
MAX_OUTPUT_TOKENS = 16000

# Reasoning depth for reasoning-class models. Renovation detection is a
# structured matching task, so a low effort keeps it fast and inexpensive.
REASONING_EFFORT = "low"

# Model-id prefixes that denote reasoning-class models (gpt-5.x, o-series).
# These take reasoning_effort and reject a custom temperature; classic chat
# models take temperature=0 instead.
_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")


@lru_cache
def _client() -> OpenAI:
    return OpenAI(api_key=get_settings().openai_api_key)


def _is_reasoning_model(model: str) -> bool:
    return model.lower().startswith(_REASONING_PREFIXES)


def generate_estimate(
    model: str, prompt: str, model_input: dict, photos: list[Photo]
) -> str:
    """Call the vision model with the prompt, input data, and property photos.

    `model_input` is the JSON object the prompt expects (property context,
    renovationItems dataset, config). Returns the raw JSON string from the
    model.

    Reasoning-class models (gpt-5.x, o-series) get `reasoning_effort` and no
    temperature; classic chat models get `temperature=0`. Both cap output via
    `max_completion_tokens` and request a JSON object.
    """
    content: list[dict] = [
        {"type": "text", "text": prompt},
        {"type": "text", "text": "Input data:\n" + json.dumps(model_input)},
    ]
    for photo in photos[:MAX_PHOTOS]:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": photo.url, "detail": "low"},
            }
        )
        if photo.date:
            content.append(
                {"type": "text", "text": f"The photo was taken on {photo.date}"}
            )

    kwargs: dict = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_completion_tokens": MAX_OUTPUT_TOKENS,
        "response_format": {"type": "json_object"},
    }
    if _is_reasoning_model(model):
        kwargs["reasoning_effort"] = REASONING_EFFORT
    else:
        kwargs["temperature"] = 0

    response = _client().chat.completions.create(**kwargs)
    return response.choices[0].message.content
