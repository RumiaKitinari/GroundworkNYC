"""Full-inventory feature and Huff scenario checks, separate from accuracy claims."""
import argparse
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd

from customer_access import access_features, file_hash, load_access_bundle
from engineer_customer_access import PROFILES
from network_huff import competitor_stock, network_scenarios
from make_heatmaps import NYC_BBOX, count_matrix, gap_scores
from recommend import cuisine_gap

CUISINES = {"neighborhood_cafe": "Coffee / Tea", "office_lunch": "Sandwiches / Deli",
            "casual_dinner": "Italian", "premium_dinner": "Steakhouse"}


def gap_inventory(labeled):
    from cuisine_matrix import build_matrix
    return labeled[labeled.cuisine_50.isin(build_matrix().index)
                   & labeled.latitude.between(NYC_BBOX["lat_min"], NYC_BBOX["lat_max"])
                   & labeled.longitude.between(NYC_BBOX["lng_min"], NYC_BBOX["lng_max"])].copy()


def rank_comparison(baseline, alternative, top=50):
    frame = pd.DataFrame({"baseline": baseline, "alternative": alternative}).dropna()
    size = min(top, len(frame))
    rho = frame.baseline.corr(frame.alternative, method="spearman") if len(frame) > 2 else np.nan
    overlap = (len(set(frame.nlargest(size, "baseline").index) & set(frame.nlargest(size, "alternative").index))
               / size if size else None)
    return {"paired_rows": len(frame), "spearman": None if pd.isna(rho) else float(rho),
            "top_k": size, "top_k_retention": overlap,
            "comparison_population": "Common nonmissing candidates only; ties use stable input order"}


