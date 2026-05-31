"""Smoke-test the megamind renovation-items integration. No OpenAI call.

Uses the configured MEGAMIND_API_URL + MEGAMIND_API_KEY (from .env/.env.local)
and prints the mapped catalog the model would receive.

Usage (from the estimator-api/ root):
    python scripts/check_items.py
"""

import os
import sys

# Allow `import app...` when run from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.megamind_client import fetch_renovation_items  # noqa: E402


def main() -> None:
    items = fetch_renovation_items()
    print(f"usable renovation items: {len(items)}")
    for it in items:
        print(f"  {it['_id']}  {it['name']:<32} {it['defaultRate']}/{it.get('unit')}")


if __name__ == "__main__":
    main()
