"""Uncertain-competitor stress test; an assumption range, not confidence bounds."""
import argparse
from datetime import date
import json
from pathlib import Path

import numpy as np
import pandas as pd

from batch_cuisine_scenarios import ROOT, PARENT, select_top
from customer_access import AccessConcept, file_hash, load_access_bundle
from evaluate_matched_results import verify_manifest
from network_huff import competitor_stock, network_scenarios


def run(batch, output):
    batch, output = Path(batch).resolve(), Path(output).resolve()
    if output.exists() or not output.is_relative_to(ROOT / "data/output"):
        raise ValueError("Use a new private output directory")
    verify_manifest(batch)
    plan = json.loads((batch / "results.json").read_text())
    saved = pd.read_csv(batch / "all_scores.csv.gz", dtype={"geoid": str, "property_id": str})
    saved = saved[saved.price_tier.eq("$$")]
    bundle = ROOT / "data/output/feature_engineering/20261027_v3"
    tract_bundle = ROOT / "data/output/customer_access_dashboard/20261027_v1/tracts"
    repair = ROOT / "data/output/access_optimization/20261027_v3"
    verify_manifest(repair, key="artifacts")
    origins, properties, property_routes, manifest = load_access_bundle(bundle, date.today().isoformat())
    other, tracts, tract_routes, _ = load_access_bundle(tract_bundle, date.today().isoformat())
    if origins.geoid.tolist() != other.geoid.tolist():
        raise ValueError("Origin order differs")
    anchors = pd.read_csv(repair / "competitor_anchors.csv", dtype={"property_id": str})
    if tracts.property_id.tolist() != anchors.property_id.tolist():
        raise ValueError("Competitor anchor order differs")
    with np.load(repair / "replacement_routes.npz", allow_pickle=False) as patch:
        indices = pd.Index(tracts.property_id).get_indexer(patch["property_ids"].astype(str))
        if (indices < 0).any() or patch["geoids"].tolist() != origins.geoid.tolist():
            raise ValueError("Repair identifiers differ")
        tract_routes[indices] = patch["distances"]
    restaurant_path = PARENT / "frozen_root/data/current_restaurants.csv"
    restaurants = pd.read_csv(restaurant_path, dtype=str, keep_default_na=False)
    if file_hash(restaurant_path) != json.loads((repair / "results.json").read_text())["sources"]["restaurants"]:
        raise ValueError("Competition inventory differs")
    held = plan["held_fixed"]
    concept = AccessConcept(held["style"], plan["tiers"]["$$"], held["audience"], held["daypart"])
    output.mkdir(parents=True)
    results, details = [], []
    for n, (cuisine, base) in enumerate(saved.groupby("cuisine", sort=True), 1):
        print(f"Uncertain competition {n}/50: {cuisine}", flush=True)
        base = base.set_index("property_id").loc[properties.property_id].reset_index()
        stock, audit, labels = competitor_stock(restaurants, origins.geoid, cuisine)
        uncertain = labels[~labels.used_in_scenario & labels.geoid.isin(origins.geoid)]
        extra = uncertain.groupby("geoid").size().reindex(origins.geoid, fill_value=0).to_numpy(float)
        known, _ = network_scenarios(origins, properties, property_routes, anchors, tract_routes, stock, concept, manifest["config"])
        if not np.allclose(known.huff_opportunities, base.huff_opportunities, equal_nan=True, atol=1e-8, rtol=1e-10):
            raise ValueError("Saved batch Huff result cannot be reproduced")
        stress, _ = network_scenarios(origins, properties, property_routes, anchors, tract_routes, stock + extra, concept, manifest["config"])
        common = base.huff_opportunities.notna() & stress.huff_opportunities.notna()
        if (stress.loc[common, "huff_opportunities"] > base.loc[common, "huff_opportunities"] + 1e-7).any():
            raise ValueError("More competitors increased candidate opportunity mass")
        first = select_top(base, "huff_opportunities", plan["top_k"])
        second = select_top(stress, "huff_opportunities", plan["top_k"])
        shared = len(set(first.property_id) & set(second.property_id))
        before = base.loc[common, "huff_opportunities"]
        relative = (stress.loc[common, "huff_opportunities"] / before.where(before > 0) - 1) * 100
        results.append({"cuisine": cuisine, "price_tier": "$$", "average_check": concept.average_check,
            "active_inventory": audit["active_rows"], "uncertain_competitors_added": int(extra.sum()),
            "base_rated": int(base.huff_opportunities.notna().sum()), "stress_rated": int(stress.huff_opportunities.notna().sum()),
            "newly_withheld_candidates": int((base.huff_opportunities.notna() & stress.huff_opportunities.isna()).sum()),
            "common_rated": int(common.sum()), "top_five_shared": shared, "stress_selected": len(second),
            "median_common_opportunity_change_pct": float(relative.median()) if relative.notna().any() else None})
        detail = properties[["property_id", "geoid"]].copy()
        detail["cuisine"] = cuisine
        detail["base_huff"] = base.huff_opportunities
        detail["uncertain_competitor_huff"] = stress.huff_opportunities
        detail["stress_status"] = stress.status
        details.append(detail)
    frame = pd.DataFrame(results)
    frame.to_csv(output / "competition_sensitivity.csv", index=False)
    pd.concat(details, ignore_index=True).to_csv(output / "candidate_sensitivity.csv.gz", index=False)
    report = {"status": "completed", "cuisines_tested": len(frame), "price": concept.average_check,
        "all_five_selections_retained": int(frame.top_five_shared.eq(5).sum()),
        "at_least_one_selection_changed": int(frame.top_five_shared.lt(5).sum()),
        "median_shared_top_five": float(frame.top_five_shared.median()),
        "maximum_newly_withheld_candidates": int(frame.newly_withheld_candidates.max()),
        "median_opportunity_change_pct_across_cuisines": float(frame.median_common_opportunity_change_pct.median()),
        "scope": "Unlabeled/weakly labeled matched active restaurants counted as full competitors, separately for every cuisine.",
        "limitations": ["Deliberately conservative scenario; not a claim that unknown restaurants serve every cuisine.",
            "Not an uncertainty interval or evidence of predictive accuracy.",
            "Active restaurants lacking usable tract matches remain outside this calculation.",
            "Top-five changes can reflect coverage withholding as well as changed ordering.",
            "No production ranking or trained model was changed."]}
    (output / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    (output / "manifest.json").write_text(json.dumps({"input_sha256": {str(batch / "manifest.json"): file_hash(batch / "manifest.json"),
        str(Path(__file__)): file_hash(Path(__file__))},
        "artifact_sha256": {p.name: file_hash(p) for p in output.iterdir() if p.is_file()}}, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(args.batch, args.output)
