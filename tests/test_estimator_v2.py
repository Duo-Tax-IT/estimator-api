import json

import pytest

from app import estimator_v2
from app.errors import ItemsFetchError, MissingBuildYearError, ModelError, NoPhotosError
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
        property = {"beds": "1", "propertyType": "UNIT", "yearBuilt": "1990"}
    # Build fetches via estimator_v2.context; the prompt preview via estimator_v2.preview.
    for mod in (estimator_v2.context, estimator_v2.preview):
        monkeypatch.setattr(mod, "fetch_renovation_items", lambda: items)
        monkeypatch.setattr(mod, "fetch_property", lambda rp_id: property)
    monkeypatch.setattr(estimator_v2.context, "fetch_photos", lambda rp_id: photos)
    # Dedup downloads images to hash them; keep the pipeline tests offline.
    monkeypatch.setattr(estimator_v2.context, "dedup_photos", lambda photos: photos)


def _patch_stages(monkeypatch, observations, candidates, era=None, support=None):
    era = era if era is not None else {"eraAnalysis": []}
    support = support if support is not None else {"renovationSupportFindings": []}
    # Each model call now lives in its own step module under estimator_v2.steps.
    monkeypatch.setattr(estimator_v2.steps.observe, "observe_photos", lambda *a, **k: (json.dumps(observations), {}, [], []))
    monkeypatch.setattr(estimator_v2.steps.era, "analyze_era", lambda *a, **k: (json.dumps(era), {}))
    monkeypatch.setattr(estimator_v2.steps.support, "assess_support", lambda *a, **k: (json.dumps(support), {}))
    monkeypatch.setattr(estimator_v2.steps.match, "match_candidates", lambda *a, **k: (json.dumps(candidates), {}))


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
    assert out["Property"] == {"beds": "1", "propertyType": "UNIT", "yearBuilt": "1990"}
    # Per-stage debug payload is carried through.
    assert out["Stages"]["observations"] == observations
    assert out["Stages"]["eraAnalysis"] == {"eraAnalysis": []}
    assert out["Stages"]["renovationSupport"] == {"renovationSupportFindings": []}
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


def test_v2_sqm_areaForTool_maps_to_area_and_caps_to_living_space(monkeypatch):
    items = [{"_id": "f1", "name": "Flooring", "defaultRate": 100, "unit": "sqm",
              "defaultQuantity": None, "parentName": None}]
    # floorArea 86 − (2 beds·12 + 1 bath·6 + 1 kitchen·8 = 38) → livingSpace 48.
    _patch_upstreams(monkeypatch, items=items,
                     property={"floorArea": 86, "beds": "2", "baths": "1", "yearBuilt": "1990"})
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


def test_v2_only_supported_findings_reach_match_payload_and_splits_owner(monkeypatch):
    _patch_upstreams(monkeypatch)
    support = {"renovationSupportFindings": [
        {"observedItem": "split system", "roomType": "living",
         "estimatedRenovationYear": "2000", "shouldProceedToCatalogMatch": True},
        {"observedItem": "old tiles", "roomType": "bathroom",
         "shouldProceedToCatalogMatch": False},
    ]}
    captured = {}

    monkeypatch.setattr(estimator_v2.steps.observe, "observe_photos", lambda *a, **k: (json.dumps({"photoObservations": []}), {}, [], []))
    monkeypatch.setattr(estimator_v2.steps.era, "analyze_era", lambda *a, **k: (json.dumps({"eraAnalysis": []}), {}))
    monkeypatch.setattr(estimator_v2.steps.support, "assess_support", lambda *a, **k: (json.dumps(support), {}))

    def fake_match(model, prompt, payload, **kwargs):
        captured["payload"] = payload
        return json.dumps({
            "validatedCandidates": [
                {"_id": "a1", "name": "Split System AC", "unit": "each",
                 "estimatedYear": "2000", "areaForTool": None, "evidence": []},
            ],
            "rejectedCandidates": [], "summary": "",
        }), {}

    monkeypatch.setattr(estimator_v2.steps.match, "match_candidates", fake_match)

    out = estimator_v2.build_estimate_v2(_req(settlementDate="2010-01-01"))
    # The Python gate drops shouldProceedToCatalogMatch=false; only the supported
    # finding reaches Step 2, alongside the trimmed catalog.
    assert [f["observedItem"] for f in captured["payload"]["renovationSupportFindings"]] == ["split system"]
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

    def fake_prompt(f):
        if "observe" in f:
            return "OBS_TPL"
        if "era" in f:
            return "ERA_TPL"
        if "support" in f:
            return "SUP_TPL"
        return "CAND_TPL"

    monkeypatch.setattr(estimator_v2.preview, "get_base_prompt", fake_prompt)
    out = estimator_v2.preview_estimate_prompt_v2(_req())
    assert "STEP 1 — OBSERVATION" in out and "OBS_TPL" in out
    assert "STEP 1b — ERA ANALYSIS" in out and "ERA_TPL" in out
    assert "STEP 1.5 — RENOVATION SUPPORT" in out and "SUP_TPL" in out
    assert "STEP 2 — CANDIDATE MATCHING" in out and "CAND_TPL" in out
    # Step 2's input payload is shown; observations are a runtime placeholder.
    assert '"renovationItems"' in out
    assert "filled at runtime" in out


