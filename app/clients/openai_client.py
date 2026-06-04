import base64
import json
from functools import lru_cache

import httpx
from openai import OpenAI

from ..config import get_settings
from ..errors import ModelError
from ..helpers.pricing import price_items
from ..room_classifier import classify, format_hint
from ..schemas import Photo

# Hard cap on photos pulled into the pipeline (applied before dedup) and sent to
# the vision model per request. Bounds dedup download time and model output on
# listings with hundreds of re-listed shots. NOTE: this many verbose per-photo
# observations approaches the MAX_OUTPUT_TOKENS ceiling — pushing it higher needs
# batching across multiple observe/era calls, not a bigger output cap.
MAX_PHOTOS = 100

# Cap on tokens the model may produce. Set to gemini-3.5-flash's maximum so the
# per-photo observation step (up to MAX_PHOTOS verbose entries) doesn't get cut
# off mid-JSON — truncation was the main cause of "invalid JSON" errors on
# photo-heavy properties. It's a ceiling, not a target: cost is only incurred for
# tokens actually produced. If a property still truncates here, batch the photos
# across multiple observe/era calls rather than raising this further.
MAX_OUTPUT_TOKENS = 65536

# Photos per vision request. A large set (up to MAX_PHOTOS) is split across calls
# so each call's JSON — one verbose entry per photo — stays well under
# MAX_OUTPUT_TOKENS; the results are merged with a single global photoIndex.
PHOTO_BATCH = 40

# gemini-3.5-flash standard pricing, USD per 1M tokens (output includes thinking).
# Source: https://ai.google.dev/gemini-api/docs/pricing
_INPUT_USD_PER_1M = 1.50
_OUTPUT_USD_PER_1M = 9.00


def _usage(prompt_tokens: int, completion_tokens: int) -> dict:
    """Token counts + USD cost for a call; also logs one line to stdout."""
    cost = (prompt_tokens * _INPUT_USD_PER_1M + completion_tokens * _OUTPUT_USD_PER_1M) / 1_000_000
    summary = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "cost": round(cost, 4),
    }
    print(f"[usage] {summary}")
    return summary


def merge_usage(*summaries: dict) -> dict:
    """Sum several usage summaries (multi-call pipelines) into one."""
    total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0.0}
    for s in summaries:
        for k in total:
            total[k] += s.get(k, 0)
    total["cost"] = round(total["cost"], 4)
    return total

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


def _data_url(resp: httpx.Response) -> str:
    """Inline an already-fetched image response as a base64 data URI (Gemini's
    OpenAI-compatible endpoint does not fetch remote URLs)."""
    mime = resp.headers.get("content-type", "image/jpeg").split(";")[0]
    return f"data:{mime};base64,{base64.b64encode(resp.content).decode()}"


