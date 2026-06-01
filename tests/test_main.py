from fastapi.testclient import TestClient

from app import main
from app.errors import ItemsFetchError, NoPhotosError, RpDataFetchError
from app.main import app

client = TestClient(app)

VALID_BODY = {"rpId": "RP1"}


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_index_serves_frontend():
    r = client.get("/")
    assert r.status_code == 200
    assert "Renovation Estimator" in r.text


def test_search_returns_suggestions(monkeypatch):
    suggestions = [{"suggestion": "1 Fullarton Street", "suggestionId": 9236365}]
    monkeypatch.setattr(main, "search_addresses", lambda q: suggestions)
    r = client.get("/search", params={"q": "1 Fullarton"})
    assert r.status_code == 200
    assert r.json() == {"suggestions": suggestions}


def test_search_requires_query():
    assert client.get("/search").status_code == 422


def test_search_upstream_error_maps_to_502(monkeypatch):
    def boom(q):
        raise RpDataFetchError("calc.duo.tax unreachable")

    monkeypatch.setattr(main, "search_addresses", boom)
    assert client.get("/search", params={"q": "x"}).status_code == 502


def test_photos_returns_mapped_photos(monkeypatch):
    from app.schemas import Photo

    monkeypatch.setattr(
        main, "fetch_photos", lambda rp_id: [Photo(url="https://x/a", date="2024-01-01")]
    )
    r = client.get("/photos", params={"rpId": "RP1"})
    assert r.status_code == 200
    assert r.json() == {"photos": [{"url": "https://x/a", "date": "2024-01-01"}]}


def test_photos_requires_rpid():
    assert client.get("/photos").status_code == 422


def test_photos_upstream_error_maps_to_502(monkeypatch):
    def boom(rp_id):
        raise RpDataFetchError("calc.duo.tax unreachable")

    monkeypatch.setattr(main, "fetch_photos", boom)
    assert client.get("/photos", params={"rpId": "RP1"}).status_code == 502


def test_estimate_requires_rpid():
    assert client.post("/estimate", json={}).status_code == 422


def test_estimate_success(monkeypatch):
    monkeypatch.setattr(
        main, "build_full_estimate",
        lambda req: {"Renovations": [], "Renovations Total": "$0.00"},
    )
    r = client.post("/estimate", json=VALID_BODY)
    assert r.status_code == 200
    assert r.json()["Renovations Total"] == "$0.00"


def test_estimate_ignores_stray_fields(monkeypatch):
    # `photos`/`renovationItems` are no longer schema fields; extras are ignored.
    monkeypatch.setattr(main, "build_full_estimate", lambda req: {"ok": True})
    body = dict(VALID_BODY, photos=[{"url": "https://x/a"}], renovationItems=[{"_id": "x"}])
    assert client.post("/estimate", json=body).status_code == 200


def test_estimate_no_photos_maps_to_422(monkeypatch):
    def boom(req):
        raise NoPhotosError("No usable photos found for rp_id RP1")

    monkeypatch.setattr(main, "build_full_estimate", boom)
    r = client.post("/estimate", json=VALID_BODY)
    assert r.status_code == 422
    assert "No usable photos" in r.json()["detail"]


def test_estimate_items_error_maps_to_502(monkeypatch):
    def boom(req):
        raise ItemsFetchError("megamind unreachable")

    monkeypatch.setattr(main, "build_full_estimate", boom)
    assert client.post("/estimate", json=VALID_BODY).status_code == 502


def test_estimate_photos_error_maps_to_502(monkeypatch):
    def boom(req):
        raise RpDataFetchError("calc.duo.tax unreachable")

    monkeypatch.setattr(main, "build_full_estimate", boom)
    assert client.post("/estimate", json=VALID_BODY).status_code == 502


def test_auth_enforced_when_api_key_set(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("API_KEY", "s3cret")
    get_settings.cache_clear()
    monkeypatch.setattr(main, "build_full_estimate", lambda req: {"ok": True})
    try:
        assert client.post("/estimate", json=VALID_BODY).status_code == 401
        assert client.post(
            "/estimate", json=VALID_BODY, headers={"secret-sauce": "nope"}
        ).status_code == 401
        assert client.post(
            "/estimate", json=VALID_BODY, headers={"secret-sauce": "s3cret"}
        ).status_code == 200
    finally:
        get_settings.cache_clear()