def test_v2_bad_observation_json_raises(monkeypatch):
    _patch_upstreams(monkeypatch)
    monkeypatch.setattr(estimator_v2.steps.observe, "observe_photos", lambda *a, **k: ("not json", {}, [], []))
    monkeypatch.setattr(estimator_v2.steps.era, "analyze_era", lambda *a, **k: (json.dumps({"eraAnalysis": []}), {}))
    monkeypatch.setattr(estimator_v2.steps.support, "assess_support", lambda *a, **k: (json.dumps({"renovationSupportFindings": []}), {}))
    monkeypatch.setattr(estimator_v2.steps.match, "match_candidates", lambda *a, **k: ("{}", {}))
    with pytest.raises(ModelError):
        estimator_v2.build_estimate_v2(_req())


def test_v2_bad_candidate_json_raises(monkeypatch):
    _patch_upstreams(monkeypatch)
    monkeypatch.setattr(estimator_v2.steps.observe, "observe_photos",
                        lambda *a, **k: (json.dumps({"photoObservations": []}), {}, [], []))
    monkeypatch.setattr(estimator_v2.steps.era, "analyze_era", lambda *a, **k: (json.dumps({"eraAnalysis": []}), {}))
    monkeypatch.setattr(estimator_v2.steps.support, "assess_support", lambda *a, **k: (json.dumps({"renovationSupportFindings": []}), {}))
    monkeypatch.setattr(estimator_v2.steps.match, "match_candidates", lambda *a, **k: ("not json", {}))
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


def test_v2_requires_build_year_when_context_and_request_lack_it(monkeypatch):
    # Property has no yearBuilt and no buildYear supplied -> hard error.
    _patch_upstreams(monkeypatch, property={"propertyType": "UNIT"})
    with pytest.raises(MissingBuildYearError):
        estimator_v2.build_estimate_v2(_req())


def test_step_context_surfaces_missing_build_year_without_erroring(monkeypatch):
    # Step 0 is the diagnostic fetch: it must NOT require a build year.
    _patch_upstreams(monkeypatch, property={"propertyType": "UNIT"})
    out = estimator_v2.step_context(_req())
    assert out["property"] == {"propertyType": "UNIT"}


def test_step_observe_requires_build_year(monkeypatch):
    # The gate kicks in from observe on.
    _patch_upstreams(monkeypatch, property={"propertyType": "UNIT"})
    with pytest.raises(MissingBuildYearError):
        estimator_v2.step_observe(_req())


def test_photos_override_is_used_and_skips_fetch(monkeypatch):
    # Dev/testing: a request's `photos` are sent as-is; rpdata fetch is never hit.
    ctx_mod = estimator_v2.context
    monkeypatch.setattr(ctx_mod, "fetch_renovation_items", lambda: SAMPLE_ITEMS)
    monkeypatch.setattr(ctx_mod, "fetch_photos",
                        lambda rp_id: pytest.fail("fetch_photos should not be called"))
    req = _req(property={"propertyType": "UNIT", "yearBuilt": "1990"},
              photos=[{"url": "https://x/keep", "date": None}])
    ctx = ctx_mod.fetch_v2_context(req)
    assert [p.url for p in ctx["photos"]] == ["https://x/keep"]


def test_v2_build_year_fills_property_when_context_missing_it(monkeypatch):
    # buildYear fills the missing yearBuilt; the year-guard then uses it, dropping
    # the 2000 candidate as original build (estimatedYear <= yearBuilt 2010).
    _patch_upstreams(monkeypatch, property={"propertyType": "UNIT"})
    candidates = {"validatedCandidates": [
        {"_id": "a1", "name": "Split System AC", "unit": "each",
         "estimatedYear": "2000", "areaForTool": None, "evidence": []},
    ], "rejectedCandidates": [], "summary": ""}
    _patch_stages(monkeypatch, {"photoObservations": []}, candidates)

    out = estimator_v2.build_estimate_v2(_req(buildYear=2010))
    assert out["Property"]["yearBuilt"] == 2010
    assert out["Renovations"] == []  # dropped by the year-guard using the filled year


# ── Internal-repaint assumption (QS convention, on by default) ──
_PAINT_LIB = {"p": {"_id": "p", "name": "Painting - Internal", "defaultRate": 55,
                    "unit": "sqm", "parentId": None, "parentName": None}}
_FRESH_PAINT = {"photoObservations": [{"roomType": "living", "condition": "clean"}]}
_GFA = {"livingSpace": 40, "bedroom": 0, "bathroom": 0, "kitchen": 0}


def test_internal_paint_applies_by_default_when_conditions_met():
    # No config: the repaint assumption fires (old property + sound paint seen),
    # sized from the gfa living-space area.
    row, decision = estimator_v2._internal_paint_row(
        [], _FRESH_PAINT, {"yearBuilt": "2000"}, {}, _GFA, _PAINT_LIB
    )
    assert decision["applied"] is True
    assert row["_id"] == "p" and row["area"] == 40.0


def test_internal_paint_can_still_be_disabled_explicitly():
    _, decision = estimator_v2._internal_paint_row(
        [], _FRESH_PAINT, {"yearBuilt": "2000"}, {"assumeInternalRepaint": False}, _GFA, _PAINT_LIB
    )
    assert decision == {"applied": False, "reason": "disabled"}
