"""In-process Places365 room classifier — hints the v2 observe step.

Predicts a coarse room type per photo and turns it into a one-line hint fed to
the observe model alongside the image. The heavy deps (torch / torchvision /
Pillow) are imported lazily and the whole module degrades to a no-op when it is
disabled, uninstalled, or missing its weights — a missing classifier must never
break an estimate (same best-effort stance as _bci_factor / _save_run).
"""

import io
from functools import lru_cache
from pathlib import Path

from .config import get_settings

# Places365 scene -> our coarse room label. Ported verbatim from the PoC; edit
# here to add/remove rooms. Scenes not listed are simply never predicted.
LABELS = {
    "kitchen": "Kitchen", "restaurant_kitchen": "Kitchen", "pantry": "Kitchen",
    "bathroom": "Bathroom", "shower": "Bathroom", "jacuzzi/indoor": "Bathroom",
    "laundromat": "Laundry", "utility_room": "Laundry",
    "bedroom": "Bedroom", "bedchamber": "Bedroom", "childs_room": "Bedroom",
    "dorm_room": "Bedroom", "hotel_room": "Bedroom", "nursery": "Bedroom",
    "living_room": "Living Room", "recreation_room": "Living Room",
    "television_room": "Living Room", "home_theater": "Living Room", "playroom": "Living Room",
    "dining_room": "Dining Room", "dining_hall": "Dining Room",
    "corridor": "Hallway", "entrance_hall": "Hallway", "staircase": "Hallway",
    "garage/indoor": "Garage", "garage/outdoor": "Garage",
    "parking_garage/indoor": "Garage", "parking_garage/outdoor": "Garage",
    "house": "Exterior", "balcony/exterior": "Exterior", "patio": "Exterior",
    "porch": "Exterior", "yard": "Exterior", "lawn": "Exterior", "driveway": "Exterior",
    "residential_neighborhood": "Exterior", "courtyard": "Exterior",
    "apartment_building/outdoor": "Exterior", "manufactured_home": "Exterior",
    "doorway/outdoor": "Exterior",
}

# Confidence % below which a prediction is too weak to hint with.
THRESHOLD = 15.0

_CATEGORIES_FILE = Path(__file__).parent / "models" / "places365" / "categories_places365.txt"


@lru_cache
def _model():
    """Load the ResNet18 Places365 model once, with the allowed-scene index map.

    Returns (model, prep, allowed) where `allowed` is a list of
    (scene_index, room_label, scene_name) for the scenes in LABELS — or None when
    the classifier is disabled or its deps/weights are unavailable (logged once,
    then a permanent no-op for the process).
    """
    settings = get_settings()
    if not settings.room_classifier_enabled:
        return None
    try:
        import torch
        from torchvision import transforms as T
        from torchvision.models import resnet18
    except ImportError:
        print("[room_classifier] torch/torchvision not installed — room hints disabled")
        return None

    weights = Path(settings.places365_weights_path)
    if not weights.exists() or not _CATEGORIES_FILE.exists():
        print(f"[room_classifier] weights/categories missing ({weights}) — room hints disabled")
        return None

    classes = [ln.strip().split(" ")[0][3:] for ln in _CATEGORIES_FILE.open()]
    model = resnet18(num_classes=365)
    ckpt = torch.load(weights, map_location="cpu", weights_only=True)
    model.load_state_dict({k.replace("module.", ""): v for k, v in ckpt["state_dict"].items()})
    model.eval()
    prep = T.Compose([T.Resize((224, 224)), T.ToTensor(),
                      T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])
    allowed = [(i, LABELS[s], s) for i, s in enumerate(classes) if s in LABELS]
    return model, prep, allowed


def classify(image_bytes: bytes) -> dict | None:
    """Predict a room label for an image.

    Returns {"label", "scene", "confidence"} — label is "Unsure" below THRESHOLD.
    Returns None when the classifier is unavailable or the image can't be read.
    """
    loaded = _model()
    if loaded is None:
        return None
    import torch
    from PIL import Image
    model, prep, allowed = loaded
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return None
    with torch.no_grad():
        probs = model(prep(img).unsqueeze(0)).softmax(1)[0]
    # Best-scoring scene among only the allowed (mapped) ones.
    idx, label, scene = max(allowed, key=lambda a: probs[a[0]])
    conf = round(probs[idx].item() * 100, 1)
    result = {"label": label if conf >= THRESHOLD else "Unsure", "scene": scene, "confidence": conf}
    print(f"[room_classifier] {result['label']} (scene={scene}, confidence={conf}%)")
    return result


def format_hint(prediction: dict) -> str | None:
    """The observe-step hint line for a `classify` prediction, e.g.
    "Predicted room type: Kitchen (confidence 82%)".

    None when the prediction is too weak (Unsure) — the caller then omits the
    hint and the observe model decides unaided.
    """
    if prediction["label"] == "Unsure":
        return None
    return f"Predicted room type: {prediction['label']} (confidence {prediction['confidence']:.0f}%)"
