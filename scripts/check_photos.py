"""Smoke-test the calc.duo.tax photos integration without calling OpenAI.

Fetches a property's photos for an rp_id, runs them through the same
`_map_photos` filtering the service uses, and prints what would be sent to the
vision model. No OpenAI key required.

Usage (from the estimator-api/ root):
    python scripts/check_photos.py <rp_id>
    RPDATA_API_URL="https://.../{rp_id}" python scripts/check_photos.py <rp_id>
"""

import os
import sys

import httpx

# Allow `import app...` when run from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.rpdata_client import _map_photos  # noqa: E402

DEFAULT_URL = "https://calc.duo.tax/property/{rp_id}"


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python scripts/check_photos.py <rp_id>")
        raise SystemExit(2)

    rp_id = sys.argv[1]
    base = os.environ.get("RPDATA_API_URL", DEFAULT_URL).format(rp_id=rp_id)
    url = base.rstrip("/") + "/photos"
    print(f"GET {url}")

    resp = httpx.get(url, timeout=30)
    resp.raise_for_status()
    raw = resp.json()

    if not isinstance(raw, list):
        print(f"WARNING: expected a JSON list, got {type(raw).__name__}")
        raise SystemExit(1)

    photos = _map_photos(raw)
    print(f"raw items: {len(raw)}  ->  usable photos: {len(photos)}")
    for p in photos:
        host = p.url.split("/")[2] if "://" in p.url else p.url
        print(f"  {p.date or '(no date)':<12} {host}")


if __name__ == "__main__":
    main()
