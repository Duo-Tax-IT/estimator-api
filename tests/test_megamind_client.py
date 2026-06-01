import httpx
import pytest

from app import megamind_client
from app.errors import ItemsFetchError
from app.megamind_client import _map_items, fetch_renovation_items


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
    assert _map_items([_item()]) == [
        {"_id": "i1", "name": "Driveway", "defaultRate": 200, "unit": "sqm"}
    ]


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

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return _FakeResp([_item(), _item(id="i2", name="Tiling", defaultRate=120)])

    monkeypatch.setattr(megamind_client.httpx, "get", fake_get)
    items = fetch_renovation_items()
    assert captured["headers"]["X-API-KEY"] == "test-key"
    assert captured["url"].endswith("/api/external/estimator-items")
    assert [i["_id"] for i in items] == ["i1", "i2"]


def test_fetch_items_connection_error_raises(monkeypatch):
    def boom(url, headers=None, timeout=None):
        raise httpx.ConnectError("nope")

    monkeypatch.setattr(megamind_client.httpx, "get", boom)
    with pytest.raises(ItemsFetchError):
        fetch_renovation_items()


def test_fetch_items_non_200_raises(monkeypatch):
    monkeypatch.setattr(
        megamind_client.httpx,
        "get",
        lambda url, headers=None, timeout=None: _FakeResp(None, status=401),
    )
    with pytest.raises(ItemsFetchError):
        fetch_renovation_items()


def test_fetch_items_non_list_raises(monkeypatch):
    monkeypatch.setattr(
        megamind_client.httpx,
        "get",
        lambda url, headers=None, timeout=None: _FakeResp({"not": "a list"}),
    )
    with pytest.raises(ItemsFetchError):
        fetch_renovation_items()
