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
    args = parser.parse_args()
    try:
        result = run_evaluation(integrated_package(), PROJECT_ROOT / "data", args.cuisine, args.target, args.cutoff)
    except (ValueError, FileNotFoundError, ImportError) as error:
        parser.exit(2, f"Evaluation failed: {error}\n")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
