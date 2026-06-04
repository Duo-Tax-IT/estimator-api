import json

import pytest
from fastapi.testclient import TestClient

from app import learning, main
from app.errors import ModelError

RUN = {
    "id": 7, "rp_id": "RP1", "address": "1 King St", "model": "gemini-3.5-flash",
    "response": {
        "Renovations": [{"Name": "Bathroom", "Year": "2018"}],
        "Renovations Total": "$2,400.00",
        "Stages": {"renovationSupport": {"renovationSupportFindings": [{"observedItem": "vanity"}]}},
        "Meta": {"pipeline": "v2"},
    },
}
ANALYSIS = {
    "accuracySummary": "Close, missed the kitchen.",
    "discrepancies": [{"item": "Kitchen", "issue": "missed", "rootCauseStage": "support",
                       "expert": "kitchen reno 2019", "system": "not detected", "explanation": "support gated it out"}],
    "tuningRecommendations": [{"target": "support_prompt", "change": "lower the bar for kitchen benchtops",
                               "rationale": "missed a real reno", "priority": "high"}],
}


def test_build_learning_analysis_feeds_logs_and_parses(monkeypatch):
    captured = {}

    def fake(model, prompt, payload):
        captured["payload"] = payload
        return json.dumps(ANALYSIS), {}

    monkeypatch.setattr(learning, "analyze_learning", fake)
    out = learning.build_learning_analysis(RUN, "expert says: full bathroom reno 2018")

    assert out == ANALYSIS
    # Both the expert truth and the run's Stages logs are fed to the model.
    assert captured["payload"]["expertGroundTruth"].startswith("expert says")
    assert captured["payload"]["systemRun"]["Stages"] == RUN["response"]["Stages"]
    assert captured["payload"]["systemRun"]["Renovations"][0]["Name"] == "Bathroom"


def test_build_learning_analysis_raises_on_bad_json(monkeypatch):
    monkeypatch.setattr(learning, "analyze_learning", lambda *a: ("not json", {}))
    with pytest.raises(ModelError):
        learning.build_learning_analysis(RUN, "x")


def test_learn_analyze_endpoint_saves_and_returns(monkeypatch):
    monkeypatch.setattr(main, "get_run", lambda rid: RUN if rid == 7 else None)
    monkeypatch.setattr(learning, "analyze_learning", lambda *a: (json.dumps(ANALYSIS), {}))
    saved = {}
    monkeypatch.setattr(main, "save_learning",
                        lambda run_id, expert, analysis: saved.update(run_id=run_id, analysis=analysis) or 99)

    c = TestClient(main.app)
    resp = c.post("/learn/analyze", json={"runId": 7, "expertInput": "full bathroom reno"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == 99 and body["analysis"] == ANALYSIS
    assert saved["run_id"] == 7 and saved["analysis"] == ANALYSIS


def test_learn_analyze_404_for_missing_run(monkeypatch):
    monkeypatch.setattr(main, "get_run", lambda rid: None)
    c = TestClient(main.app)
    resp = c.post("/learn/analyze", json={"runId": 999, "expertInput": "x"})
    assert resp.status_code == 404
