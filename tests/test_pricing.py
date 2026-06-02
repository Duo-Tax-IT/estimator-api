from app.pricing import price_items

LIBRARY = {
    "each1": {"_id": "each1", "name": "Split AC", "defaultRate": 1200,
              "unit": "each", "defaultQuantity": 2, "parentName": "Cooling"},
    "sqm1": {"_id": "sqm1", "name": "Flooring", "defaultRate": 100,
             "unit": "sqm", "defaultQuantity": None, "parentName": None},
    "sqm2": {"_id": "sqm2", "name": "Tiling", "defaultRate": 50,
             "unit": "sqm", "defaultQuantity": None, "parentName": None},
}


def test_non_sqm_uses_catalog_quantity_rate_and_cost():
    out = price_items([{"_id": "each1"}], LIBRARY)
    row = out["renovations"][0]
    # quantity, rate, name, parent all come from the catalog — not the input.
    assert row["Quantity"] == 2
    assert row["DefaultRate"] == 1200
    assert row["Name"] == "Split AC"
    assert row["parentName"] == "Cooling"
    assert row["FinalCost"] == 2400
    assert out["total"] == 2400


def test_sqm_uses_area_and_caps_to_living_space():
    out = price_items(
        [{"_id": "sqm1", "area": 40}, {"_id": "sqm2", "area": 20}],
        LIBRARY,
        living_space=48,
    )
    # 40 + 20 = 60 > 48 → scale by 48/60 = 0.8.
    assert out["renovations"][0]["Quantity"] == 32
    assert out["renovations"][1]["Quantity"] == 16
    assert out["total"] == 32 * 100 + 16 * 50


def test_sqm_not_capped_when_within_budget():
    out = price_items([{"_id": "sqm1", "area": 10}], LIBRARY, living_space=48)
    assert out["renovations"][0]["Quantity"] == 10


def test_unknown_id_is_skipped():
    out = price_items([{"_id": "nope"}, {"_id": "each1"}], LIBRARY)
    assert len(out["renovations"]) == 1
    assert out["renovations"][0]["_id"] == "each1"


def test_wrong_id_recovers_by_unique_name():
    # The model mistyped the _id but gave the right name; a unique name recovers it.
    out = price_items([{"_id": "typo", "name": "Split AC"}], LIBRARY)
    assert out["renovations"][0]["_id"] == "each1"
    assert out["renovations"][0]["FinalCost"] == 2400


def test_ambiguous_name_is_not_matched():
    # Two items share the name "Tapware" → an unknown _id can't be safely matched.
    library = {
        "k1": {"_id": "k1", "name": "Tapware", "defaultRate": 400, "unit": "item",
               "defaultQuantity": None, "parentName": "Kitchen"},
        "b1": {"_id": "b1", "name": "Tapware", "defaultRate": 500, "unit": "item",
               "defaultQuantity": None, "parentName": "Bathroom"},
    }
    out = price_items([{"_id": "typo", "name": "Tapware"}], library)
    assert out["renovations"] == []


def test_sqm_without_area_defaults_to_one():
    out = price_items([{"_id": "sqm1"}], LIBRARY)
    assert out["renovations"][0]["Quantity"] == 1


def test_factor_scales_final_cost():
    out = price_items([{"_id": "each1", "factor": 0.5}], LIBRARY)
    row = out["renovations"][0]
    # 2 × 1200 × 0.5 = 1200; quantity/rate themselves are unchanged.
    assert row["Quantity"] == 2
    assert row["DefaultRate"] == 1200
    assert row["Factor"] == 0.5
    assert row["FinalCost"] == 1200
    assert out["total"] == 1200


def test_factor_defaults_to_one():
    out = price_items([{"_id": "each1"}], LIBRARY)
    assert out["renovations"][0]["Factor"] == 1.0
    assert out["renovations"][0]["FinalCost"] == 2400


def test_group_path_is_full_ancestry_for_nesting():
    # Kitchen - House › Joinery › Benchtop (grandchild).
    library = {
        "k": {"_id": "k", "name": "Kitchen - House", "defaultRate": 0, "unit": "item",
              "defaultQuantity": 1, "parentId": None, "parentName": None},
        "j": {"_id": "j", "name": "Joinery", "defaultRate": 0, "unit": "item",
              "defaultQuantity": 1, "parentId": "k", "parentName": "Kitchen - House"},
        "b": {"_id": "b", "name": "Benchtop", "defaultRate": 3000, "unit": "item",
              "defaultQuantity": 1, "parentId": "j", "parentName": "Joinery"},
    }
    out = price_items([{"_id": "b"}], library)
    assert out["renovations"][0]["groupPath"] == ["Kitchen - House", "Joinery"]
    # A top-level item has an empty ancestry.
    assert price_items([{"_id": "each1"}], LIBRARY)["renovations"][0]["groupPath"] == []
