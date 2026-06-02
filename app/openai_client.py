import base64
import json
from functools import lru_cache

import httpx
from openai import OpenAI

from .config import get_settings
from .pricing import price_items
from .schemas import Photo

# The vision model is sent at most this many photos per request.
MAX_PHOTOS = 60

# Cap on tokens the model may produce.
MAX_OUTPUT_TOKENS = 16000

# gemini-3.5-flash standard pricing, USD per 1M tokens (output includes thinking).
# Source: https://ai.google.dev/gemini-api/docs/pricing
_INPUT_USD_PER_1M = 1.50
_OUTPUT_USD_PER_1M = 9.00


def _log_usage(prompt_tokens: int, completion_tokens: int) -> None:
    cost = (prompt_tokens * _INPUT_USD_PER_1M + completion_tokens * _OUTPUT_USD_PER_1M) / 1_000_000
    print(
        f"[usage] prompt={prompt_tokens} completion={completion_tokens} "
        f"total={prompt_tokens + completion_tokens} cost=${cost:.4f}"
    )

# Reasoning depth for reasoning-class models. Medium keeps borderline item
# detection consistent run-to-run; low effort flips items in and out.
REASONING_EFFORT = "medium"

# Model-id prefixes that denote reasoning-class models (gpt-5.x, o-series).
# These take reasoning_effort and reject a custom temperature; other models take
# temperature=0 instead. Gemini models fall in the temperature branch.
_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")

# Tool the model calls to price detected renovations: it passes each item's _id
# (and, for sqm items, the area in m²); rate/unit/quantity/cost are looked up
# from the catalog server-side (price_items), so the model can't alter pricing.
RENOVATIONS_TOOL = {
    "type": "function",
    "function": {
        "name": "calculate_renovations",
        "description": "Price detected renovation items from the authoritative "
        "catalog. Pass each item's _id and, for sqm items, the area in square "
        "metres. Rates, units, quantities and costs are computed server-side — "
        "you cannot set them. Use the returned values in your output.",
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "_id": {"type": "string"},
                            "name": {
                                "type": "string",
                                "description": "The matched item's name — used to "
                                "recover the item if the _id is mistyped",
                            },
                            "area": {
                                "type": "number",
                                "description": "Area in m² — sqm items only",
                            },
                        },
                        "required": ["_id"],
                    },
                }
            },
            "required": ["items"],
        },
    },
}


@lru_cache
def _client() -> OpenAI:
    # Gemini via Google's OpenAI-compatible endpoint.
    settings = get_settings()
    return OpenAI(api_key=settings.gemini_api_key, base_url=settings.gemini_base_url)


def _is_reasoning_model(model: str) -> bool:
    return model.lower().startswith(_REASONING_PREFIXES)


def _image_data_url(url: str) -> str:
    """Download an image and inline it as a base64 data URI.

    Gemini's OpenAI-compatible endpoint does not fetch remote URLs, so the bytes
    must be sent inline. Raises httpx.HTTPError if the image can't be fetched.
    """
    resp = httpx.get(url, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    mime = resp.headers.get("content-type", "image/jpeg").split(";")[0]
    data = base64.b64encode(resp.content).decode()
    return f"data:{mime};base64,{data}"


def build_input_text(model_input: dict) -> str:
    """The 'Input data' text block injected after the prompt."""
    return "Input data:\n" + json.dumps(model_input)


def generate_estimate(
    model: str,
    prompt: str,
    model_input: dict,
    photos: list[Photo],
    *,
    library: dict,
    living_space: float | None = None,
    reasoning_effort: str | None = None,
    temperature: float | None = None,
) -> str:
    """Call the vision model with the prompt, input data, and property photos.

    `model_input` is the JSON object the prompt expects (property context,
    trimmed renovationItems dataset, the backend-computed `gfa`, config).
    `library` is the full catalog keyed by `_id`, used to price the model's
    tool calls (the trimmed `model_input` copy has no rates). Returns the raw
    JSON string from the model.

    The model makes a single tool call — `calculate_renovations` — to price its
    detected items; `living_space` (computed server-side from the GFA) caps the
    total sqm area. Photos are downloaded and inlined as base64 (Gemini won't
    fetch remote URLs); a photo that can't be fetched is skipped. Reasoning-class
    models get `reasoning_effort` and no temperature; others get `temperature`.
    """
    content: list[dict] = [
        {"type": "text", "text": prompt},
        {"type": "text", "text": build_input_text(model_input)},
    ]
    for photo in photos[:MAX_PHOTOS]:
        try:
            data_url = _image_data_url(photo.url)
        except httpx.HTTPError:
            continue  # non-fatal: skip a photo we couldn't fetch
        content.append({"type": "image_url", "image_url": {"url": data_url}})
        if photo.date:
            content.append(
                {"type": "text", "text": f"The photo was taken on {photo.date}"}
            )

    kwargs: dict = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": MAX_OUTPUT_TOKENS,
        "response_format": {"type": "json_object"},
        "tools": [RENOVATIONS_TOOL],
    }
    if _is_reasoning_model(model):
        kwargs["reasoning_effort"] = reasoning_effort or REASONING_EFFORT
    else:
        kwargs["temperature"] = temperature if temperature is not None else 0

    # calculate_renovations prices items from this request's catalog (`library`);
    # living_space (computed server-side from the GFA) caps the total sqm area.

    # Run the tool calls the model makes, feed the results back, until it returns
    # the final JSON. Capped so a misbehaving model can't loop forever.
    prompt_tokens = completion_tokens = 0
    for _ in range(5):
        resp = _client().chat.completions.create(**kwargs)
        usage = getattr(resp, "usage", None)
        if usage:
            prompt_tokens += usage.prompt_tokens
            completion_tokens += usage.completion_tokens
        message = resp.choices[0].message
        if not getattr(message, "tool_calls", None):
            _log_usage(prompt_tokens, completion_tokens)
            return message.content
        kwargs["messages"].append(message)
        for call in message.tool_calls:
            args = json.loads(call.function.arguments)
            result = price_items(args.get("items", []), library, living_space)
            kwargs["messages"].append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result),
                }
            )
    _log_usage(prompt_tokens, completion_tokens)
    return message.content