def _image_data_url(url: str) -> str:
    """Download an image and inline it as a base64 data URI.

    Raises httpx.HTTPError if the image can't be fetched.
    """
    resp = httpx.get(url, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    return _data_url(resp)


def build_input_text(model_input: dict) -> str:
    """The 'Input data' text block injected after the prompt."""
    return "Input data:\n" + json.dumps(model_input)


def _extract_json(text: str) -> str:
    """Pull the JSON object out of the model's reply, tolerating a ```json fence
    or stray prose some models add despite JSON mode. For a single top-level
    object the first '{' and last '}' are its true bounds, so slicing between
    them is safe even when inner strings contain braces.
    """
    if not text:
        return text
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


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
) -> tuple[str, dict]:
    """Call the vision model with the prompt, input data, and property photos.

    `model_input` is the JSON object the prompt expects (property context,
    trimmed renovationItems dataset, the backend-computed `gfa`, config).
    `library` is the full catalog keyed by `_id`, used to price the model's
    tool calls (the trimmed `model_input` copy has no rates). Returns the raw
    JSON string from the model plus a usage summary (tokens + USD cost).

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
            return message.content, _usage(prompt_tokens, completion_tokens)
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
    return message.content, _usage(prompt_tokens, completion_tokens)


def _photo_content(photos: list[Photo]) -> tuple[list[dict], list[dict], list[dict]]:
    """Vision content blocks for up to MAX_PHOTOS, inlined as base64 (Gemini
    won't fetch remote URLs), plus the room-classifier prediction per photo.

    A photo that can't be fetched is skipped; each image is followed by a
    predicted room-type hint (when confident) and its capture date when known.
    `photoIndex` counts only images actually sent, matching how the model indexes
    them. Returns (content, predictions, sent_photos); predictions and the
    index→url/date map (sent_photos) are recorded in Stages so each evidence
    `photoIndex` resolves to a real image."""
    content: list[dict] = []
    predictions: list[dict] = []
    sent_photos: list[dict] = []
    sent = 0
    for photo in photos[:MAX_PHOTOS]:
        try:
            resp = httpx.get(photo.url, timeout=30, follow_redirects=True)
            resp.raise_for_status()
        except httpx.HTTPError:
            continue  # non-fatal: skip a photo we couldn't fetch
        content.append({"type": "image_url", "image_url": {"url": _data_url(resp)}})
        prediction = classify(resp.content)
        if prediction:
            predictions.append({"photoIndex": sent, **prediction})
            hint = format_hint(prediction)
            if hint:
                content.append({"type": "text", "text": hint})
        if photo.date:
            content.append(
                {"type": "text", "text": f"The photo was taken on {photo.date}"}
            )
        sent_photos.append({"photoIndex": sent, "url": photo.url, "date": photo.date})
        sent += 1
    return content, predictions, sent_photos


def _chat_json(
    model: str,
    content: list[dict],
    *,
    reasoning_effort: str | None = None,
    temperature: float | None = None,
) -> tuple[str, dict]:
    """One JSON-only chat completion (no tools). Returns (json_text, usage summary).

    Shared by the v2 pipeline's observe/era/support/match stages. Reasoning-class
    models get `reasoning_effort` and no temperature; others get `temperature`.

    JSON mode should always yield valid JSON, so an unparseable reply is almost
    always a cut-off / abnormal finish. We retry once (transient hiccup); a `length`
    cap is surfaced immediately (retrying would just truncate again), and a
    persistent failure surfaces the `finish_reason` so a non-length stop (e.g.
    RECITATION/SAFETY, which our guard can't pre-empt) is diagnosable rather than a
    mystery "invalid JSON".
    """
    kwargs: dict = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": MAX_OUTPUT_TOKENS,
        "response_format": {"type": "json_object"},
    }
    if _is_reasoning_model(model):
        kwargs["reasoning_effort"] = reasoning_effort or REASONING_EFFORT
    else:
        kwargs["temperature"] = temperature if temperature is not None else 0

    prompt_tokens = completion_tokens = 0
    last_text = last_reason = None
    for _ in range(2):
        resp = _client().chat.completions.create(**kwargs)
        usage = getattr(resp, "usage", None)
        if usage:
            prompt_tokens += usage.prompt_tokens
            completion_tokens += usage.completion_tokens
        choice = resp.choices[0]
        last_reason = choice.finish_reason
        if choice.finish_reason == "length":
            raise ModelError(
                f"Vision model output hit the {MAX_OUTPUT_TOKENS}-token cap (the "
                "model maximum) and was cut off before completing its JSON — the "
                "property has too many photos. Lower MAX_PHOTOS, or batch the "
                "photos across multiple observe/era calls."
            )
        text = _extract_json(choice.message.content or "")
        try:
            json.loads(text)
        except (json.JSONDecodeError, TypeError):
            last_text = text
            continue  # transient bad JSON — retry once
        return text, _usage(prompt_tokens, completion_tokens)

    snippet = (last_text or "")[:500] + (" …" if len(last_text or "") > 500 else "")
    raise ModelError(
        f"Vision model returned unparseable JSON (finish_reason={last_reason!r}) "
        f"after a retry — the reply was cut off without a length flag. It returned "
        f"{len(last_text or '')} chars starting: {snippet!r}"
    )


def _loads(raw: str, stage: str) -> dict:
    """json.loads that raises a diagnosable ModelError on a bad/truncated reply."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        text = raw or ""
        snippet = text[:300] + (" …" if len(text) > 300 else "")
        raise ModelError(
            f"Vision model returned invalid JSON in {stage}. "
            f"It returned {len(text)} chars starting: {snippet!r}"
        ) from exc


def _run_photo_batches(
    model: str,
    prompt: str,
    photos: list[Photo],
    list_key: str,
    stage: str,
    *,
    reasoning_effort: str | None = None,
    temperature: float | None = None,
) -> tuple[dict, dict, list[dict], list[dict]]:
    """Run a vision prompt over `photos` in batches of PHOTO_BATCH and merge.

    Splitting keeps each call's output (one entry per photo under `list_key`) under
    MAX_OUTPUT_TOKENS on photo-heavy properties. Each batch's `photoIndex` values
    (the entries, classifier predictions, and sent-photo map) are shifted by the
    running count of photos already sent, so the merged result keeps one global
    0-based index. Returns (merged {list_key: [...]}, summed usage, predictions,
    sent_photos)."""
    items: list[dict] = []
    predictions: list[dict] = []
    sent_photos: list[dict] = []
    usages: list[dict] = []
    offset = 0
    for start in range(0, len(photos), PHOTO_BATCH):
        blocks, preds, sent = _photo_content(photos[start : start + PHOTO_BATCH])
        content = [{"type": "text", "text": prompt}, *blocks]
        raw, usage = _chat_json(
            model, content, reasoning_effort=reasoning_effort, temperature=temperature
        )
        for entry in _loads(raw, stage).get(list_key, []):
            if isinstance(entry.get("photoIndex"), int):
                entry["photoIndex"] += offset
            items.append(entry)
        predictions += [{**p, "photoIndex": p["photoIndex"] + offset} for p in preds]
        sent_photos += [{**s, "photoIndex": s["photoIndex"] + offset} for s in sent]
        usages.append(usage)
        offset += len(sent)
    return {list_key: items}, merge_usage(*usages), predictions, sent_photos


def observe_photos(
    model: str,
    prompt: str,
    photos: list[Photo],
    *,
    reasoning_effort: str | None = None,
    temperature: float | None = None,
) -> tuple[str, dict, list[dict], list[dict]]:
    """v2 Step 1: describe what's visible in each photo (no matching/pricing).

    Photos are processed in batches and merged (see _run_photo_batches). Also
    returns the room-classifier prediction per photo and the index→url/date map of
    the photos actually sent, both for Stages debug."""
    merged, usage, predictions, sent_photos = _run_photo_batches(
        model, prompt, photos, "photoObservations", "observation",
        reasoning_effort=reasoning_effort, temperature=temperature,
    )
    return json.dumps(merged), usage, predictions, sent_photos


def analyze_era(
    model: str,
    prompt: str,
    photos: list[Photo],
    *,
    reasoning_effort: str | None = None,
    temperature: float | None = None,
) -> tuple[str, dict]:
    """v2 Step 1b: forensically date visible finishes from fabrication/style cues.

    A pure observation pass like observe_photos (batched + merged) — it only reports
    what it sees and the era the fabrication technology implies. It is given no
    build year and makes no renovation/original call; Step 2 does that comparison."""
    merged, usage, _, _ = _run_photo_batches(
        model, prompt, photos, "eraAnalysis", "era analysis",
        reasoning_effort=reasoning_effort, temperature=temperature,
    )
    return json.dumps(merged), usage


def assess_support(
    model: str,
    prompt: str,
    payload: dict,
    *,
    reasoning_effort: str | None = None,
    temperature: float | None = None,
) -> tuple[str, dict]:
    """v2 Step 1.5: judge whether observed items are renovation-supported, before
    any catalog matching (text-only, reasons over observations + era + property)."""
    content = [
        {"type": "text", "text": prompt},
        {"type": "text", "text": build_input_text(payload)},
    ]
    return _chat_json(
        model, content, reasoning_effort=reasoning_effort, temperature=temperature
    )


def match_candidates(
    model: str,
    prompt: str,
    payload: dict,
    *,
    reasoning_effort: str | None = None,
    temperature: float | None = None,
) -> tuple[str, dict]:
    """v2 Step 2: match observations to the catalog (text-only, no photos)."""
    content = [
        {"type": "text", "text": prompt},
        {"type": "text", "text": build_input_text(payload)},
    ]
    return _chat_json(
        model, content, reasoning_effort=reasoning_effort, temperature=temperature
    )
