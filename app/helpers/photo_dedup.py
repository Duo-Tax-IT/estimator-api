"""Drop near-duplicate property photos before the v2 pipeline.

Re-listings re-upload the same shots under fresh asset IDs, so URL/ID dedup
misses them — only image content catches it. Each photo is downloaded once,
reduced to a perceptual dHash, and one photo per near-identical group is kept.
Best-effort: a photo that can't be fetched or read is always kept (same stance
as the room classifier — dedup must never drop a real photo or break an
estimate).
"""

import io
from concurrent.futures import ThreadPoolExecutor

import httpx
from PIL import Image

from ..schemas import Photo

# Max dHash Hamming distance still treated as the same photo (tuned on re-listed
# CoreLogic sets: identical re-uploads land at 0-8, distinct shots well above).
DUP_DISTANCE = 8


def _dhash(image_bytes: bytes, size: int = 8) -> int | None:
    """Row-wise difference hash (size*size bits), or None if unreadable.

    Greyscale, resize to (size+1, size), then 1 bit per adjacent-pixel compare —
    robust to rescaling/recompression, which is exactly how re-lists differ.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("L").resize(
            (size + 1, size), Image.LANCZOS
        )
    except Exception:
        return None
    px = img.tobytes()  # one byte per pixel, row-major
    bits = 0
    for r in range(size):
        row = r * (size + 1)
        for c in range(size):
            bits = (bits << 1) | (px[row + c] < px[row + c + 1])
    return bits


def _hash_photo(photo: Photo) -> int | None:
    """Download a photo and hash it; None if it can't be fetched or read."""
    try:
        resp = httpx.get(photo.url, timeout=30, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    return _dhash(resp.content)


def dedup_photos(photos: list[Photo]) -> list[Photo]:
    """Keep the first photo of each near-identical group.

    Input is newest-first (see rpdata_client._map_photos), so the newest copy of
    a re-listed shot survives. Photos that fail to hash are always kept.
    """
    with ThreadPoolExecutor(max_workers=8) as pool:
        hashes = list(pool.map(_hash_photo, photos))
    kept, kept_hashes = [], []
    for photo, h in zip(photos, hashes):
        if h is not None and any(
            bin(h ^ k).count("1") <= DUP_DISTANCE for k in kept_hashes
        ):
            continue
        kept.append(photo)
        if h is not None:
            kept_hashes.append(h)
    if len(kept) < len(photos):
        print(f"[photo_dedup] dropped {len(photos) - len(kept)} duplicate photo(s); kept {len(kept)}")
    return kept
