"""Audit the proposed lifespan archive without treating snapshot gaps as closures."""

import argparse
import csv
import json
import math
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from evaluation import fingerprint


REQUIRED = {"camis", "open_date", "survival_lower_years", "survival_upper_years", "clean_cohort"}
TRUE_VALUES = {"1", "true", "yes", "y"}
FALSE_VALUES = {"0", "false", "no", "n", ""}


def audit_lifespans(path, today=None):
    path = Path(path)
    today = today or date.today()
    counts = Counter()
    seen = set()
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        missing = REQUIRED - set(reader.fieldnames or [])
        if missing:
            raise ValueError("Lifespan archive is missing columns: " + ", ".join(sorted(missing)))
        for row in reader:
            counts["rows"] += 1
            clean = (row.get("clean_cohort") or "").strip().lower()
            if clean not in TRUE_VALUES | FALSE_VALUES:
                counts["invalid_clean_cohort_flag"] += 1
                continue
            if clean not in TRUE_VALUES:
                continue
            counts["clean_cohort_rows"] += 1
            camis = (row.get("camis") or "").strip()
            if not camis:
                counts["missing_camis"] += 1
            elif camis in seen:
                counts["duplicate_camis"] += 1
            seen.add(camis)
            try:
                opened = date.fromisoformat((row.get("open_date") or "").strip()[:10])
                if opened > today or opened < date(2000, 1, 1):
                    raise ValueError("opening date outside plausible range")
            except ValueError:
                counts["invalid_open_date"] += 1
                continue
            try:
                lower = float(row.get("survival_lower_years") or "")
                upper = float(row.get("survival_upper_years") or "")
                if not math.isfinite(lower) or lower < 0 or upper < lower or math.isnan(upper):
                    raise ValueError("invalid lifespan interval")
            except ValueError:
                counts["invalid_interval"] += 1
                continue
            if lower > (today - opened).days / 365.25 + 0.1:
                counts["interval_extends_beyond_today"] += 1
            if math.isinf(upper):
                counts["right_censored_rows"] += 1
            elif upper <= 1:
                counts["snapshot_inferred_exit_within_year"] += 1
            elif lower >= 1:
                counts["snapshot_observed_at_least_one_year"] += 1
            else:
                counts["one_year_outcome_indeterminate"] += 1
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(path.resolve()), "source_sha256": fingerprint(path),
        "counts": dict(counts), "training_eligible": False,
        "status": "requires_independent_outcome_verification",
        "reasons": [
            "A first pre-permit inspection is not a verified business opening date.",
            "Disappearance from an inspection snapshot is not a verified permanent closure.",
            "Snapshot intervals alone do not establish unbiased one-year outcomes or historical predictor availability.",
        ],
        "next_step": "Verify baseline operation, outcome, dates, and independent source references; then use prepare_historical_cohort.py.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Local restaurant_lifespans.csv")
    parser.add_argument("--output", type=Path, help="Optional new JSON audit file")
    args = parser.parse_args()
    audit = audit_lifespans(args.archive)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(audit, stream, indent=2)
            stream.write("\n")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
