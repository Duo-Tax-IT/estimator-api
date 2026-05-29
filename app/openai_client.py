import json
from functools import lru_cache

from openai import OpenAI

from .config import get_settings
from .schemas import Photo

# The vision model is sent at most this many photos per request.
MAX_PHOTOS = 60


@lru_cache
def _client() -> OpenAI:
    return OpenAI(api_key=get_settings().openai_api_key)


def generate_estimate(
    model: str, prompt: str, model_input: dict, photos: list[Photo]
) -> str:
    """Call the vision model with the prompt, input data, and property photos.

    `model_input` is the JSON object the prompt expects (property context,
    renovationItems dataset, config). Returns the raw JSON string from the
    model.
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

    response = _client().chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        max_tokens=4096,
        temperature=0,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content
