import json

import pytest

from app import estimator_v2, estimator_v3
from app.errors import ModelError
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
    # v3 reuses the v2 context fetch + pricing; only the vision call differs.
    monkeypatch.setattr(estimator_v2.context, "fetch_renovation_items", lambda: items)
    monkeypatch.setattr(estimator_v2.context, "fetch_property", lambda rp_id: property)
    monkeypatch.setattr(estimator_v2.context, "fetch_photos", lambda rp_id: photos)
    monkeypatch.setattr(estimator_v2.context, "dedup_photos", lambda photos: photos)
    monkeypatch.setattr(estimator_v3, "prepare_photos", lambda photos: [
        {"photoIndex": i, "data_url": "d", "url": p.url, "date": p.date, "prediction": None}
        for i, p in enumerate(photos)
    ])


def _patch_stages(monkeypatch, analysis, candidates, support=None, sent=None):
    """One fused vision call (analyze_photos) replaces v2's observe/era/structure;
    support + match are the reused v2 text steps."""
    support = support if support is not None else {"renovationSupportFindings": []}
    monkeypatch.setattr(estimator_v3.analyze, "analyze_photos",
                        lambda *a, **k: (json.dumps(analysis), {}, [], sent or []))
    monkeypatch.setattr(estimator_v2.steps.support, "assess_support",
                        lambda *a, **k: (json.dumps(support), {}))
    monkeypatch.setattr(estimator_v2.steps.match, "match_candidates",
                        lambda *a, **k: (json.dumps(candidates), {}))


def test_v3_shape_matches_v1_and_splits_master_json_into_v2_stages(monkeypatch):
    _patch_upstreams(monkeypatch)
    analysis = {
        "photoObservations": [{"photoIndex": 0, "roomType": "living"}],
        "eraAnalysis": [{"photoIndex": 0, "element": "benchtop"}],
        "structureAnalysis": {},
        "propertyType": {"detected": "unit", "confidence": "high", "evidence": ["lobby"]},
    }
    candidates = {
        "validatedCandidates": [
            {"_id": "a1", "name": "Split System AC", "unit": "each",
             "estimatedYear": "2018", "roomType": "living", "confidence": "high",
             "evidence": [], "areaForTool": None},
        ],
        "rejectedCandidates": [{"candidateName": "Pool", "reason": "landscaping"}],
        "summary": "Detected split system AC.",
    }
    _patch_stages(monkeypatch, analysis, candidates)

    out = estimator_v3.build_estimate_v3(_req())

    # Priced from the catalog, same as v1/v2.
    assert out["Renovations"][0]["FinalCost"] == "$2,400.00"
    assert out["Renovations Total"] == "$2,400.00"
    assert out["Summary Description"] == "Detected split system AC."
    # The master JSON is split back into the SAME Stages keys v2 emits.
    assert out["Stages"]["observations"] == {"photoObservations": analysis["photoObservations"]}
    assert out["Stages"]["eraAnalysis"] == {"eraAnalysis": analysis["eraAnalysis"]}
    assert out["Stages"]["structuralChange"] == {}
    # The model's own dwelling-type read is surfaced for audit vs rpdata.
    assert out["Stages"]["propertyType"]["detected"] == "unit"
    assert out["Stages"]["candidates"]["validatedCandidates"] == candidates["validatedCandidates"]
    assert out["Stages"]["candidates"]["rejectedCandidates"] == candidates["rejectedCandidates"]
    assert out["Meta"]["pipeline"] == "v3"
    assert "analyzePromptHash" in out["Meta"]


def test_v3_structure_analysis_adds_priced_house_extension_row(monkeypatch):
    items = [{"_id": "h", "name": "House Extension", "defaultRate": 2675,
              "unit": "sqm", "defaultQuantity": None, "parentName": None}]
    # livingSpace = 86 − (2·12 + 1·6 + kitchen 8) = 48.
    _patch_upstreams(monkeypatch, items=items,
                     property={"floorArea": 86, "beds": "2", "baths": "1", "yearBuilt": "1990"})
    analysis = {
        "photoObservations": [],
        "eraAnalysis": [],
        # The structure section of the single pass drives the deterministic row —
        # no separate structure call, no exterior-pair gate (the model decides).
        "structureAnalysis": {"secondStoreyAdded": True, "oldStoreys": 1, "newStoreys": 2,
                              "estimatedAddedAreaSqm": 70, "estimatedYear": "2018",
                              "confidence": "high", "evidence": ["second storey in newer photo"]},
    }
    candidates = {"validatedCandidates": [], "rejectedCandidates": [], "summary": ""}
    _patch_stages(monkeypatch, analysis, candidates)

    out = estimator_v3.build_estimate_v3(_req())
    ext = [r for r in out["Renovations"] if r["Name"] == "House Extension"]
    assert len(ext) == 1
    # capExempt: full 70 m² × 2675, not scaled to livingSpace 48.
    assert ext[0]["Quantity"] == 70
    assert ext[0]["FinalCost"] == "$187,250.00"
    assert ext[0]["Year"] == "2018"
    assert out["Stages"]["extensionAssumption"]["applied"] is True
    assert out["Stages"]["structuralChange"]["secondStoreyAdded"] is True


