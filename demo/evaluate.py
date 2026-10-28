"""Run reproducible backend benchmarks without changing dashboard rankings."""

import argparse
import json

from app import PROJECT_ROOT, integrated_package
from evaluation import run_evaluation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["market_presence", "continued_operation"], default="market_presence")
    parser.add_argument("--cuisine", default="korean")
    parser.add_argument("--cutoff", help="YYYY-MM-DD: train only on outcomes recorded before this date")
    parser.add_argument("--feature-set", choices=["full", "historical_core"], default="full",
                        help="Historical predictors for continued-operation evaluation")
    parser.add_argument("--validation-mode", choices=["temporal_spatial", "spatial_exploratory"],
                        default="temporal_spatial", help="Temporal test or explicitly exploratory spatial-only test")
    args = parser.parse_args()
    try:
        result = run_evaluation(integrated_package(), PROJECT_ROOT / "data", args.cuisine, args.target,
                                args.cutoff, args.feature_set, args.validation_mode)
    except (ValueError, FileNotFoundError, ImportError) as error:
        parser.exit(2, f"Evaluation failed: {error}\n")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
