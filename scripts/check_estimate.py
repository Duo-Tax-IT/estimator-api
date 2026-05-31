"""End-to-end smoke test: rp_id -> megamind items + calc.duo.tax photos ->
vision model -> estimate.

Requires a real OPENAI_API_KEY and MEGAMIND_API_KEY (in .env or .env.local) and
HITS THE PAID OpenAI API. Uses the default model (gpt-5.4-mini) unless
DEFAULT_MODEL overrides it.

Usage (from the estimator-api/ root):
    python scripts/check_estimate.py <rp_id>
"""

import json
import os
import sys

# Allow `import app...` when run from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.estimator import build_full_estimate  # noqa: E402
from app.schemas import EstimateRequest  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python scripts/check_estimate.py <rp_id>")
        raise SystemExit(2)

    result = build_full_estimate(EstimateRequest(rpId=sys.argv[1]))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
