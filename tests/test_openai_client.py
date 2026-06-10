import json

import pytest

from app.clients import openai_client
from app.errors import ModelError
from app.schemas import Photo


def _message(content="", tool_calls=None):
    return type("M", (), {"content": content, "tool_calls": tool_calls})()


def _resp(content, finish_reason="stop"):
    choice = type("C", (), {"message": _message(content), "finish_reason": finish_reason})()
    return type("R", (), {"choices": [choice], "usage": None})()


def _patch_chat(monkeypatch, resp):
    comp = type("Comp", (), {"create": lambda self, **kw: resp})()
    client = type("Cl", (), {"chat": type("Ch", (), {"completions": comp})()})()
    monkeypatch.setattr(openai_client, "_client", lambda: client)


class _FakeCompletions:
    def __init__(self, sink, message):
        self._sink = sink
        self._message = message

    def create(self, **kwargs):
        self._sink.update(kwargs)
        return type("R", (), {"choices": [type("C", (), {"message": self._message})()]})()


def _patch(monkeypatch, sink, message=None):
    message = message or _message('{"ok": true}')
    client = type("Cl", (), {"chat": type("Ch", (), {"completions": _FakeCompletions(sink, message)})()})()
    monkeypatch.setattr(openai_client, "_client", lambda: client)
    # Skip the real image download — return a stub data URI.
    monkeypatch.setattr(openai_client, "_image_data_url", lambda url: "data:image/jpeg;base64,AAA")


def test_reasoning_model_uses_reasoning_effort_no_temperature(monkeypatch):
    sink = {}
    _patch(monkeypatch, sink)
    out, _ = openai_client.generate_estimate(
        "gpt-5.4-mini", "prompt", {"x": 1},
        [Photo(url="https://x/a", date="2024-01-01")], library={},
    )
    assert out == '{"ok": true}'
    assert sink["model"] == "gpt-5.4-mini"
    assert sink["reasoning_effort"] == "medium"
    assert "temperature" not in sink
    assert "max_tokens" in sink
    assert sink["response_format"] == {"type": "json_object"}
    assert sink["tools"] == [openai_client.RENOVATIONS_TOOL]
    content_types = [c["type"] for c in sink["messages"][0]["content"]]
    assert "image_url" in content_types  # photo inlined as base64
    assert content_types.count("text") >= 3  # prompt + input + photo date


def test_classic_model_uses_temperature_no_reasoning(monkeypatch):
    sink = {}
    _patch(monkeypatch, sink)
    openai_client.generate_estimate("gpt-4.1", "prompt", {"x": 1}, [Photo(url="https://x/a")], library={})
    assert sink["temperature"] == 0
    assert "reasoning_effort" not in sink
    assert "max_tokens" in sink


def test_reasoning_effort_override_is_applied(monkeypatch):
    sink = {}
    _patch(monkeypatch, sink)
    openai_client.generate_estimate(
        "gpt-5.4-mini", "prompt", {"x": 1}, [Photo(url="https://x/a")],
        library={}, reasoning_effort="high",
    )
    assert sink["reasoning_effort"] == "high"
    assert "temperature" not in sink


def test_temperature_override_is_applied_for_classic(monkeypatch):
    sink = {}
    _patch(monkeypatch, sink)
    openai_client.generate_estimate(
        "gpt-4.1", "prompt", {"x": 1}, [Photo(url="https://x/a")], library={}, temperature=0.7,
    )
    assert sink["temperature"] == 0.7
    assert "reasoning_effort" not in sink


def test_skips_photos_that_fail_to_download(monkeypatch):
    import httpx

    sink = {}
    _patch(monkeypatch, sink)

    def boom(url):
        raise httpx.ConnectError("nope")

    monkeypatch.setattr(openai_client, "_image_data_url", boom)
    openai_client.generate_estimate("gpt-4.1", "prompt", {"x": 1}, [Photo(url="https://x/a")], library={})
    content_types = [c["type"] for c in sink["messages"][0]["content"]]
    assert "image_url" not in content_types  # the unfetchable photo was skipped


