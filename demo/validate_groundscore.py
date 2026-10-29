"""Audit concept sensitivity and single-hex support without claiming predictive validity."""

import argparse
import csv
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from audit_scoring import compare, evaluate_release, sensitivity_pairs, sha256
from app import PROFILE_WEIGHTS
from scoring import Concept, ScreeningModel
from refresh_integrated import BASELINE, CURRENT


CONTROLLED_CONTRASTS = (
    ("format", "format:restaurant", "format:coffee"),
    ("format", "format:restaurant", "format:fine_dining"),
    ("price", "price:restaurant:$", "price:restaurant:$$$$"),
    ("cuisine", "cuisine:any", "cuisine:korean"),
    ("daypart", "daypart:all_day", "daypart:evening"),
    ("dietary", "cuisine:mexican", "dietary:vegan_mexican"),
)
COMPONENTS = tuple(PROFILE_WEIGHTS["restaurant"])


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def component_diagnostics(directory):
    from scipy.stats import spearmanr

    tracts = [row for row in read_csv(directory / "master_tract_features.csv")
              if row.get("eligible_for_location_screening", "").lower() in {"true", "1"}
              and row.get("borough") != "Staten Island"]
    restaurants = read_csv(directory / "entities/current_restaurants.csv")
    model = ScreeningModel(tracts, restaurants)
    concept = Concept.from_args({"profile": "restaurant", "price_mode": "tier", "price_tier": "$$", "cuisine": "korean"})
    weights = PROFILE_WEIGHTS["restaurant"]
    baseline, components = {}, {key: [] for key in COMPONENTS}
    coverage = {key: [] for key in COMPONENTS}
    for row in tracts:
        result = model.evaluate(row, concept, weights, "restaurant")
        baseline[row["geoid"]] = result["opportunity"]
        for key in COMPONENTS:
            components[key].append(result["components"][key]["score"])
            coverage[key].append(result["components"][key]["coverage"])
    overlap = []
    for index, first in enumerate(COMPONENTS):
        for second in COMPONENTS[index + 1:]:
            coefficient = (spearmanr(components[first], components[second]).statistic
                           if len(set(components[first])) > 1 and len(set(components[second])) > 1 else None)
            overlap.append({"first": first, "second": second,
                            "spearman_r": round(float(coefficient), 3) if coefficient is not None else None,
                            "review_overlap": bool(coefficient is not None and abs(coefficient) >= .8)})
    sensitivity = []
    for key in COMPONENTS:
        for multiplier in (.8, 1.2):
            changed_weights = {name: value * multiplier if name == key else value for name, value in weights.items()}
            alternative = {row["geoid"]: model.evaluate(row, concept, changed_weights, "restaurant")["opportunity"]
                           for row in tracts}
            sensitivity.append({"component": key, "weight_multiplier": multiplier,
                                **compare(baseline, alternative)})
    return {"reference_concept": "casual Korean restaurant, $$",
            "reference_weights": weights, "tracts": len(tracts),
            "component_distinct_scores": {key: len(set(values)) for key, values in components.items()},
            "component_median_coverage_pct": {key: statistics.median(values) for key, values in coverage.items()},
            "component_rank_correlations": overlap,
            "weight_sensitivity": sensitivity,
            "interpretation": "Correlations identify overlapping indicators; weight perturbations test rank stability. Neither calibrates the weights or validates business outcomes."}


