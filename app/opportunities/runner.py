"""CLI harness: run an estimator pipeline across Salesforce opportunities and
store every output in training.db, for tuning the pipeline against real data.

Idempotent per (opportunity, version): re-runs skip opps already `ok` at the
current version. Editing a prompt bumps the version (see derive_version), so a
fresh sweep runs while the old version's rows stay for comparison.

    python -m app.opportunities.runner --pipeline v3 [--stage Fillout] [--force] [--limit N]
"""
import argparse
import hashlib
from pathlib import Path

from ..config import get_settings
from ..errors import EstimatorError
from ..estimator import build_full_estimate
from ..estimator_v2 import build_estimate_v2
from ..estimator_v3 import build_estimate_v3
from ..schemas import EstimateRequest
from . import list_opportunities, store

BUILDERS = {"v1": build_full_estimate, "v2": build_estimate_v2, "v3": build_estimate_v3}

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def derive_version(pipeline: str, model: str) -> str:
    """Run identity: pipeline + a short hash of the prompts and model. Editing any
    prompt or swapping the model bumps it, triggering a fresh idempotent sweep."""
    h = hashlib.sha256(model.encode())
    for f in sorted(_PROMPTS_DIR.glob("*.txt")):
        h.update(f.read_bytes())
    return f"{pipeline}@{h.hexdigest()[:8]}"


def _request(opp: dict, model: str) -> EstimateRequest:
    """Map an opportunity's real fields onto the estimator's inputs."""
    build = opp.get("Build_Date_OC_Date__c")  # 'YYYY-MM-DD' or None
    return EstimateRequest(
        rpId=opp["RPData_Property_ID__c"],
        model=model,
        address=opp.get("Property_Address__c"),
        settlementDate=opp.get("Settlement_Date__c"),
        buildYear=int(build[:4]) if build else None,
        label="training",
    )


def run(pipeline: str = "v3", stage: str | None = "Fillout",
        force: bool = False, limit: int | None = None) -> dict:
    """Run `pipeline` over `stage` opportunities into Postgres; return a summary.

    Parallel-safe: workers race to claim each opp; only the winner runs it, so
    running this same command in several processes splits the work without a queue.
    """
    model = get_settings().default_model
    version = derive_version(pipeline, model)
    builder = BUILDERS[pipeline]
    store.init_db()
    # Skip opps already in the DB so each batch advances to fresh ones; --force
    # ignores this and re-processes the window.
    exclude = set() if force else store.done_opportunity_ids()
    opps = list_opportunities(stage=stage, exclude_ids=exclude, limit=limit or 20)  # TEMP: cap at 20
    summary = {"version": version, "total": len(opps), "ran": 0, "skipped": 0, "errors": 0}

    for opp in opps:
        store.upsert_opportunity(opp)
        if not store.claim_estimate(opp["Id"], pipeline, version, model, force):
            continue  # another worker owns it, or it's already ok
        if not opp.get("RPData_Property_ID__c"):
            store.finish_estimate(opp["Id"], version, "skipped", error="no RPData_Property_ID__c")
            summary["skipped"] += 1
            continue
        try:
            result = builder(_request(opp, model))
        except EstimatorError as exc:
            store.finish_estimate(opp["Id"], version, "error", error=str(exc))
            summary["errors"] += 1
            continue
        store.finish_estimate(opp["Id"], version, "ok", estimate=result)
        summary["ran"] += 1
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Run a pipeline across opportunities into training.db")
    p.add_argument("--pipeline", default="v3", choices=list(BUILDERS))
    p.add_argument("--stage", default="Fillout")
    p.add_argument("--force", action="store_true", help="re-run even opps already ok")
    p.add_argument("--limit", type=int, help="cap number of opportunities")
    a = p.parse_args()
    print(run(a.pipeline, a.stage, a.force, a.limit))