def test_runs_tool_call_then_returns_final(monkeypatch):
    # First response asks for calculate_gfa; second returns the final JSON.
    state = {"n": 0, "messages": []}
    call = type("Call", (), {
        "id": "c1",
        "function": type("F", (), {"name": "calculate_gfa",
                                   "arguments": '{"property_gfa": 100, "bedrooms": 2}'})(),
    })()

    class _ToolCompletions:
        def create(self, **kwargs):
            state["messages"].append(list(kwargs["messages"]))
            state["n"] += 1
            msg = _message("", [call]) if state["n"] == 1 else _message('{"done": true}')
            return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()

    client = type("Cl", (), {"chat": type("Ch", (), {"completions": _ToolCompletions()})()})()
    monkeypatch.setattr(openai_client, "_client", lambda: client)
    monkeypatch.setattr(openai_client, "_image_data_url", lambda url: "data:image/jpeg;base64,AAA")

    out, _ = openai_client.generate_estimate(
        "gpt-4.1", "prompt", {"x": 1}, [Photo(url="https://x/a")], library={}
    )
    assert out == '{"done": true}'
    assert state["n"] == 2
    # The second call carries the tool result we fed back.
    assert any(
        isinstance(m, dict) and m.get("role") == "tool" for m in state["messages"][1]
    )


def test_calculate_renovations_tool_prices_from_catalog(monkeypatch):
    # The model asks calculate_renovations for one catalog item; the tool result
    # fed back must be priced from the server-side `library`, not the model.
    state = {"n": 0, "messages": []}
    call = type("Call", (), {
        "id": "c1",
        "function": type("F", (), {"name": "calculate_renovations",
                                   "arguments": '{"items": [{"_id": "a1"}]}'})(),
    })()

    class _Comp:
        def create(self, **kwargs):
            state["messages"].append(list(kwargs["messages"]))
            state["n"] += 1
            msg = _message("", [call]) if state["n"] == 1 else _message('{"done": true}')
            return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()

    client = type("Cl", (), {"chat": type("Ch", (), {"completions": _Comp()})()})()
    monkeypatch.setattr(openai_client, "_client", lambda: client)
    monkeypatch.setattr(openai_client, "_image_data_url", lambda url: "data:image/jpeg;base64,AAA")

    library = {"a1": {"_id": "a1", "name": "AC", "defaultRate": 1000, "unit": "each",
                      "defaultQuantity": 2, "parentName": None}}
    out, _ = openai_client.generate_estimate(
        "gpt-4.1", "prompt", {"x": 1}, [Photo(url="https://x/a")], library=library
    )
    assert out == '{"done": true}'
    # The tool message fed back carries the catalog-priced result (2 × $1000).
    import json
    tool_msg = next(m for m in state["messages"][1] if isinstance(m, dict) and m.get("role") == "tool")
    result = json.loads(tool_msg["content"])
    assert result["total"] == 2000
    assert result["renovations"][0]["DefaultRate"] == 1000


def test_extract_json_strips_fences_and_prose():
    assert openai_client._extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert openai_client._extract_json('Here you go: {"a": 1} cheers') == '{"a": 1}'
    # First '{' / last '}' are the true bounds even when a string holds a brace.
    assert openai_client._extract_json('{"a": "}"}') == '{"a": "}"}'


def test_chat_json_unwraps_fenced_output(monkeypatch):
    _patch_chat(monkeypatch, _resp('```json\n{"ok": true}\n```'))
    text, _ = openai_client._chat_json("gemini-x", [{"type": "text", "text": "p"}])
    assert text == '{"ok": true}'


def test_chat_json_raises_clear_error_on_truncation(monkeypatch):
    _patch_chat(monkeypatch, _resp('{"photoObservations": [', finish_reason="length"))
    with pytest.raises(ModelError, match="cut off"):
        openai_client._chat_json("gemini-x", [{"type": "text", "text": "p"}])


def test_chat_json_retries_once_on_bad_json_then_succeeds(monkeypatch):
    # JSON mode hiccup: first reply is unparseable, the retry is clean.
    seq = iter([_resp("{bad json"), _resp('{"ok": true}')])
    comp = type("Comp", (), {"create": lambda self, **kw: next(seq)})()
    client = type("Cl", (), {"chat": type("Ch", (), {"completions": comp})()})()
    monkeypatch.setattr(openai_client, "_client", lambda: client)
    text, _ = openai_client._chat_json("gemini-x", [{"type": "text", "text": "p"}])
    assert text == '{"ok": true}'


