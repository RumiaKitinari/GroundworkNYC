"""Offline competitor-anchor repair and full-inventory scenario sensitivity.

Population origins and property routes never move. Only failed competitor
centroid destinations may use an observed same-tract restaurant within 500 m.
No routing gap or unknown cuisine is treated as evidence of absent supply.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3

import numpy as np
import pandas as pd

from customer_access import AccessConcept, file_hash, load_access_bundle, route_matrix, xy
from network_huff import competitor_stock, network_scenarios

ROOT = Path(__file__).resolve().parents[1]


def choose_anchors(origins, candidates, restaurants, bad, db, max_shift=500, max_snap=200):
    replacements, audit = [], []
    active = restaurants[restaurants.active_establishment.astype(str).str.lower().isin(["true", "1"])].copy()
    for index in np.flatnonzero(bad):
        original = candidates.iloc[index]
        pool = active[active.geoid.eq(str(original.property_id))].copy()
        lat = pd.to_numeric(pool.latitude, errors="coerce")
        lon = pd.to_numeric(pool.longitude, errors="coerce")
        pool = pool[lat.between(40.45, 40.96) & lon.between(-74.31, -73.64)].copy()
        pool["shift_meters"] = np.linalg.norm(xy(pool.latitude, pool.longitude) - xy([original.latitude], [original.longitude]), axis=1)
        pool = pool[pool.shift_meters.le(max_shift)].sort_values(["shift_meters", "camis"])
        record = {"index": int(index), "geoid": str(original.property_id), "old_latitude": float(original.latitude),
                  "old_longitude": float(original.longitude), "status": "no_supported_replacement"}
        for row in pool.itertuples():
            latitude, longitude = float(row.latitude), float(row.longitude)
            nodes = db.execute("SELECT n.latitude,n.longitude FROM nodes n JOIN node_index r ON n.id=r.id "
                               "WHERE r.min_lon BETWEEN ? AND ? AND r.min_lat BETWEEN ? AND ?",
                               (longitude-.004, longitude+.004, latitude-.003, latitude+.003)).fetchall()
            if not nodes:
                continue
            nodes = np.asarray(nodes)
            snap = float(np.linalg.norm(xy(nodes[:, 0], nodes[:, 1]) - xy([latitude], [longitude]), axis=1).min())
            if snap > max_snap:
                continue
            replacement = original.to_dict()
            replacement.update(latitude=latitude, longitude=longitude)
            replacements.append(replacement)
            record.update(status="observed_restaurant_anchor", camis=str(row.camis), latitude=latitude,
                          longitude=longitude, shift_meters=float(row.shift_meters), snap_meters=snap)
            break
        audit.append(record)
    return pd.DataFrame(replacements, columns=candidates.columns), pd.DataFrame(audit)


def comparison(reference, candidate):
    common = reference.notna() & candidate.notna()
    ref_top = set(reference[common].nlargest(50).index)
    new_top = set(candidate[common].nlargest(50).index)
    return {"rated": int(candidate.notna().sum()), "common_rated": int(common.sum()),
            "spearman_common": float(reference[common].corr(candidate[common], method="spearman")) if common.sum() > 1 else None,
            "top_50_common_retention": len(ref_top & new_top) / len(ref_top) if ref_top else None}


def run(output):
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT / "data/output") or output.exists():
        raise ValueError("Use a new private data/output directory")
    property_dir = ROOT / "data/output/feature_engineering/20261027_v3"
    tract_dir = ROOT / "data/output/customer_access_dashboard/20261027_v1/tracts"
    origins, properties, property_routes, manifest = load_access_bundle(property_dir, "2026-10-27")
    other_origins, tracts, tract_routes, tract_manifest = load_access_bundle(tract_dir, "2026-10-27")
    if origins.geoid.tolist() != other_origins.geoid.tolist():
        raise ValueError("Origin order differs")
    config = manifest["config"]
    network = Path(tract_manifest["sources"]["network"]["path"])
    if file_hash(network) != tract_manifest["sources"]["network"]["sha256"]:
        raise ValueError("Walking graph changed")
    restaurant_path = Path(manifest["sources"]["master"]["path"]).with_name("entities") / "current_restaurants.csv"
    if not restaurant_path.exists():
        restaurant_path = Path(manifest["sources"]["master"]["path"]).with_name("current_restaurants.csv")
    restaurants = pd.read_csv(restaurant_path, dtype={"camis": str, "geoid": str})
    restaurant_hash = file_hash(restaurant_path)
    with np.load(tract_dir / "routes.npz", allow_pickle=False) as saved:
        bad = saved["candidate_snap_meters"] > config["max_snap_meters"]
    output.mkdir(parents=True)
    for name in ("audit_access_optimization.py", "network_huff.py", "customer_access.py", "cuisine_matrix.py", "label_cuisines.py"):
        shutil.copy2(Path(__file__).with_name(name), output / name)
    with sqlite3.connect(f"file:{network}?mode=ro", uri=True) as db:
        replacements, audit = choose_anchors(origins, tracts, restaurants, bad, db,
                                              max_snap=config["max_snap_meters"])
    audit.to_csv(output / "anchor_audit.csv", index=False)
    repaired_tracts, repaired_routes = tracts.copy(), tract_routes.copy()
    if len(replacements):
        print(f"Routing {len(replacements)} observed competitor anchors", flush=True)
        patch, routing_audit = route_matrix(origins, replacements, network, config)
        if np.isnan(patch).all(axis=1).any():
            raise ValueError("Replacement did not connect to the walking graph")
        indices = pd.Index(tracts.property_id).get_indexer(replacements.property_id)
        repaired_routes[indices] = patch
        repaired_tracts.loc[indices, ["latitude", "longitude"]] = replacements[["latitude", "longitude"]].to_numpy()
        np.savez_compressed(output / "replacement_routes.npz", property_ids=replacements.property_id.to_numpy(str),
                            geoids=origins.geoid.to_numpy(str), distances=patch,
                            origin_snap_meters=routing_audit["origin_snap_meters"],
                            candidate_snap_meters=routing_audit["candidate_snap_meters"])
    repaired_tracts.to_csv(output / "competitor_anchors.csv", index=False)
    profiles = {"neighborhood_cafe": ("Coffee / Tea", AccessConcept("quick_service",18,"residents","morning")),
                "office_lunch": ("Sandwiches / Deli", AccessConcept("quick_service",18,"workers","lunch")),
                "casual_dinner": ("Italian", AccessConcept("casual",35,"residents","evening")),
                "premium_dinner": ("Steakhouse", AccessConcept("fine_dining",110,"destination","evening"))}
    report = {}
    for name, (cuisine, concept) in profiles.items():
        print(f"Full inventory: {name}", flush=True)
        stock, label_audit, labels = competitor_stock(restaurants, origins.geoid, cuisine)
        baseline, before = network_scenarios(origins, properties, property_routes, tracts, tract_routes, stock, concept, config)
        repaired, after = network_scenarios(origins, properties, property_routes, repaired_tracts, repaired_routes, stock, concept, config)
        values = repaired.huff_opportunities
        scenarios = []
        for factor in (.8, 1.2):
            changed = deepcopy(config)
            changed["half_life_minutes"][concept.service_style] *= factor
            frame, _ = network_scenarios(origins, properties, property_routes, repaired_tracts, repaired_routes, stock, concept, changed)
            scenarios.append({"parameter": "walking_half_life", "factor": factor, **comparison(values, frame.huff_opportunities)})
        for outside in (.5, 2.):
            frame, _ = network_scenarios(origins, properties, property_routes, repaired_tracts, repaired_routes, stock, concept, config, outside=outside)
            scenarios.append({"parameter": "outside_option", "value": outside, **comparison(values, frame.huff_opportunities)})
        for factor in (.8, 1.2):
            changed_concept = AccessConcept(concept.service_style,concept.average_check*factor,concept.audience,concept.daypart)
            frame, _ = network_scenarios(origins, properties, property_routes, repaired_tracts, repaired_routes, stock, changed_concept, config)
            scenarios.append({"parameter": "average_check", "factor": factor, **comparison(values, frame.huff_opportunities)})
        uncertain = labels[~labels.used_in_scenario & labels.geoid.isin(origins.geoid)]
        extra = uncertain.groupby("geoid").size().reindex(origins.geoid, fill_value=0).to_numpy(float)
        frame, _ = network_scenarios(origins, properties, property_routes, repaired_tracts, repaired_routes, stock+extra, concept, config)
        scenarios.append({"parameter": "all_uncertain_labels_as_full_competitors", "additional_competitors": int(extra.sum()),
                          **comparison(values, frame.huff_opportunities), "interpretation": "Conservative scenario, not inferred cuisine or a confidence interval"})
        pd.DataFrame({"property_id": properties.property_id, "geoid": properties.geoid,
                      "original_opportunities": baseline.huff_opportunities, "repaired_opportunities": values,
                      "uncertain_competition_opportunities": frame.huff_opportunities,
                      "original_status": baseline.status, "repaired_status": repaired.status}).to_csv(output / f"{name}.csv", index=False)
        report[name] = {"cuisine": cuisine, "baseline_rated": int(baseline.huff_opportunities.notna().sum()),
                        "anchor_comparison": comparison(baseline.huff_opportunities, values),
                        "before": before, "after": after, "label_audit": label_audit, "sensitivities": scenarios}
    unmatched = restaurants[restaurants.active_establishment.astype(str).str.lower().isin(["true","1"]) & ~restaurants.geoid.isin(origins.geoid)].copy()
    unmatched["usable_nyc_coordinates"] = pd.to_numeric(unmatched.latitude, errors="coerce").between(40.45,40.96) & pd.to_numeric(unmatched.longitude, errors="coerce").between(-74.31,-73.64)
    unmatched.to_csv(output / "unmatched_active_restaurants.csv", index=False)
    if file_hash(network) != tract_manifest["sources"]["network"]["sha256"] or file_hash(restaurant_path) != restaurant_hash:
        raise ValueError("Pinned inputs changed during audit")
    result = {"schema": "offline-access-optimization-v1", "created_at": datetime.now(timezone.utc).isoformat(),
              "failed_centroid_targets": int(bad.sum()), "replaced_targets": len(replacements),
              "maximum_anchor_shift_meters": 500, "maximum_road_snap_meters": config["max_snap_meters"],
              "population_origins_unchanged": True, "property_routes_unchanged": True,
              "unmatched_active_rows": len(unmatched), "unmatched_with_coordinates": int(unmatched.usable_nyc_coordinates.sum()),
              "profiles": report, "deployed": False, "calibrated": False,
              "sources": {"properties_manifest": file_hash(property_dir / "manifest.json"),
                          "tract_manifest": file_hash(tract_dir / "manifest.json"), "restaurants": restaurant_hash,
                          "network": file_hash(network)},
              "limitations": ["Same-tract observed restaurant anchors approximate aggregated competitor positions.",
                              "Population centroid failures remain; no origins were relocated.",
                              "Current walking graph and synthetic properties are prospective scenario inputs only.",
                              "No observed visits are available to select optimal Huff parameters."]}
    (output / "results.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    snapshot = {name: file_hash(Path(__file__).with_name(name)) for name in ("audit_access_optimization.py","network_huff.py","customer_access.py")}
    (output / "manifest.json").write_text(json.dumps({"status":"completed", "code":snapshot,
        "artifacts": {p.name:file_hash(p) for p in output.iterdir() if p.is_file()}}, indent=2)+"\n")
    print(json.dumps({"replaced_targets":len(replacements), "rated":{k:v["anchor_comparison"]["rated"] for k,v in report.items()}},indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    run(parser.parse_args().output)
