"""Bitemporal evidence for opening-date AFT research, never snapshot disappearance.

Baselines identify a location and inferred time origin known by that origin.
Observations are a versioned evidence ledger: both event and availability dates
are required. A closure observation brackets an exit; it is not an exact date.
"""
from collections import Counter
from datetime import date

import numpy as np
import pandas as pd

BASELINE_FIELDS = (
    "camis", "open_date", "baseline_available_on", "baseline_source_reference",
    "verification_status", "geoid", "nta_code", "borough",
)
OBSERVATION_FIELDS = (
    "camis", "status", "observed_on", "available_on", "source_reference",
    "verification_status",
)
VERIFIED = "independently_verified"
DAYS_PER_YEAR = 365.25


def parse_date(value):
    # Deliberately reject timestamps/partial dates instead of silently rounding
    # evidence that may only become available later in the day.
    parsed = date.fromisoformat(str(value))
    if parsed.isoformat() != str(value):
        raise ValueError("Evidence dates must use YYYY-MM-DD")
    return parsed


def validate_baselines(frame, as_of):
    missing = set(BASELINE_FIELDS) - set(frame.columns)
    if missing:
        raise ValueError("Baseline evidence missing fields: " + ", ".join(sorted(missing)) +
                         ". Legacy lifespan summaries cannot establish opening-time availability.")
    cutoff = parse_date(as_of)
    rows, excluded, seen = [], Counter(), set()
    for row in frame.to_dict("records"):
        identity = str(row["camis"]).strip()
        if not identity or identity in seen:
            raise ValueError("Baseline CAMIS identifiers must be unique and nonempty")
        seen.add(identity)
        if row["verification_status"] != VERIFIED:
            excluded["unverified_baseline"] += 1
            continue
        opening, available = parse_date(row["open_date"]), parse_date(row["baseline_available_on"])
        if available > opening:
            excluded["baseline_not_known_at_opening"] += 1
            continue
        if opening > cutoff:
            excluded["baseline_after_analysis_date"] += 1
            continue
        if (not str(row["baseline_source_reference"]).strip() or
                not str(row["nta_code"]).strip() or not str(row["borough"]).strip() or
                len(str(row["geoid"])) != 11 or not str(row["geoid"]).isdigit()):
            raise ValueError(f"Invalid baseline evidence/geography for {identity}")
        # Availability before a future opening is allowed for a genuinely dated
        # plan. The validity of the inferred time origin remains an evidence review.
        rows.append({**row, "camis": identity, "open_date": opening.isoformat()})
    return pd.DataFrame(rows, columns=frame.columns), dict(excluded)


def validate_observations(frame, baselines):
    missing = set(OBSERVATION_FIELDS) - set(frame.columns)
    if missing:
        raise ValueError("Outcome evidence missing fields: " + ", ".join(sorted(missing)))
    starts = baselines.set_index("camis")["open_date"].to_dict()
    rows, seen = [], set()
    for row in frame.to_dict("records"):
        identity = str(row["camis"]).strip()
        if row["verification_status"] != VERIFIED or identity not in starts:
            continue
        if row["status"] not in {"operating", "permanent_closure"}:
            raise ValueError("Only verified operating or permanent_closure observations are labels")
        observed, available = parse_date(row["observed_on"]), parse_date(row["available_on"])
        if not parse_date(starts[identity]) <= observed <= available:
            raise ValueError(f"Invalid outcome chronology for {identity}")
        if not str(row["source_reference"]).strip():
            raise ValueError("Outcome evidence needs a source reference")
        key = (identity, row["status"], observed, available, row["source_reference"])
        if key in seen:
            continue
        seen.add(key)
        rows.append({**row, "camis": identity, "observed_on": observed, "available_on": available})
    return pd.DataFrame(rows, columns=OBSERVATION_FIELDS)


def outcome_intervals(baselines, observations, as_of, strict_before=False):
    """Reconstruct labels using ONLY evidence available by the model fit date.

    Never clip a future closure back to a cutoff or assume operation until the
    cutoff. Without earlier operating evidence, the row is not trainable.
    Permanent closure needs a positive last-operating lower bound. This avoids
    inventing epsilon-duration outcomes or claiming a pre-permit date proves
    that trade had begun. Straddling three-year intervals stay unresolved.
    """
    cutoff = parse_date(as_of)
    eligible = observations[
        observations.available_on.map(lambda d: d < cutoff if strict_before else d <= cutoff).astype(bool)
    ]
    grouped = {key: group.to_dict("records") for key, group in eligible.groupby("camis")}
    rows, excluded = [], Counter()
    for row in baselines.to_dict("records"):
        start = parse_date(row["open_date"])
        events = grouped.get(row["camis"], [])
        operations = [r for r in events if r["status"] == "operating"]
        closures = [r for r in events if r["status"] == "permanent_closure"]
        if not operations:
            excluded["no_verified_followup_operation"] += 1
            continue
        last = max(operations, key=lambda r: (r["observed_on"], r["available_on"]))
        lo = (last["observed_on"] - start).days / DAYS_PER_YEAR
        if lo <= 0:
            excluded["no_positive_followup"] += 1
            continue
        hi, recorded, status = np.inf, last["available_on"], "right_censored"
        if closures:
            first_close = min(closures, key=lambda r: (r["observed_on"], r["available_on"]))
            if last["observed_on"] >= first_close["observed_on"]:
                raise ValueError(f"Operating evidence conflicts with permanent closure: {row['camis']}")
            if first_close["source_reference"] == last["source_reference"]:
                raise ValueError("Closure interval requires distinct operation and closure evidence")
            hi = (first_close["observed_on"] - start).days / DAYS_PER_YEAR
            recorded = max(recorded, first_close["available_on"])
            status = "interval_censored_closure"
        rows.append({**row, "y_lower": lo, "y_upper": hi, "label_status": status,
                     "label_available_on": recorded.isoformat()})
    return pd.DataFrame(rows, columns=[*baselines.columns, "y_lower", "y_upper", "label_status",
                                      "label_available_on"]), dict(excluded)


def three_year_outcome(lower, upper, horizon=3.0):
    """1=known beyond horizon; 0=closed by horizon; NaN=not identifiable."""
    lower, upper = np.asarray(lower, dtype=float), np.asarray(upper, dtype=float)
    return np.where(np.isfinite(upper) & (upper <= horizon), 0.0,
                    np.where(lower >= horizon, 1.0, np.nan))
