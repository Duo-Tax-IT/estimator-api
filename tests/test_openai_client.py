from app import openai_client
from app.schemas import Photo


class _FakeCompletions:
    def __init__(self, sink):
        self._sink = sink

    def create(self, **kwargs):
        self._sink.update(kwargs)

        class _Msg:
            content = '{"ok": true}'

        class _Choice:
            message = _Msg()

        class _Resp:
            choices = [_Choice()]

        return _Resp()


class _FakeClient:
    def __init__(self, sink):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(sink)})()


def test_reasoning_model_uses_reasoning_effort_no_temperature(monkeypatch):
    sink = {}
    monkeypatch.setattr(openai_client, "_client", lambda: _FakeClient(sink))
    out = openai_client.generate_estimate(
        "gpt-5.4-mini", "prompt", {"x": 1},
        [Photo(url="https://x/a", date="2024-01-01")],
    )
    assert out == '{"ok": true}'
    assert sink["model"] == "gpt-5.4-mini"
    assert sink["reasoning_effort"] == "low"
    assert "temperature" not in sink
    assert "max_completion_tokens" in sink
    assert "max_tokens" not in sink
    assert sink["response_format"] == {"type": "json_object"}
    content_types = [c["type"] for c in sink["messages"][0]["content"]]
    assert "image_url" in content_types  # photo attached
    assert content_types.count("text") >= 3  # prompt + input + photo date


def test_classic_model_uses_temperature_no_reasoning(monkeypatch):
    sink = {}
    monkeypatch.setattr(openai_client, "_client", lambda: _FakeClient(sink))
    openai_client.generate_estimate(
        "gpt-4.1", "prompt", {"x": 1}, [Photo(url="https://x/a")]
    )
    assert sink["temperature"] == 0
    assert "reasoning_effort" not in sink
    assert "max_completion_tokens" in sink


def test_reasoning_effort_override_is_applied(monkeypatch):
    sink = {}
    monkeypatch.setattr(openai_client, "_client", lambda: _FakeClient(sink))
    openai_client.generate_estimate(
        "gpt-5.4-mini", "prompt", {"x": 1}, [Photo(url="https://x/a")],
        reasoning_effort="high",
    )
    assert sink["reasoning_effort"] == "high"
    assert "temperature" not in sink


def test_temperature_override_is_applied_for_classic(monkeypatch):
    sink = {}
    monkeypatch.setattr(openai_client, "_client", lambda: _FakeClient(sink))
    openai_client.generate_estimate(
        "gpt-4.1", "prompt", {"x": 1}, [Photo(url="https://x/a")],
        temperature=0.7,
    )
    assert sink["temperature"] == 0.7
    assert "reasoning_effort" not in sink


def test_reasoning_effort_ignored_for_classic_model(monkeypatch):
    # A reasoning_effort sent to a classic model must not leak into the call.
    sink = {}
    monkeypatch.setattr(openai_client, "_client", lambda: _FakeClient(sink))
    openai_client.generate_estimate(
        "gpt-4.1", "prompt", {"x": 1}, [Photo(url="https://x/a")],
        reasoning_effort="high",
    )
    assert "reasoning_effort" not in sink
    assert sink["temperature"] == 0


def test_is_reasoning_model_classification():
    assert openai_client._is_reasoning_model("gpt-5.4-mini")
    assert openai_client._is_reasoning_model("o3-mini")
    assert not openai_client._is_reasoning_model("gpt-4.1")
    assert not openai_client._is_reasoning_model("gpt-4o")
