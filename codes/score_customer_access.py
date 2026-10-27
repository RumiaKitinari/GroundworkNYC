"""Re-score a pinned route bundle for a business concept without rebuilding routes."""

import argparse
from datetime import date
from pathlib import Path

import pandas as pd

from customer_access import AccessConcept, score_cached_run


PRICE_TIERS = {"$": 18, "$$": 35, "$$$": 65, "$$$$": 110}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--access-run", type=Path, required=True)
    parser.add_argument("--service-style", choices=["quick_service", "casual", "fine_dining"], default="casual")
    price = parser.add_mutually_exclusive_group()
    price.add_argument("--average-check", type=float)
    price.add_argument("--price-tier", choices=list(PRICE_TIERS))
    parser.add_argument("--audience", choices=["residents", "workers", "destination"], default="residents")
    parser.add_argument("--daypart", choices=["all_day", "morning", "lunch", "evening"], default="all_day")
    parser.add_argument("--prediction-date", default=date.today().isoformat())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new output path; previous results are preserved")
    import json
    manifest = json.loads((args.access_run / "manifest.json").read_text())
    candidates = pd.read_csv(manifest["sources"]["listings"]["path"], dtype={"geoid": str, "property_id": str})
    check = PRICE_TIERS[args.price_tier] if args.price_tier else args.average_check if args.average_check is not None else 35
    concept = AccessConcept(args.service_style, check, args.audience, args.daypart)
    result = score_cached_run(args.access_run, concept, candidates, args.prediction_date)
    result.insert(0, "property_id", candidates.property_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(f"Saved {len(result)} property-access assessments to {args.output}")
    print("Uncalibrated walking-access opportunity features; no survival or visit prediction.")


if __name__ == "__main__":
    main()