def hex_assessment(report):
    rows = report.get("results", [])
    boroughs = {row["borough"] for row in rows} - {"Staten Island"}
    if boroughs != {"Bronx", "Brooklyn", "Manhattan", "Queens"}:
        raise ValueError("Hex audit is missing a screened borough.")
    for borough in boroughs:
        if {row["resolution"] for row in rows if row["borough"] == borough} != {8, 9}:
            raise ValueError(f"Hex audit is missing resolution 8 or 9 for {borough}.")
    coverage = {row["resolution"]: row for row in report["live_grid_coverage"]["results"]}
    if set(coverage) != {8, 9} or any(row["eligible_tract_polygon_coverage_pct"] < 99 for row in coverage.values()):
        raise ValueError("Live hex coverage is incomplete.")
    per_borough = {}
    for borough in sorted(boroughs):
        pairs = {row["resolution"]: row for row in rows if row["borough"] == borough}
        per_borough[borough] = {
            str(resolution): {"median_material_census_blocks_per_cell": pairs[resolution]["material_blocks_per_cell_p10_p50_p90"][1],
                              "median_distinct_tracts_per_cell": pairs[resolution]["distinct_tracts_per_cell_p50_p90"][0],
                              "block_land_coverage_pct": pairs[resolution]["block_land_coverage_pct"]}
            for resolution in (8, 9)}
    return {"default_single_hex_resolution": 8, "exploratory_fine_resolution": 9,
            "live_eligible_tract_coverage_pct": {str(key): value["eligible_tract_polygon_coverage_pct"] for key, value in coverage.items()},
            "by_borough": per_borough,
            "interpretation": "Resolution 9 subdivides the same tract-level inputs; finer geometry alone cannot establish more accurate demand."}


def verify_hex_inputs(report, directory):
    expected = {"master": sha256(directory / "master_tract_features.csv"),
                "geography": sha256(directory / "geography/nyc_2020_census_tracts.geojson")}
    if report.get("integrated_inputs_sha256") != expected:
        raise ValueError("Hex audit does not match the selected integrated release.")


def analyze(directory, hex_report=None):
    directory = Path(directory).resolve()
    scores = evaluate_release(directory)
    comparisons = []
    for dimension, first, second in sensitivity_pairs():
        comparisons.append({"dimension": dimension, "from": first, "to": second,
                            **compare(scores[first], scores[second])})
    controlled = [{"dimension": dimension, "from": first, "to": second,
                   **compare(scores[first], scores[second])}
                  for dimension, first, second in CONTROLLED_CONTRASTS]
    summary = {}
    for dimension in sorted({row["dimension"] for row in comparisons}):
        subset = [row for row in comparisons if row["dimension"] == dimension]
        summary[dimension] = {"pairs": len(subset),
                              "median_changed_fraction": round(statistics.median(row["changed_fraction"] for row in subset), 3),
                              "median_absolute_score_change": round(statistics.median(row["median_absolute_change"] for row in subset), 2),
                              "median_top_decile_overlap": round(statistics.median(row["top_decile_overlap"] for row in subset), 3)}
    report = {"created_at": datetime.now(timezone.utc).isoformat(),
              "status": "behavior_audited_not_outcome_validated", "training_ready": False,
              "release": str(directory), "tracts": len(next(iter(scores.values()))),
              "input_sha256": {"master": sha256(directory / "master_tract_features.csv"),
                               "restaurants": sha256(directory / "entities/current_restaurants.csv")},
              "scenario_count": len(scores), "contrast_count": len(comparisons),
              "dimension_summary": summary, "controlled_contrasts": controlled,
              "all_contrasts": comparisons,
              "component_diagnostics": component_diagnostics(directory),
              "limitations": ["Score changes and rank changes test implementation behavior, not accuracy or restaurant survival.",
                              "Weights remain uncalibrated until independently verified outcomes and dated predictors are available."]}
    if hex_report:
        hex_report = Path(hex_report)
        hex_data = json.loads(hex_report.read_text())
        verify_hex_inputs(hex_data, directory)
        report["hex_audit_sha256"] = sha256(hex_report)
        report["hex_assessment"] = hex_assessment(hex_data)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=CURRENT.resolve() if CURRENT.is_dir() else BASELINE)
    parser.add_argument("--hex-report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = analyze(args.release, args.hex_report)
    if args.output:
        serialized = json.dumps(report, indent=2, allow_nan=False) + "\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(serialized)
    print(json.dumps({key: report[key] for key in ("status", "tracts", "scenario_count", "contrast_count", "dimension_summary")}, indent=2))


if __name__ == "__main__":
    main()
