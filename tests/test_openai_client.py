from app import openai_client
from app.schemas import Photo


def _message(content="", tool_calls=None):
    return type("M", (), {"content": content, "tool_calls": tool_calls})()


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
    out = openai_client.generate_estimate(
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

    out = openai_client.generate_estimate(
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
    out = openai_client.generate_estimate(
        "gpt-4.1", "prompt", {"x": 1}, [Photo(url="https://x/a")], library=library
    )
    assert out == '{"done": true}'
    # The tool message fed back carries the catalog-priced result (2 × $1000).
    import json
    tool_msg = next(m for m in state["messages"][1] if isinstance(m, dict) and m.get("role") == "tool")
    result = json.loads(tool_msg["content"])
    assert result["total"] == 2000
    assert result["renovations"][0]["DefaultRate"] == 1000


def test_build_input_text():
    assert openai_client.build_input_text({"x": 1}) == 'Input data:\n{"x": 1}'


def test_is_reasoning_model_classification():
    assert openai_client._is_reasoning_model("gpt-5.4-mini")
    assert openai_client._is_reasoning_model("o3-mini")
    assert not openai_client._is_reasoning_model("gpt-4.1")
    assert not openai_client._is_reasoning_model("gemini-flash-3.5")
