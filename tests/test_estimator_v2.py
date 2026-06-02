import json

import pytest

from app import estimator_v2
from app.errors import ItemsFetchError, ModelError, NoPhotosError
from app.schemas import EstimateRequest, Photo

SAMPLE_ITEMS = [
    {"_id": "a1", "name": "Split System AC", "defaultRate": 1200, "unit": "each",
     "defaultQuantity": 2, "parentName": "Cooling"},
]


def _req(**overrides):
    return EstimateRequest(**{"rpId": "RP1", **overrides})


def _patch_upstreams(monkeypatch, items=SAMPLE_ITEMS, photos=None, property=None):
    if photos is None:
        photos = [Photo(url="https://x/a", date="2024-01-01")]
    if property is None:
        property = {"beds": "1", "propertyType": "UNIT"}
    monkeypatch.setattr(estimator_v2, "fetch_renovation_items", lambda: items)
    monkeypatch.setattr(estimator_v2, "fetch_photos", lambda rp_id: photos)
    monkeypatch.setattr(estimator_v2, "fetch_property", lambda rp_id: property)


def _patch_stages(monkeypatch, observations, candidates):
    monkeypatch.setattr(estimator_v2, "observe_photos", lambda *a, **k: (json.dumps(observations), {}))
    monkeypatch.setattr(estimator_v2, "match_candidates", lambda *a, **k: (json.dumps(candidates), {}))


def test_v2_shape_matches_v1_prices_from_library_and_keeps_stages(monkeypatch):
    _patch_upstreams(monkeypatch)
    observations = {"photoObservations": [{"photoIndex": 0, "roomType": "living"}]}
    candidates = {
        "validatedCandidates": [
            {"_id": "a1", "name": "Split System AC", "unit": "each",
             "estimatedYear": "2018", "roomType": "living", "confidence": "high",
             "evidence": [], "areaForTool": None},
        ],
        "rejectedCandidates": [{"candidateName": "Pool", "reason": "landscaping"}],
        "summary": "Detected split system AC.",
    }
    _patch_stages(monkeypatch, observations, candidates)

    out = estimator_v2.build_estimate_v2(_req())

    # Quantity/rate/cost are read from the catalog (defaultQty 2), not the model.
    assert out["Renovations"][0]["Quantity"] == 2
    assert out["Renovations"][0]["DefaultRate"] == "$1,200.00"
    assert out["Renovations"][0]["FinalCost"] == "$2,400.00"
    assert out["Renovations Total"] == "$2,400.00"
    assert out["Renovations"][0]["Year"] == "2018"
    assert out["Renovations"][0]["parentName"] == "Cooling"
    assert out["Summary Description"] == "Detected split system AC."
    assert out["Disclaimer"].startswith("This assessment is based solely")
    assert out["Property"] == {"beds": "1", "propertyType": "UNIT"}
    # Per-stage debug payload is carried through.
    assert out["Stages"]["observations"] == observations
    assert out["Stages"]["candidates"]["validatedCandidates"] == candidates["validatedCandidates"]
    assert out["Stages"]["candidates"]["rejectedCandidates"] == candidates["rejectedCandidates"]
    assert out["Stages"]["toolInput"][0] == {
        "_id": "a1", "name": "Split System AC", "area": None, "factor": 1.0
    }


def test_v2_stages_record_bci_audit(monkeypatch):
    from app import estimator  # _bci_factor calls estimator.fetch_bci_factor
    _patch_upstreams(monkeypatch)
    monkeypatch.setattr(estimator, "fetch_bci_factor", lambda state, date: 0.5)
    candidates = {
        "validatedCandidates": [
            {"_id": "a1", "name": "Split System AC", "unit": "each",
             "estimatedYear": "2018", "areaForTool": None, "evidence": []},
        ],
        "rejectedCandidates": [], "summary": "",
    }
    _patch_stages(monkeypatch, {"photoObservations": []}, candidates)

    out = estimator_v2.build_estimate_v2(_req(address="1 King St, SYDNEY NSW 2000"))
    # The state and the per-year factor that scaled the cost are auditable.
    assert out["Stages"]["bci"] == {"state": "NSW", "factors": {"2018": 0.5}}
    # …and the same factor rides each priced row + tool input.
    assert out["Stages"]["toolInput"][0]["factor"] == 0.5
    assert out["Renovations"][0]["Factor"] == 0.5
    assert out["Renovations"][0]["FinalCost"] == "$1,200.00"  # 2 × $1,200 × 0.5