def test_v3_gut_reno_resurfaces_year_guarded_candidate_as_needs_review(monkeypatch):
    # Built 1990; a candidate dated 1990 is normally dropped by the year-guard as
    # "original build". But a gut reno can reset the recorded build year, so when
    # analyze flags gutRenovation the dropped match resurfaces unpriced for review.
    _patch_upstreams(monkeypatch)
    analysis = {
        "photoObservations": [], "eraAnalysis": [], "structureAnalysis": {},
        "gutRenovation": {"detected": True, "estimatedYear": "1990",
                          "confidence": "high", "evidence": ["1970s brick shell, all-new interior"]},
    }
    candidates = {
        "validatedCandidates": [
            {"_id": "a1", "name": "Split System AC", "unit": "each",
             "estimatedYear": "1990", "roomType": "living", "confidence": "high",
             "evidence": [], "areaForTool": None},
        ],
        "rejectedCandidates": [], "summary": "",
    }
    _patch_stages(monkeypatch, analysis, candidates)

    out = estimator_v3.build_estimate_v3(_req())
    review = [r for r in out["Renovations"] if r.get("needsReview")]
    assert len(review) == 1
    assert review[0]["Name"] == "Split System AC" and review[0]["Year"] == "1990"
    assert "FinalCost" not in review[0]          # unpriced — manual judgement only
    assert out["Renovations Total"] == "$0.00"   # never auto-priced on a gut reno
    assert out["Stages"]["gutRenovation"]["detected"] is True


def test_v3_support_and_match_run_on_cheap_text_model(monkeypatch):
    _patch_upstreams(monkeypatch)
    seen = {}
    monkeypatch.setattr(estimator_v3.analyze, "analyze_photos",
                        lambda *a, **k: (json.dumps({"photoObservations": [], "eraAnalysis": []}), {}, [], []))

    def cap_support(model, *a, **k):
        seen["support"] = model
        return json.dumps({"renovationSupportFindings": []}), {}

    def cap_match(model, *a, **k):
        seen["match"] = model
        return json.dumps({"validatedCandidates": [], "rejectedCandidates": [], "summary": ""}), {}

    monkeypatch.setattr(estimator_v2.steps.support, "assess_support", cap_support)
    monkeypatch.setattr(estimator_v2.steps.match, "match_candidates", cap_match)

    estimator_v3.build_estimate_v3(_req(model="vision-model", textModel="cheap-text"))
    # The text-only steps run on the cheap text model, not the vision model.
    assert seen["support"] == "cheap-text"
    assert seen["match"] == "cheap-text"


def test_v3_text_model_falls_back_to_vision_model_when_unset(monkeypatch):
    _patch_upstreams(monkeypatch)
    seen = {}
    monkeypatch.setattr(estimator_v3.analyze, "analyze_photos",
                        lambda *a, **k: (json.dumps({"photoObservations": [], "eraAnalysis": []}), {}, [], []))

    def cap_match(model, *a, **k):
        seen["match"] = model
        return json.dumps({"validatedCandidates": [], "rejectedCandidates": [], "summary": ""}), {}

    monkeypatch.setattr(estimator_v2.steps.support, "assess_support",
                        lambda *a, **k: (json.dumps({"renovationSupportFindings": []}), {}))
    monkeypatch.setattr(estimator_v2.steps.match, "match_candidates", cap_match)

    # No textModel and default_text_model is "" → reuse the vision model.
    estimator_v3.build_estimate_v3(_req(model="vision-model"))
    assert seen["match"] == "vision-model"


def test_v3_bad_analysis_json_raises(monkeypatch):
    _patch_upstreams(monkeypatch)
    monkeypatch.setattr(estimator_v3.analyze, "analyze_photos", lambda *a, **k: ("not json", {}, [], []))
    monkeypatch.setattr(estimator_v2.steps.support, "assess_support",
                        lambda *a, **k: (json.dumps({"renovationSupportFindings": []}), {}))
    monkeypatch.setattr(estimator_v2.steps.match, "match_candidates", lambda *a, **k: ("{}", {}))
    with pytest.raises(ModelError):
        estimator_v3.build_estimate_v3(_req())


def test_v3_step_analyze_returns_master_json(monkeypatch):
    _patch_upstreams(monkeypatch)
    analysis = {"photoObservations": [{"photoIndex": 0}], "eraAnalysis": [], "structureAnalysis": {}}
    monkeypatch.setattr(estimator_v3.analyze, "analyze_photos",
                        lambda *a, **k: (json.dumps(analysis), {}, [{"photoIndex": 0}], [{"photoIndex": 0}]))
    out = estimator_v3.step_analyze(_req())
    assert out["analysis"] == analysis
    assert out["photos"] == [{"photoIndex": 0}]
