import json

import pytest

from app import estimator
from app.errors import ItemsFetchError, ModelError, NoPhotosError
from app.schemas import EstimateRequest, Photo

SAMPLE_ITEMS = [
    {"_id": "a1", "name": "Split System AC", "defaultRate": 1200, "unit": "each",
     "defaultQuantity": 2, "parentName": "Cooling"}
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
                "Quantity": 5,
                "Unit": "each",
                "DefaultRate": 1200,
                "FinalCost": 6000,
                "Year": "2018",
            }
        ],
        "Totals": {"TotalRenovation": 6000, "Capped": False},
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
    # No BCI scaling by default (factor 1.0); tests that need it override this.
    monkeypatch.setattr(estimator, "fetch_bci_factor", lambda state, date: 1.0)


def test_build_full_estimate_formats_and_reshapes(monkeypatch):
    _patch_upstreams(monkeypatch)
    captured = {}

    def fake_generate(model, prompt, model_input, photos, **kwargs):
        captured.update(model=model, model_input=model_input, photos=photos)
        return _model_json()

    monkeypatch.setattr(estimator, "generate_estimate", fake_generate)

    out = estimator.build_full_estimate(_req())

    # Quantity comes from the library's defaultQty (2), not the model's (5);
    # FinalCost and the total are recomputed from it.
    assert out["Renovations"][0]["Quantity"] == 2
    assert out["Renovations"][0]["parentName"] == "Cooling"
    assert out["Renovations"][0]["DefaultRate"] == "$1,200.00"
    assert out["Renovations"][0]["FinalCost"] == "$2,400.00"
    assert out["Renovations Total"] == "$2,400.00"
    assert out["Summary Description"] == "Detected split system AC."
    assert out["Disclaimer"].startswith("This assessment is based solely")
    # property attributes are echoed back for debugging
    assert out["Property"] == {"beds": "1", "propertyType": "UNIT"}
    # default model used; megamind catalog + photos forwarded to the model. The
    # catalog is trimmed to the fields the model may use (no rate/quantity).
    assert captured["model"] == "gemini-3.5-flash"
    assert captured["model_input"]["renovationItems"] == [
        {"_id": "a1", "name": "Split System AC", "unit": "each", "parentName": "Cooling"}
    ]
    assert [p.url for p in captured["photos"]] == ["https://x/a"]
    # property defaults to the attributes rpdata holds for the rp_id
    assert captured["model_input"]["property"] == {"beds": "1", "propertyType": "UNIT"}


def test_sqm_items_use_model_quantity_and_cap_to_living_space(monkeypatch):
    items = [
        {"_id": "f1", "name": "Flooring", "defaultRate": 100, "unit": "sqm",
         "defaultQuantity": None, "parentName": None},
        {"_id": "t1", "name": "Tiling", "defaultRate": 50, "unit": "sqm",
         "defaultQuantity": None, "parentName": None},
    ]
    # floorArea 86 − (2 beds·12 + 1 bath·6 + 1 kitchen·8 = 38) → livingSpace 48.
    _patch_upstreams(
        monkeypatch, items=items,
        property={"floorArea": 86, "beds": "2", "baths": "1"},
    )

    model_out = json.dumps({
        "Renovations": [
            {"_id": "f1", "Name": "Flooring", "Quantity": 40, "Unit": "sqm",
             "DefaultRate": 100, "Year": "2018"},
            {"_id": "t1", "Name": "Tiling", "Quantity": 20, "Unit": "sqm",
             "DefaultRate": 50, "Year": "2018"},
        ],
        "Summary Description": "", "Guarantee": "",
    })
    monkeypatch.setattr(estimator, "generate_estimate", lambda *a, **k: model_out)

    out = estimator.build_full_estimate(_req())
    # 40 + 20 = 60 sqm > 48 living space → scale by 48/60 = 0.8.
    assert out["Renovations"][0]["Quantity"] == 32
    assert out["Renovations"][1]["Quantity"] == 16
    assert out["Renovations"][0]["FinalCost"] == "$3,200.00"
    assert out["Renovations"][1]["FinalCost"] == "$800.00"
    assert out["Renovations Total"] == "$4,000.00"
    assert out["GFA"]["livingSpace"] == 48


def test_build_full_estimate_applies_bci_factor(monkeypatch):
    _patch_upstreams(monkeypatch)
    captured = {}

    def fake_factor(state, date):
        captured.update(state=state, date=date)
        return 0.5

    monkeypatch.setattr(estimator, "fetch_bci_factor", fake_factor)
    monkeypatch.setattr(estimator, "generate_estimate", lambda *a, **k: _model_json())

    out = estimator.build_full_estimate(_req(address="1 King St, SYDNEY NSW 2000"))
    # 2 × $1,200 × 0.5 = $1,200; state from the address, year (2018) dated to 1 Jul.
    assert out["Renovations"][0]["FinalCost"] == "$1,200.00"
    assert out["Renovations Total"] == "$1,200.00"
    assert captured == {"state": "NSW", "date": "2018-07-01"}


def test_name_comes_from_library_not_model(monkeypatch):
    # The model returns _id a1 but a mismatched Name; the library name + parent win,
    # so the row can never show under a parent that contradicts its name.
    items = [{"_id": "a1", "name": "Driveway", "defaultRate": 200, "unit": "each",
              "defaultQuantity": 1, "parentName": "Outdoor"}]
    _patch_upstreams(monkeypatch, items=items)
    model_out = json.dumps({
        "Renovations": [{"_id": "a1", "Name": "Kitchen Splashback", "Unit": "each",
                         "DefaultRate": 200, "Year": "2018"}],
        "Summary Description": "", "Guarantee": "",
    })
    monkeypatch.setattr(estimator, "generate_estimate", lambda *a, **k: model_out)

    out = estimator.build_full_estimate(_req())
    assert out["Renovations"][0]["Name"] == "Driveway"
    assert out["Renovations"][0]["parentName"] == "Outdoor"


def test_build_full_estimate_property_override(monkeypatch):
    _patch_upstreams(monkeypatch)
    captured = {}

    def fake_generate(model, prompt, model_input, photos, **kwargs):
        captured.update(model_input=model_input)
        return _model_json(Renovations=[], Totals={"TotalRenovation": 0})

    monkeypatch.setattr(estimator, "generate_estimate", fake_generate)
    # fetch_property would raise if called; a caller override must short-circuit it
    monkeypatch.setattr(
        estimator, "fetch_property", lambda rp_id: pytest.fail("should not fetch")
    )

    override = {"beds": "4", "source": "caller"}
    out = estimator.build_full_estimate(_req(property=override))
    assert captured["model_input"]["property"] == override
    assert out["Property"] == override


def test_preview_estimate_prompt_assembles_template_and_input(monkeypatch):
    _patch_upstreams(monkeypatch)
    monkeypatch.setattr(estimator, "get_base_prompt", lambda _: "TPL")

    out = estimator.preview_estimate_prompt(_req())
    assert out.startswith("TPL")
    assert '"property": {"beds": "1", "propertyType": "UNIT"}' in out
    assert '"renovationItems"' in out


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

    def fake_generate(model, prompt, model_input, photos, **kwargs):
        seen["model"] = model
        return _model_json(Renovations=[], Totals={"TotalRenovation": 0})

    monkeypatch.setattr(estimator, "generate_estimate", fake_generate)
    estimator.build_full_estimate(_req(model="gpt-4o"))
    assert seen["model"] == "gpt-4o"