def test_v2_room_scaling_doubles_bathroom_total_when_enabled(monkeypatch):
    items = [
        {"_id": "b", "name": "Bathroom", "defaultRate": 0, "unit": "item",
         "defaultQuantity": 1, "parentId": None, "parentName": None},
        {"_id": "t", "name": "Toilet", "defaultRate": 1000, "unit": "item",
         "defaultQuantity": 1, "parentId": "b", "parentName": "Bathroom"},
    ]
    _patch_upstreams(monkeypatch, items=items,
                     property={"baths": "2", "propertyType": "HOUSE"})
    candidates = {
        "validatedCandidates": [
            {"_id": "b", "name": "Bathroom", "unit": "item", "estimatedYear": "2021",
             "areaForTool": None, "evidence": []},
        ],
        "rejectedCandidates": [], "summary": "",
    }
    _patch_stages(monkeypatch, {"photoObservations": []}, candidates)

    out = estimator_v2.build_estimate_v2(_req(config={"assumeAllRoomsRenovated": True}))
    # One bathroom itemised (Toilet $1,000, Count 2); the total reflects ×2 baths.
    assert out["Renovations"][0]["Count"] == 2
    assert out["Renovations Total"] == "$2,000.00"
    assert out["Stages"]["roomScaling"] == {
        "manual": {}, "auto": True, "applied": {"Bathroom": 2},
    }


def test_v2_manual_room_scale_doubles_total(monkeypatch):
    items = [
        {"_id": "b", "name": "Bathroom", "defaultRate": 0, "unit": "item",
         "defaultQuantity": 1, "parentId": None, "parentName": None},
        {"_id": "t", "name": "Toilet", "defaultRate": 1000, "unit": "item",
         "defaultQuantity": 1, "parentId": "b", "parentName": "Bathroom"},
    ]
    _patch_upstreams(monkeypatch, items=items, property={"propertyType": "HOUSE"})
    candidates = {
        "validatedCandidates": [
            {"_id": "b", "name": "Bathroom", "unit": "item", "estimatedYear": "2021",
             "areaForTool": None, "evidence": []},
        ],
        "rejectedCandidates": [], "summary": "",
    }
    _patch_stages(monkeypatch, {"photoObservations": []}, candidates)

    # Manual ×3, independent of the property's (unknown) bathroom count.
    out = estimator_v2.build_estimate_v2(_req(config={"roomScale": {"bathroom": 3}}))
    assert out["Renovations"][0]["Count"] == 3
    assert out["Renovations Total"] == "$3,000.00"
    assert out["Stages"]["roomScaling"]["manual"] == {"bathroom": 3}


def test_v2_sqm_areaForTool_maps_to_area_and_caps_to_living_space(monkeypatch):
    items = [{"_id": "f1", "name": "Flooring", "defaultRate": 100, "unit": "sqm",
              "defaultQuantity": None, "parentName": None}]
    # floorArea 86 − (2 beds·12 + 1 bath·6 + 1 kitchen·8 = 38) → livingSpace 48.
    _patch_upstreams(monkeypatch, items=items,
                     property={"floorArea": 86, "beds": "2", "baths": "1"})
    candidates = {
        "validatedCandidates": [
            {"_id": "f1", "name": "Flooring", "unit": "sqm",
             "estimatedYear": "2018", "areaForTool": 60, "evidence": []},
        ],
        "rejectedCandidates": [], "summary": "",
    }
    _patch_stages(monkeypatch, {"photoObservations": []}, candidates)

    out = estimator_v2.build_estimate_v2(_req())
    # areaForTool 60 > livingSpace 48 → scaled to 48; cost 48 × 100.
    assert out["Renovations"][0]["Quantity"] == 48
    assert out["Renovations"][0]["FinalCost"] == "$4,800.00"
    assert out["GFA"]["livingSpace"] == 48
    assert out["Stages"]["toolInput"][0]["area"] == 60


def test_v2_forwards_observations_into_match_payload_and_splits_owner(monkeypatch):
    _patch_upstreams(monkeypatch)
    observations = {"photoObservations": [{"photoIndex": 0}]}
    captured = {}

    monkeypatch.setattr(estimator_v2, "observe_photos", lambda *a, **k: (json.dumps(observations), {}))

    def fake_match(model, prompt, payload, **kwargs):
        captured["payload"] = payload
        return json.dumps({
            "validatedCandidates": [
                {"_id": "a1", "name": "Split System AC", "unit": "each",
                 "estimatedYear": "2000", "areaForTool": None, "evidence": []},
            ],
            "rejectedCandidates": [], "summary": "",
        }), {}

    monkeypatch.setattr(estimator_v2, "match_candidates", fake_match)

    out = estimator_v2.build_estimate_v2(_req(settlementDate="2010-01-01"))
    # Step 1 output is fed into Step 2's payload, alongside the trimmed catalog.
    assert captured["payload"]["photoObservations"] == observations["photoObservations"]
    assert captured["payload"]["renovationItems"][0]["_id"] == "a1"
    # Year 2000 predates settlement 2010 → previous owner.
    assert out["Renovations"][0]["Owner"] == "Previous Owner"
    assert out["Previous Owner Total"] == "$2,400.00"
    assert out["Current Owner Total"] == "$0.00"


