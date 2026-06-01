import json

import pytest

from app import estimator
from app.errors import ItemsFetchError, ModelError, NoPhotosError
from app.schemas import EstimateRequest, Photo

SAMPLE_ITEMS = [
    {"_id": "a1", "name": "Split System AC", "defaultRate": 1200, "unit": "each"}
]


def _req(**overrides):
    data = {"rpId": "RP1"}
    data.update(overrides)
    return EstimateRequest(**data)


def _model_json(**overrides):
    payload = {
        "Renovations": [
            {
                "_id": "a1",
                "Name": "Split System AC",
                "Quantity": 2,
                "Unit": "each",
                "DefaultRate": 1200,
                "FinalCost": 2400,
                "Year": "2018",
            }
        ],
        "Totals": {"TotalRenovation": 2400, "Capped": False},
        "Summary Description": "Detected split system AC.",
        "Guarantee": "This assessment is based solely on visual analysis...",
    }
    payload.update(overrides)
    return json.dumps(payload)


def _patch_upstreams(monkeypatch, items=SAMPLE_ITEMS, photos=None, property=None):
    if photos is None:
        photos = [Photo(url="https://x/a", date="2024-01-01")]
    if property is None:
        property = {"beds": "1", "propertyType": "UNIT"}
    monkeypatch.setattr(estimator, "fetch_renovation_items", lambda: items)
    monkeypatch.setattr(estimator, "fetch_photos", lambda rp_id: photos)
    monkeypatch.setattr(estimator, "fetch_property", lambda rp_id: property)


def test_build_full_estimate_formats_and_reshapes(monkeypatch):
    _patch_upstreams(monkeypatch)
    captured = {}

    def fake_generate(model, prompt, model_input, photos):
        captured.update(model=model, model_input=model_input, photos=photos)
        return _model_json()

    monkeypatch.setattr(estimator, "generate_estimate", fake_generate)

    out = estimator.build_full_estimate(_req())

    assert out["Renovations"][0]["DefaultRate"] == "$1,200.00"
    assert out["Renovations"][0]["FinalCost"] == "$2,400.00"
    assert out["Renovations Total"] == "$2,400.00"
    assert out["Summary Description"] == "Detected split system AC."
    assert out["Disclaimer"].startswith("This assessment is based solely")
    # default model used; megamind catalog + photos forwarded to the model
    assert captured["model"] == "gpt-5.4-mini"
    assert captured["model_input"]["renovationItems"] == SAMPLE_ITEMS
    assert [p.url for p in captured["photos"]] == ["https://x/a"]
    # property defaults to the attributes rpdata holds for the rp_id
    assert captured["model_input"]["property"] == {"beds": "1", "propertyType": "UNIT"}


def test_build_full_estimate_property_override(monkeypatch):
    _patch_upstreams(monkeypatch)
    captured = {}

    def fake_generate(model, prompt, model_input, photos):
        captured.update(model_input=model_input)
        return _model_json(Renovations=[], Totals={"TotalRenovation": 0})

    monkeypatch.setattr(estimator, "generate_estimate", fake_generate)
    # fetch_property would raise if called; a caller override must short-circuit it
    monkeypatch.setattr(
        estimator, "fetch_property", lambda rp_id: pytest.fail("should not fetch")
    )

    override = {"beds": "4", "source": "caller"}
    estimator.build_full_estimate(_req(property=override))
    assert captured["model_input"]["property"] == override


def test_build_full_estimate_no_items_raises(monkeypatch):
    _patch_upstreams(monkeypatch, items=[])
    with pytest.raises(ItemsFetchError):
        estimator.build_full_estimate(_req())


def test_build_full_estimate_no_photos_raises(monkeypatch):
    _patch_upstreams(monkeypatch, photos=[])
    with pytest.raises(NoPhotosError):
        estimator.build_full_estimate(_req())


def test_build_full_estimate_bad_model_json_raises(monkeypatch):
    _patch_upstreams(monkeypatch)
    monkeypatch.setattr(estimator, "generate_estimate", lambda *a, **k: "not json")
    with pytest.raises(ModelError):
        estimator.build_full_estimate(_req())


def test_build_full_estimate_uses_model_override(monkeypatch):
    _patch_upstreams(monkeypatch)
    seen = {}

    def fake_generate(model, prompt, model_input, photos):
        seen["model"] = model
        return _model_json(Renovations=[], Totals={"TotalRenovation": 0})

    monkeypatch.setattr(estimator, "generate_estimate", fake_generate)
    estimator.build_full_estimate(_req(model="gpt-4o"))
    assert seen["model"] == "gpt-4o"