def test_chat_json_raises_with_finish_reason_when_json_stays_bad(monkeypatch):
    # A non-length abnormal stop (e.g. content_filter/recitation) is surfaced with
    # its finish_reason, not a mystery "invalid JSON".
    bad = _resp("{bad json", finish_reason="content_filter")
    comp = type("Comp", (), {"create": lambda self, **kw: bad})()
    client = type("Cl", (), {"chat": type("Ch", (), {"completions": comp})()})()
    monkeypatch.setattr(openai_client, "_client", lambda: client)
    with pytest.raises(ModelError, match="finish_reason='content_filter'"):
        openai_client._chat_json("gemini-x", [{"type": "text", "text": "p"}])


def test_chat_json_retry_diverges_on_early_stop(monkeypatch):
    # A temp-0 reply that stops early (finish_reason='stop', not 'length') would
    # re-truncate identically, so the retry must diverge: temperature off 0 + a
    # reminder to finish the JSON.
    calls = []
    seq = iter([_resp('{"validatedCandidates": [', finish_reason="stop"),
                _resp('{"ok": true}')])

    def create(self, **kw):
        calls.append(kw)
        return next(seq)

    comp = type("Comp", (), {"create": create})()
    client = type("Cl", (), {"chat": type("Ch", (), {"completions": comp})()})()
    monkeypatch.setattr(openai_client, "_client", lambda: client)

    text, _ = openai_client._chat_json("gemini-x", [{"type": "text", "text": "p"}])
    assert text == '{"ok": true}'
    assert len(calls) == 2
    assert calls[0]["temperature"] == 0  # deterministic first try
    assert calls[1]["temperature"] >= 0.4  # diverged retry
    # The retry carries an extra reminder message to emit the whole object.
    assert len(calls[1]["messages"]) == 2
    assert "ENTIRE JSON" in calls[1]["messages"][1]["content"]


def test_build_input_text():
    assert openai_client.build_input_text({"x": 1}) == 'Input data:\n{"x": 1}'


def test_observe_photos_batches_and_offsets_global_photoindex(monkeypatch):
    # 3 photos with PHOTO_BATCH=2 → two calls; the 2nd batch's photoIndex must be
    # offset by the 2 photos sent in the first so the merged index stays global.
    monkeypatch.setattr(openai_client, "PHOTO_BATCH", 2)

    def fake_content(batch):
        preds = [{"photoIndex": i, "label": "r"} for i in range(len(batch))]
        sent = [{"photoIndex": i, "url": p.url, "date": p.date} for i, p in enumerate(batch)]
        return [], preds, sent

    monkeypatch.setattr(openai_client, "_photo_content", fake_content)

    calls = {"n": 0}

    def fake_chat(model, content, **kw):
        calls["n"] += 1
        # Each batch reports one finding at its LOCAL index 0.
        return json.dumps({"photoObservations": [{"photoIndex": 0, "tag": f"b{calls['n']}"}]}), \
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 10, "cost": 0.1}

    monkeypatch.setattr(openai_client, "_chat_json", fake_chat)

    photos = [Photo(url=f"u{i}") for i in range(3)]
    raw, usage, preds, sent = openai_client.observe_photos("m", "p", photos)

    obs = json.loads(raw)["photoObservations"]
    assert calls["n"] == 2                                  # 3 photos / batch 2
    assert [o["photoIndex"] for o in obs] == [0, 2]         # batch 2 offset by 2 sent
    assert [o["tag"] for o in obs] == ["b1", "b2"]
    assert [s["photoIndex"] for s in sent] == [0, 1, 2]     # contiguous global map
    assert [p["photoIndex"] for p in preds] == [0, 1, 2]
    assert usage["total_tokens"] == 20                      # summed across batches


def test_is_reasoning_model_classification():
    assert openai_client._is_reasoning_model("gpt-5.4-mini")
    assert openai_client._is_reasoning_model("o3-mini")
    assert not openai_client._is_reasoning_model("gpt-4.1")
    assert not openai_client._is_reasoning_model("gemini-flash-3.5")
