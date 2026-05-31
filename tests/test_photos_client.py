import httpx
import pytest

from app import photos_client
from app.errors import PhotosFetchError
from app.photos_client import _map_photos, fetch_photos


def _img(url, date="2024-01-01", **extra):
    item = {
        "digitalAssetType": "Image",
        "noPhotoAvailable": False,
        "largePhotoUrl": url,
        "scanDate": date,
    }
    item.update(extra)
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


def test_map_photos_real_corelogic_shape():
    items = [
        {
            "basePhotoUrl": "https://images.corelogic.asia/0x0/a",
            "digitalAssetType": "Image",
            "isDefaultPhoto": True,
            "largePhotoUrl": "https://images.corelogic.asia/768x512/a",
            "mediumPhotoUrl": "https://images.corelogic.asia/470x313/a",
            "noPhotoAvailable": False,
            "scanDate": "2026-05-19",
        }
    ]
    photos = _map_photos(items)
    assert len(photos) == 1
    assert photos[0].url == "https://images.corelogic.asia/768x512/a"  # prefers large
    assert photos[0].date == "2026-05-19"


def test_map_photos_url_preference_order():
    medium_only = {
        "digitalAssetType": "Image",
        "mediumPhotoUrl": "https://x/medium",
        "basePhotoUrl": "https://x/base",
    }
    base_only = {"digitalAssetType": "Image", "basePhotoUrl": "https://x/base"}
    assert _map_photos([medium_only])[0].url == "https://x/medium"
    assert _map_photos([base_only])[0].url == "https://x/base"


def test_map_photos_filters_non_image_no_photo_and_missing_url():
    items = [
        {"digitalAssetType": "Floor Plan", "largePhotoUrl": "https://x/fp"},
        _img("https://x/np", noPhotoAvailable=True),
        {"digitalAssetType": "Image"},  # no url fields
        _img("https://x/keep"),
    ]
    assert [p.url for p in _map_photos(items)] == ["https://x/keep"]


def test_map_photos_drops_google_maps_entries():
    items = [
        _img("https://maps.googleapis.com/maps/api/streetview?x=1"),
        _img("https://maps.googleapis.com/maps/api/staticmap?x=1"),
        _img("https://images.corelogic.asia/768x512/keep"),
    ]
    assert [p.url for p in _map_photos(items)] == [
        "https://images.corelogic.asia/768x512/keep"
    ]


def test_map_photos_sorts_newest_first_dateless_last():
    items = [
        _img("https://x/2020", date="2020-01-01"),
        _img("https://x/2024", date="2024-06-01"),
        _img("https://x/none", date=None),
        _img("https://x/2022", date="2022-03-01"),
    ]
    assert [p.url for p in _map_photos(items)] == [
        "https://x/2024",
        "https://x/2022",
        "https://x/2020",
        "https://x/none",
    ]


def test_fetch_photos_success_formats_url(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        return _FakeResp([_img("https://x/a")])

    monkeypatch.setattr(photos_client.httpx, "get", fake_get)
    photos = fetch_photos("RP1")
    assert captured["url"] == "https://calc.duo.tax/property/RP1/photos"
    assert [p.url for p in photos] == ["https://x/a"]


def test_fetch_photos_connection_error_raises(monkeypatch):
    def boom(url, headers=None, timeout=None):
        raise httpx.ConnectError("nope")

    monkeypatch.setattr(photos_client.httpx, "get", boom)
    with pytest.raises(PhotosFetchError):
        fetch_photos("RP1")


def test_fetch_photos_non_200_raises(monkeypatch):
    monkeypatch.setattr(
        photos_client.httpx,
        "get",
        lambda url, headers=None, timeout=None: _FakeResp(None, status=500),
    )
    with pytest.raises(PhotosFetchError):
        fetch_photos("RP1")


def test_fetch_photos_non_list_payload_raises(monkeypatch):
    monkeypatch.setattr(
        photos_client.httpx,
        "get",
        lambda url, headers=None, timeout=None: _FakeResp({"not": "a list"}),
    )
    with pytest.raises(PhotosFetchError):
        fetch_photos("RP1")