# Nested catalog: Room(0) -> [ItemA(100), Sub(0) -> ItemB(200)].
NESTED_ITEMS = [
    {"_id": "p", "name": "Room", "defaultRate": 0, "unit": "item",
     "defaultQuantity": 1, "parentId": None, "parentName": None},
    {"_id": "a", "name": "ItemA", "defaultRate": 100, "unit": "item",
     "defaultQuantity": 1, "parentId": "p", "parentName": "Room"},
    {"_id": "s", "name": "Sub", "defaultRate": 0, "unit": "item",
     "defaultQuantity": 1, "parentId": "p", "parentName": "Room"},
    {"_id": "b", "name": "ItemB", "defaultRate": 200, "unit": "item",
     "defaultQuantity": 1, "parentId": "s", "parentName": "Sub"},
]


def test_v2_full_room_match_expands_to_leaf_children(monkeypatch):
    _patch_upstreams(monkeypatch, items=NESTED_ITEMS)
    candidates = {
        "validatedCandidates": [
            {"_id": "p", "name": "Room", "unit": "item", "estimatedYear": "2021",
             "areaForTool": None, "evidence": []},
        ],
        "rejectedCandidates": [], "summary": "",
    }
    _patch_stages(monkeypatch, {"photoObservations": []}, candidates)

    out = estimator_v2.build_estimate_v2(_req())
    # The 0-rate parent is replaced by its descendant leaves (recursing through Sub).
    names = {r["Name"] for r in out["Renovations"]}
    assert names == {"ItemA", "ItemB"}
    assert "Room" not in names
    assert out["Renovations Total"] == "$300.00"
    # Leaves inherit the parent candidate's year.
    assert all(r["Year"] == "2021" for r in out["Renovations"])


def test_v2_parent_plus_child_match_does_not_double_count(monkeypatch):
    _patch_upstreams(monkeypatch, items=NESTED_ITEMS)
    candidates = {
        "validatedCandidates": [
            {"_id": "p", "name": "Room", "unit": "item", "estimatedYear": "2021",
             "areaForTool": None, "evidence": []},
            {"_id": "a", "name": "ItemA", "unit": "item", "estimatedYear": "2021",
             "areaForTool": None, "evidence": []},
        ],
        "rejectedCandidates": [], "summary": "",
    }
    _patch_stages(monkeypatch, {"photoObservations": []}, candidates)

    out = estimator_v2.build_estimate_v2(_req())
    # ItemA appears once despite being both expanded and matched directly.
    assert [r["Name"] for r in out["Renovations"]].count("ItemA") == 1
    assert out["Renovations Total"] == "$300.00"


def test_v2_prompt_preview_includes_both_stage_prompts(monkeypatch):
    _patch_upstreams(monkeypatch)
    monkeypatch.setattr(estimator_v2, "get_base_prompt",
                        lambda f: "OBS_TPL" if "observe" in f else "CAND_TPL")
    out = estimator_v2.preview_estimate_prompt_v2(_req())
    assert "STEP 1 — OBSERVATION" in out and "OBS_TPL" in out
    assert "STEP 2 — CANDIDATE MATCHING" in out and "CAND_TPL" in out
    # Step 2's input payload is shown; observations are a runtime placeholder.
    assert '"renovationItems"' in out
    assert "filled at runtime" in out


def test_v2_bad_observation_json_raises(monkeypatch):
    _patch_upstreams(monkeypatch)
    monkeypatch.setattr(estimator_v2, "observe_photos", lambda *a, **k: ("not json", {}))
    monkeypatch.setattr(estimator_v2, "match_candidates", lambda *a, **k: ("{}", {}))
    with pytest.raises(ModelError):
        estimator_v2.build_estimate_v2(_req())


def test_v2_bad_candidate_json_raises(monkeypatch):
    _patch_upstreams(monkeypatch)
    monkeypatch.setattr(estimator_v2, "observe_photos",
                        lambda *a, **k: (json.dumps({"photoObservations": []}), {}))
    monkeypatch.setattr(estimator_v2, "match_candidates", lambda *a, **k: ("not json", {}))
    with pytest.raises(ModelError):
        estimator_v2.build_estimate_v2(_req())


def test_v2_no_items_raises(monkeypatch):
    _patch_upstreams(monkeypatch, items=[])
    with pytest.raises(ItemsFetchError):
        estimator_v2.build_estimate_v2(_req())


def test_v2_no_photos_raises(monkeypatch):
    _patch_upstreams(monkeypatch, photos=[])
    with pytest.raises(NoPhotosError):
        estimator_v2.build_estimate_v2(_req())