def run(property_run, tract_run, output, restaurants_path=None):
    output = Path(output)
    if output.exists():
        raise FileExistsError("Choose a new evaluation directory")
    today = date.today().isoformat()
    origins, properties, routes, pm = load_access_bundle(property_run, today)
    tract_origins, tract_candidates, tract_routes, tm = load_access_bundle(tract_run, today)
    if (pm["sources"]["master"]["sha256"] != tm["sources"]["master"]["sha256"]
            or pm["sources"]["network"]["sha256"] != tm["sources"]["network"]["sha256"]
            or pm["config"] != tm["config"] or not origins.geoid.equals(tract_origins.geoid)):
        raise ValueError("Property and competitor routes must use identical origins, network and settings")
    if restaurants_path is None:
        restaurants_path = Path(pm["sources"]["master"]["path"]).parent / "entities/current_restaurants.csv"
    restaurants_path = Path(restaurants_path).resolve()
    restaurant_hash = file_hash(restaurants_path)
    restaurants = pd.read_csv(restaurants_path, dtype={"camis": str, "geoid": str})
    if not properties.inventory_type.isin(["synthetic", "synthetic_demonstration"]).all():
        raise ValueError("This evaluation expects the explicitly synthetic scenario inventory")
    config = pm["config"]
    output.mkdir(parents=True, exist_ok=False)
    all_ablations, coverage, huff_audits, diagnostics, sensitivity = [], [], [], [], []
    master = origins.set_index("geoid")
    # Reuse Atharv's exact gap calculation, on the complete active label inventory.
    _, _, labeled = competitor_stock(restaurants, origins.geoid, "Italian")
    labeled = labeled.merge(restaurants[["camis", "latitude", "longitude"]], on="camis", validate="one_to_one")
    import h3
    from cuisine_matrix import build_matrix
    eligible = gap_inventory(labeled)
    eligible["hex"] = [h3.latlng_to_cell(la, lo, 9) for la, lo in zip(eligible.latitude, eligible.longitude)]
    counts = count_matrix(eligible)
    universe = sorted({cell for home in counts.index for cell in h3.grid_disk(home, 4)})
    local, area, gap = gap_scores(counts, build_matrix(), universe)
    gap_path = output / "selected_cuisine_gap_scores.csv"
    pd.concat([pd.DataFrame({"hex": universe, "cuisine": cuisine, "gap_score": gap[cuisine].values,
        "local_competition": local[cuisine].values, "area_competition": area[cuisine].values})
        for cuisine in CUISINES.values()], ignore_index=True).to_csv(gap_path, index=False)
    labeled.to_csv(output / "competition_label_audit.csv", index=False)
    for name, concept in PROFILES.items():
        print("Evaluating " + name, flush=True)
        features = access_features(origins, properties, routes, concept, config)
        baseline = features.price_adjusted_access_opportunities.where(features.inverse_walkability_percentile.notna())
        rw, ww = np.multiply(config["audience_weights"][concept.audience], config["daypart_weights"][concept.daypart])
        variants = {
            "without_affordability": features.customer_access_opportunities,
            "without_workers": (baseline - ww * features.decay_worker_opportunities) / rw,
            "without_residents": features.decay_worker_opportunities,
            "epa_walkability_only": properties.geoid.map(master.national_walkability_index),
            "local_population_only": properties.geoid.map(master.population_2024),
            "local_jobs_only": properties.geoid.map(master.total_jobs),
        }
        uniform = {**config, "half_life_minutes": {**config["half_life_minutes"], concept.service_style: 1e9}}
        variants["without_distance_decay_within_catchment"] = access_features(origins, properties, routes, concept, uniform).price_adjusted_access_opportunities
        for variant, values in variants.items():
            all_ablations.append({"profile": name, "variant": variant, **rank_comparison(baseline, values)})
        stock, inventory_audit, _ = competitor_stock(restaurants, origins.geoid, CUISINES[name])
        huff, huff_audit = network_scenarios(origins, properties, routes, tract_candidates, tract_routes, stock, concept, config)
        huff_audits.append({"profile": name, "cuisine": CUISINES[name], **huff_audit, "inventory": inventory_audit})
        result = properties[["property_id", "geoid", "borough", "inventory_type"]].copy()
        result["customer_access_percentile"] = features.inverse_walkability_percentile
        result["huff_opportunities"] = huff.huff_opportunities
        result["huff_percentile"] = huff.huff_percentile
        result["huff_status"] = huff.status
        result["cuisine_gap"] = cuisine_gap(properties, CUISINES[name], gap_path)[0]
        # The 60/40 survival+gap baseline cannot be populated without a validated
        # survival artifact. No substitute probability or proxy baseline is made.
        result["survival_3yr"] = np.nan
        result["baseline_60_40"] = np.nan
        result.to_csv(output / (name + ".csv"), index=False)
        diagnostics.append({"profile": name, "comparison": "walking_access_vs_competition_aware_huff",
            **rank_comparison(features.inverse_walkability_percentile, huff.huff_percentile)})
        diagnostics.append({"profile": name, "comparison": "supply_gap_vs_competition_aware_huff",
            **rank_comparison(result.cuisine_gap, huff.huff_percentile)})
        for borough, group in result.groupby("borough"):
            coverage.append({"profile": name, "borough": borough, "properties": len(group),
                "access_rated": int(group.customer_access_percentile.notna().sum()),
                "huff_rated": int(group.huff_percentile.notna().sum())})
        for outside in (.5, 2.0):
            alternative, _ = network_scenarios(origins, properties, routes, tract_candidates, tract_routes, stock, concept, config, outside)
            sensitivity.append({"profile": name, "parameter": "outside_attractiveness", "value": outside,
                **rank_comparison(huff.huff_opportunities, alternative.huff_opportunities)})
    if file_hash(restaurants_path) != restaurant_hash:
        raise ValueError("Restaurant inventory changed during evaluation")
    for name, records in (("access_ablations", all_ablations), ("borough_coverage", coverage),
                          ("ranking_diagnostics", diagnostics), ("huff_sensitivity", sensitivity)):
        pd.DataFrame(records).to_csv(output / (name + ".csv"), index=False)
    report = {"schema": "model-feature-evaluation-v1", "as_of": today,
        "evaluation_kind": "Full-inventory engineering and scenario sensitivity; not predictive validation",
        "properties": len(properties), "origins": len(origins), "restaurant_rows": len(restaurants),
        "legacy_gap_eligible_rows": len(eligible), "legacy_gap_excluded_active_rows": len(labeled) - len(eligible),
        "profiles": {name: asdict(concept) for name, concept in PROFILES.items()},
        "stage_one": {"status": "blocked", "reason": "No validated empirical artifact and dated outcome cohort available; no survival accuracy or 60/40 result claimed"},
        "huff_scenarios": huff_audits,
        "limitations": [*config["limitations"],
            "Competition located at tract centroids, not restaurant doorways; within-tract variation is lost.",
            "Direct and keyword cuisine mappings are rule-based, not independently verified; ambiguous labels are excluded from Huff but retained in the audit.",
            "The reproduced legacy gap includes original default cuisine guesses; its coverage differs from the stricter Huff inventory.",
            "Candidate attractiveness is fixed at one and substitution weights are assumptions; competitor price, size and quality are unavailable.",
            "Each synthetic entrant is evaluated separately; opportunity values cannot be summed as customer visits.",
            "No consumer preference by ethnicity is inferred from neighborhood demographics.",
            "No access/Huff blend is selected based on these sensitivity checks or deployed as a survival probability."],
        "inputs": {"property_manifest": file_hash(Path(property_run) / "manifest.json"),
            "tract_manifest": file_hash(Path(tract_run) / "manifest.json"),
            "restaurants": {"path": str(restaurants_path), "sha256": restaurant_hash}},
        "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "code_sha256": {name: file_hash(Path(__file__).with_name(name)) for name in
            ("evaluate_model_features.py", "customer_access.py", "network_huff.py", "label_cuisines.py", "cuisine_matrix.py", "make_heatmaps.py")}}
    report["artifacts"] = {path.name: file_hash(path) for path in output.iterdir() if path.is_file()}
    (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--property-run", type=Path, required=True)
    parser.add_argument("--tract-run", type=Path, required=True)
    parser.add_argument("--restaurants", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.property_run, args.tract_run, args.output, args.restaurants), indent=2))
