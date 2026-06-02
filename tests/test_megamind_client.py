import httpx
import pytest

from app import megamind_client
from app.errors import BciFetchError, ItemsFetchError
from app.megamind_client import _map_items, fetch_bci_factor, fetch_renovation_items


def _item(**overrides):
    item = {
        "id": "i1",
        "name": "Driveway",
        "defaultRate": 200,
        "unit": "sqm",
        "sections": [],
        "isDeleted": False,
        "createdBy": "thai@duotax.com.au",
    }
    item.update(overrides)
    return item


class _FakeResp:
    def __init__(self, payload, status=200, json_raises=False):
        self._payload = payload
        self._status = status
        self._json_raises = json_raises

    def raise_for_status(self):
        if self._status >= 400:
            raise httpx.HTTPError(f"HTTP {self._status}")

    def json(self):
        if self._json_raises:
            raise ValueError("bad json")
        return self._payload


def test_map_items_maps_id_to_underscore_id_and_keeps_core_fields():
    # The megamind audit/sections fields are dropped; `id` becomes `_id`.
    # defaultQuantity is carried through (None when absent); parentName too.
    assert _map_items([_item(defaultQuantity=3)]) == [
        {"_id": "i1", "name": "Driveway", "defaultRate": 200, "unit": "sqm",
         "defaultQuantity": 3, "parentName": None}
    ]
    assert _map_items([_item()])[0]["defaultQuantity"] is None


def test_map_items_resolves_parent_name_from_payload():
    # A label-only parent (no rate) is dropped from the catalog but still names
    # its child's group via parentId.
    parent = _item(id="p1", name="Outdoor", defaultRate=None)
    child = _item(id="c1", name="Driveway", parentId="p1")
    mapped = _map_items([parent, child])
    assert [m["_id"] for m in mapped] == ["c1"]
    assert mapped[0]["parentName"] == "Outdoor"


def test_map_items_drops_deleted():
    items = [_item(id="keep"), _item(id="gone", isDeleted=True)]
    assert [i["_id"] for i in _map_items(items)] == ["keep"]


def test_map_items_ignores_is_verified():
    # isVerified is deliberately not a filter — unverified items still pass.
    items = [_item(id="verified", isVerified=True), _item(id="unverified", isVerified=False)]
    assert [i["_id"] for i in _map_items(items)] == ["verified", "unverified"]


def test_map_items_drops_items_missing_id_name_or_rate():
    items = [
        _item(id=None),
        _item(name=None),
        _item(defaultRate=None),
        _item(id="ok"),
    ]
    assert [i["_id"] for i in _map_items(items)] == ["ok"]


def test_fetch_items_sends_api_key_header_and_maps(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, params=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return _FakeResp([_item(), _item(id="i2", name="Tiling", defaultRate=120)])

    monkeypatch.setattr(megamind_client.httpx, "get", fake_get)
    items = fetch_renovation_items()
    assert captured["headers"]["X-API-KEY"] == "test-key"
    assert captured["url"].endswith("/api/external/estimator-items")
    assert [i["_id"] for i in items] == ["i1", "i2"]


def test_fetch_items_connection_error_raises(monkeypatch):
    def boom(url, headers=None, params=None, timeout=None):
        raise httpx.ConnectError("nope")

    monkeypatch.setattr(megamind_client.httpx, "get", boom)
    with pytest.raises(ItemsFetchError):
        fetch_renovation_items()


def test_fetch_items_non_200_raises(monkeypatch):
    monkeypatch.setattr(
        megamind_client.httpx,
        "get",
        lambda url, headers=None, params=None, timeout=None: _FakeResp(None, status=401),
    )
    with pytest.raises(ItemsFetchError):
        fetch_renovation_items()


def test_fetch_items_non_list_raises(monkeypatch):
    monkeypatch.setattr(
        megamind_client.httpx,
        "get",
        lambda url, headers=None, params=None, timeout=None: _FakeResp({"not": "a list"}),
    )
    with pytest.raises(ItemsFetchError):
        fetch_renovation_items()


def test_fetch_bci_factor_sends_params_and_returns_factor(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, params=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["params"] = params
        return _FakeResp({"factor": 0.6902, "past": {"value": 303}, "present": {"value": 439}})

    monkeypatch.setattr(megamind_client.httpx, "get", fake_get)
    factor = fetch_bci_factor("NSW", "2018-06-15")
    assert factor == 0.6902
    assert captured["url"].endswith("/api/external/aiqs-bci/factor")
    assert captured["headers"]["X-API-KEY"] == "test-key"
    assert captured["params"] == {"state": "NSW", "date": "2018-06-15"}


def test_fetch_bci_factor_defaults_to_one_when_absent(monkeypatch):
    # Endpoint's no-scaling fallback (unknown state) omits/zeroes the factor.
    monkeypatch.setattr(
        megamind_client.httpx,
        "get",
        lambda url, headers=None, params=None, timeout=None: _FakeResp({"past": None}),
    )
    assert fetch_bci_factor("XYZ", "2018-06-15") == 1.0


def test_fetch_bci_factor_connection_error_raises(monkeypatch):
    def boom(url, headers=None, params=None, timeout=None):
        raise httpx.ConnectError("nope")

    monkeypatch.setattr(megamind_client.httpx, "get", boom)
    with pytest.raises(BciFetchError):
        fetch_bci_factor("NSW", "2018-06-15")
