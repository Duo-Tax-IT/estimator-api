from app.helpers import photo_dedup
from app.schemas import Photo


def test_keeps_first_of_near_identical_group_and_distinct_photos(monkeypatch):
    photos = [Photo(url=f"https://x/{i}") for i in range(4)]
    # 0 and 1 are near-identical (hamming 1); 2 is distinct (hamming 13); 3 fails.
    fake = {0: 0b0000, 1: 0b0001, 2: 0x1FFF, 3: None}
    monkeypatch.setattr(photo_dedup, "_hash_photo", lambda p: fake[int(p.url[-1])])

    kept = photo_dedup.dedup_photos(photos)

    assert [p.url for p in kept] == ["https://x/0", "https://x/2", "https://x/3"]
