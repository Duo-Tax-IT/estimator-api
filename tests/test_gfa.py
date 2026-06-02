from app.gfa import calculate_gfa


def test_breaks_gfa_into_rooms_and_living_space():
    # 2 bed (24) + 1 bath (6) + 1 kitchen (8) = 38; 100 - 38 = 62 living space.
    assert calculate_gfa(100, bedrooms=2, bathrooms=1, kitchens=1) == {
        "bedroom": 24,
        "bathroom": 6,
        "kitchen": 8,
        "livingSpace": 62,
    }


def test_no_rooms_is_all_living_space():
    assert calculate_gfa(80) == {
        "bedroom": 0,
        "bathroom": 0,
        "kitchen": 0,
        "livingSpace": 80,
    }
