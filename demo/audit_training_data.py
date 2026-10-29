"""Read-only source audit and private, explicitly unlabeled historical preparation."""

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median

from evaluation import HISTORICAL_CORE_FEATURES, fingerprint
from match_sla_lifespan_leads import candidate_address, normalized_name
from prepare_historical_cohort import build_cohort, read_snapshots
from rent_benchmarks import COUNTY_BY_BOROUGH_DIGIT, positive_number


RENT = "reported_median_monthly_rent_psf"
IDENTIFIERS = {"geoid", "tract_code", "community_district_code", "nearest_subway_station_complex_id",
               "nearest_citibike_station_id", "nearest_pedestrian_count_site_objectid",
               "taxi_zone_dominant_area_id", "tract_label", "cuisine_categories",
               "nearest_pedestrian_count_site_loc"}


def read_rows(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError(f"Missing or duplicate headers: {path}")
        if any(None in row or any(value is None for value in row.values()) for row in rows):
            raise ValueError(f"Malformed CSV row: {path}")
        return rows, reader.fieldnames


def write_rows(path, rows, fields):
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def numeric(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def rent_audit(master, raw):
    year = max(int(row["reporting_year"]) for row in raw)
    index, rejected = {}, Counter()
    for row in raw:
        if row["reporting_year"] != str(year) or row["aggregate_level_citywide"].lower() != "census tract":
            continue
        code = row["aggregate_level_id"]
        if not re.fullmatch(r"[1-5]\d{6}", code):
            rejected["unrecognized_tract_code"] += 1
            continue
        geoid = "36" + COUNTY_BY_BOROUGH_DIGIT[code[0]] + code[1:]
        if geoid in index:
            raise ValueError(f"Duplicate latest-year source rent tract: {geoid}")
        index[geoid] = row
    result = []
    for row in master:
        source = index.get(row["geoid"])
        raw_value = source["median_monthly_rent_per_square"].strip() if source else ""
        value = positive_number(raw_value)
        reason = ("no_latest_year_source_tract" if source is None else
                  "publisher_star_marker" if raw_value == "*" else
                  "source_blank" if not raw_value else
                  "source_nonpositive_or_invalid" if value is None else
                  "source_exceeds_parser_limit" if value > 1000 else "reported")
        expected = round(value, 2) if reason == "reported" else None
        actual = numeric(row.get(RENT))
        matches = (actual is None and not row.get(RENT, "").strip()) if expected is None else (
            actual is not None and math.isfinite(actual) and math.isclose(actual, expected, abs_tol=.005))
        annual = numeric(row.get("reported_median_annual_rent_psf"))
        annual_matches = (annual is None and not row.get("reported_median_annual_rent_psf", "").strip()) if expected is None else (
            annual is not None and math.isclose(annual, round(expected * 12, 2), abs_tol=.011))
        result.append({"geoid": row["geoid"], "borough": row.get("borough", ""),
                       "reporting_year": year, "source_value": raw_value,
                       "monthly_rent_psf": row.get(RENT, ""), "rent_missing": int(expected is None),
                       "missingness_reason": reason, "monthly_source_matches": matches,
                       "annual_conversion_matches": annual_matches})
    return result, {"reporting_year": year, "reasons": dict(Counter(r["missingness_reason"] for r in result)),
                    "source_code_rejections": dict(rejected),
                    "source_tracts_outside_master": len(set(index) - {r["geoid"] for r in master}),
                    "source_or_unit_mismatches": sum(not r["monthly_source_matches"] or
                                                      not r["annual_conversion_matches"] for r in result)}


def quality_audit(rows, fields, dictionary):
    profiles, issues = [], []
    counts = Counter(row["geoid"] for row in rows)
    for geoid, count in counts.items():
        if count > 1 or not re.fullmatch(r"36(?:005|047|061|081|085)\d{6}", geoid):
            issues.append({"geoid": geoid, "column": "geoid", "rule": "invalid_or_duplicate_geoid", "value": str(count)})
    for field in fields:
        present = [(row["geoid"], row[field]) for row in rows if row[field].strip()]
        parsed = [(g, v, numeric(v)) for g, v in present]
        is_numeric = field not in IDENTIFIERS and bool(present) and all(n is not None for _, _, n in parsed)
        values = [n for _, _, n in parsed if n is not None and math.isfinite(n)] if is_numeric else []
        profile = {"column": field, "unit": dictionary.get(field, {}).get("unit", "undocumented"),
                   "definition": dictionary.get(field, {}).get("definition", ""),
                   "vintage_years_in_name_or_definition": ";".join(sorted(set(re.findall(
                       r"\b20\d{2}\b", field.replace("_", " ") + " " + dictionary.get(field, {}).get("definition", ""))))),
                   "missing": len(rows) - len(present), "missing_share": (len(rows)-len(present))/len(rows),
                   "distinct_nonmissing": len({v for _, v in present}), "numeric": is_numeric,
                   "zero_count": sum(v == 0 for v in values), "minimum": min(values) if values else "",
                   "median": median(values) if values else "", "maximum": max(values) if values else "",
                   "outlier_review_count": 0}
        if not profile["definition"]:
            issues.append({"geoid": "", "column": field, "rule": "undocumented_column", "value": ""})
        if is_numeric:
            ordered = sorted(values)
            # Tukey outer fences are review flags, never an automatic deletion rule.
            q1, q3 = (ordered[int((len(ordered)-1)*p)] for p in (.25, .75)) if ordered else (0, 0)
            low, high = q1 - 3*(q3-q1), q3 + 3*(q3-q1)
            for geoid, raw, value in parsed:
                rule = None
                if not math.isfinite(value):
                    rule = "nonfinite"
                elif field == "centroid_longitude":
                    rule = "invalid_longitude" if not -180 <= value <= 180 else None
                elif field == "centroid_latitude":
                    rule = "invalid_latitude" if not -90 <= value <= 90 else None
                elif value < 0 and not profile["unit"].startswith("relative change"):
                    rule = "negative_measure"
                elif profile["unit"] == "percent" and not 0 <= value <= 100.000001:
                    rule = "percent_outside_zero_hundred"
                elif (profile["unit"] == "share" or "_share" in field) and not 0 <= value <= 1.000001:
                    rule = "share_outside_zero_one"
                elif field == RENT and value == 0:
                    rule = "zero_commercial_rent"
                elif field == "national_walkability_index" and not 1 <= value <= 20:
                    rule = "walkability_outside_one_twenty"
                if rule:
                    issues.append({"geoid": geoid, "column": field, "rule": rule, "value": raw})
                if values and q3 > q1 and (value < low or value > high):
                    profile["outlier_review_count"] += 1
        profiles.append(profile)
    pairs = (("population_under_18_2024", "population_2024"),
             ("population_65_plus_2024", "population_2024"),
             ("population_below_poverty_2024", "poverty_universe_population_2024"),
             ("resident_area_high_earning_jobs", "resident_area_jobs"),
             ("resident_area_food_service_jobs", "resident_area_jobs"))
    for row in rows:
        for part, total in pairs:
            a, b = numeric(row.get(part)), numeric(row.get(total))
            if a is not None and b is not None and a > b:
                issues.append({"geoid": row["geoid"], "column": part,
                               "rule": "numerator_exceeds_" + total, "value": row[part]})
        for measure, denominator in (("population_density_per_sq_mile", "land_area_sq_miles"),
                                     ("jobs_per_resident", "population_2024"),
                                     ("workplace_to_resident_area_job_ratio", "resident_area_jobs")):
            if row.get(measure, "").strip() and numeric(row.get(denominator)) == 0:
                issues.append({"geoid": row["geoid"], "column": measure,
                               "rule": "populated_ratio_with_zero_" + denominator, "value": row[measure]})
    return profiles, issues


def prepare_candidates(packet, snapshots):
    result, identities = [], defaultdict(list)
    seen = set()
    for case in packet:
        key = case["business_id"].strip()
        if not key or key in seen:
            raise ValueError("Missing or duplicate candidate business ID")
        seen.add(key)
        identity = (case["borough"].lower(), normalized_name(case["candidate_name"]),
                    *candidate_address(case["candidate_address"], case["borough"]))
        if all(identity):
            identities[identity].append(key)
        baseline = case.get("first_cycle_inspection_lead", "")[:10]
        start = date.fromisoformat(baseline) if baseline else None
        row = {"business_id": key, "geoid": case["geoid"], "nta_code": case["nta_code"],
               "borough": case["borough"], "candidate_baseline_date": baseline,
               "baseline_verified": False, "training_eligible": False,
               "identity_review": case["identity_review"], "outcome_status": case["outcome_status"]}
        for feature in HISTORICAL_CORE_FEATURES:
            selected = next((s for s in snapshots[feature] if start and s["available"] <= start
                             and s["values"].get(case["geoid"])), None)
            row[feature] = selected["values"][case["geoid"]] if selected else ""
            row[feature + "__available_on"] = selected["available"].isoformat() if selected else ""
            row[feature + "__source_path"] = selected["path"] if selected else ""
        row["complete_historical_core"] = all(row[f] != "" for f in HISTORICAL_CORE_FEATURES)
        result.append(row)
    duplicate_ids = {key for group in identities.values() if len(group) > 1 for key in group}
    review = []
    for row in packet:
        reasons = []
        if row["business_id"] in duplicate_ids:
            reasons.append("multiple_archive_camis_same_normalized_identity")
        if row["identity_review"] != "same_name_and_address":
            reasons.append(row["identity_review"])
        if row.get("review_tier") == "identity_or_date_conflict":
            reasons.append("cross_source_identity_or_date_conflict")
        if reasons:
            review.append({"business_id": row["business_id"], "candidate_name": row["candidate_name"],
                           "candidate_address": row["candidate_address"], "borough": row["borough"],
                           "review_reasons": ";".join(reasons), "outcome_status": row["outcome_status"],
                           "successor_camis_leads": row.get("other_current_camis_same_name_address", "")})
    return result, review


def run(data, output):
    data = data.resolve()
    output = output.resolve()
    if not output.is_relative_to(data / "evaluation") or output.exists():
        raise ValueError("Choose a new directory under private data/evaluation")
    release = (data / "integrated/current").resolve()
    master_path = release / "master_tract_features.csv"
    rows, fields = read_rows(master_path)
    dictionary, _ = read_rows(release / "data_dictionary.csv")
    dictionary = {r["column"]: r for r in dictionary if r["file"] == "master_tract_features.csv"}
    rent_home = data / "raw_sources/storefront_rent_stats"
    rent_manifest = rent_home / "manifest.json"
    revision = json.loads(rent_manifest.read_text())["revisions"][-1]
    entry = revision["files"][0]
    raw_path = rent_home / revision["directory"] / entry["file"]
    if fingerprint(raw_path) != entry["sha256"]:
        raise ValueError("Rent source fingerprint mismatch")
    packet_path = data / "evaluation/lifespans/adjudication_packet_20261020_v5.csv"
    snapshot_path = data / "evaluation/snapshots/2023-04-v0/historical_core_snapshots.json"
    inputs = (master_path, release / "data_dictionary.csv", raw_path, rent_manifest, packet_path, snapshot_path)
    before = {str(p.relative_to(data)): fingerprint(p) for p in inputs}
    raw, _ = read_rows(raw_path)
    rent_rows, rent_summary = rent_audit(rows, raw)
    profiles, issues = quality_audit(rows, fields, dictionary)
    snapshots = read_snapshots(snapshot_path, data, HISTORICAL_CORE_FEATURES)
    packet, _ = read_rows(packet_path)
    candidates, identity_review = prepare_candidates(packet, snapshots)
    verified, cohort_audit = build_cohort(packet_path, snapshot_path, data, features=HISTORICAL_CORE_FEATURES)
    policy = []
    for field in fields:
        historical = field if field in HISTORICAL_CORE_FEATURES else (
            "median_household_income" if field == "median_household_income_2024" else "")
        policy.append({"current_master_column": field,
                       "historical_feature": historical,
                       "training_policy": "dated_snapshot_only_never_current_master" if historical else "excluded_until_historical_provenance_verified",
                       "imputation": "training_fold_median_plus_missingness_indicator_only_after_eligibility_checks" if historical else "none",
                       "source_unit": dictionary.get(field, {}).get("unit", "undocumented"),
                       "unit_handling": "divide_by_100_to_share_in_future_model_transform" if
                           dictionary.get(field, {}).get("unit") == "percent" else "retain_source_units"})
    if before != {str(p.relative_to(data)): fingerprint(p) for p in inputs}:
        raise ValueError("An input changed during audit; rerun against a stable release")
    output.mkdir(parents=True, exist_ok=False)
    for name, records, columns in (
        ("rent_coverage.csv", rent_rows, list(rent_rows[0])),
        ("feature_quality.csv", profiles, list(profiles[0])),
        ("quality_issues.csv", issues, ["geoid", "column", "rule", "value"]),
        ("historical_candidates_NOT_TRAINING.csv", candidates, list(candidates[0])),
        ("identity_review.csv", identity_review, ["business_id", "candidate_name", "candidate_address", "borough", "review_reasons", "outcome_status", "successor_camis_leads"]),
        ("training_feature_policy.csv", policy, list(policy[0])),
    ):
        write_rows(output / name, records, columns)
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "active_release": str(release),
              "master_rows": len(rows), "master_columns": len(fields), "rent": rent_summary,
              "quality_issue_count": len(issues), "quality_rules": dict(Counter(r["rule"] for r in issues)),
              "all_missing_columns": [p["column"] for p in profiles if p["missing"] == len(rows)],
              "unit_review_columns": [p["column"] for p in profiles if p["numeric"] and p["unit"] in {"varies", "undocumented"}],
              "exact_duplicate_column_pairs_review_only": [[a, b] for i, a in enumerate(fields) for b in fields[i+1:]
                    if any(row[a].strip() for row in rows) and all(row[a] == row[b] for row in rows)],
              "columns_over_40_percent_missing": [p["column"] for p in profiles if p["missing_share"] > .4],
              "identity_counts": dict(Counter(r["identity_review"] for r in packet)),
              "identity_review_rows": len(identity_review), "historical_candidates": len(candidates),
              "complete_historical_core_candidates": sum(r["complete_historical_core"] for r in candidates),
              "verified_training_rows": len(verified), "cohort_audit": cohort_audit,
              "input_sha256": before, "source_files_unchanged": True,
              "warning": "No labels inferred or published rents overwritten. Separate current-context rent estimates are not asking rents or historical survival predictors. Candidate baselines are inspection leads, not verified opening dates. No current master values enter historical candidates."}
    (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    (output / "README.md").write_text(
        "# Training Data Cleaning Audit\n\n"
        "The active release and raw sources were not modified. See report.json for fingerprints and counts.\n\n"
        "- rent_coverage.csv: reported medians, missingness reasons, and annual-unit reconciliation. A star is a publisher marker, never zero rent.\n"
        "- feature_quality.csv: every column, missingness, numeric ranges, dictionary units and review-only outer-fence outlier counts. Outliers are not deleted.\n"
        "- quality_issues.csv: structural, range, and denominator violations; investigate before training.\n"
        "- identity_review.csv: prioritized CAMIS and cross-source identity conflicts. No automatic merges or closure labels.\n"
        "- historical_candidates_NOT_TRAINING.csv: all candidates, dated historical predictors, per-feature release dates and source paths. Never pass this to training: baselines and outcomes remain unverified.\n"
        "- training_feature_policy.csv: default-deny historical feature policy; current income, commercial rent, residential rent, and synthetic property values are not interchangeable.\n\n"
        "Training remains through run_survival_training.py with verified evidence and a predeclared temporal/geographic holdout. "
        "The evaluator fits median imputation and missingness indicators on training rows only; the verified cohort currently requires complete historical predictors. "
        "Extending that eligibility rule requires a separately reviewed protocol, not blanket fillna(0).\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.data_dir / "evaluation/cleaning" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report = run(args.data_dir, output)
    print(json.dumps({"output": str(output), **report}, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
