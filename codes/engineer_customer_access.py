"""Build full-inventory network-access features and reproducible validation artifacts."""

import argparse
from dataclasses import asdict
from datetime import date, datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import platform

import numpy as np
import pandas as pd

from customer_access import (AccessConcept, CONFIG_PATH, access_features, file_hash,
                             load_config, route_matrix, xy)
from paths import DATA, find
from model_feature_catalog import feature_audit


PROFILES = {
    "neighborhood_cafe": AccessConcept("quick_service", 18, "residents", "morning"),
    "office_lunch": AccessConcept("quick_service", 18, "workers", "lunch"),
    "casual_dinner": AccessConcept("casual", 35, "residents", "evening"),
    "premium_dinner": AccessConcept("fine_dining", 110, "destination", "evening"),
}
ROUTING_KEYS = ("walking_meters_per_minute", "max_walk_minutes", "max_snap_meters")


def build(master_path, listing_path, network_path, output, config_path=CONFIG_PATH, reuse=None):
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"Preserving previous artifacts; choose a new output directory: {output}")
    paths = {"master": Path(master_path).resolve(), "listings": Path(listing_path).resolve(),
             "network": Path(network_path).resolve(), "config": Path(config_path).resolve()}
    sources = {key: {"path": str(path), "sha256": file_hash(path)} for key, path in paths.items()}
    config = load_config(config_path)
    origins = pd.read_csv(paths["master"], dtype={"geoid": str})
    candidates = pd.read_csv(paths["listings"], dtype={"geoid": str, "property_id": str})
    if not origins.geoid.str.fullmatch(r"\d{11}").all() or origins.geoid.duplicated().any():
        raise ValueError("Master requires unique 11-digit tract GEOIDs")
    if not candidates.geoid.isin(origins.geoid).all():
        raise ValueError("Candidate tract missing from master")
    if reuse:
        reuse = Path(reuse)
        old = json.loads((reuse / "manifest.json").read_text())
        if any(sources[key]["sha256"] != old["sources"][key]["sha256"] for key in ("master", "listings", "network")):
            raise ValueError("Cached routes do not match pinned input hashes")
        if any(config[key] != old["config"][key] for key in ROUTING_KEYS):
            raise ValueError("Cached routes do not match routing configuration")
        if file_hash(reuse / "routes.npz") != old["artifacts"]["routes.npz"]:
            raise ValueError("Cached route checksum mismatch")
        with np.load(reuse / "routes.npz", allow_pickle=False) as saved:
            if (saved["geoids"].tolist() != origins.geoid.tolist()
                    or saved["property_ids"].tolist() != candidates.property_id.tolist()):
                raise ValueError("Cached route identifiers/order differ")
            distances = saved["distances"]
            network_audit = {"origin_snap_meters": saved["origin_snap_meters"],
                             "candidate_snap_meters": saved["candidate_snap_meters"],
                             "nodes": old["network"]["nodes"], "directed_edges": old["network"]["directed_edges"]}
    else:
        distances, network_audit = route_matrix(origins, candidates, network_path, config, progress=print)
    # Build in memory first; do not expose an incomplete artifact as a valid release.
    outputs = {name: access_features(origins, candidates, distances, concept, config)
               for name, concept in PROFILES.items()}
    base_concept = AccessConcept()
    baseline = access_features(origins, candidates, distances, base_concept, config)
    higher_price = access_features(origins, candidates, distances, AccessConcept(average_check=110), config)
    longer_walk = access_features(origins, candidates, distances, AccessConcept(service_style="fine_dining"), config)
    def nondecreasing(a, b):
        return bool(((b - a).dropna() >= -1e-6).all())
    tests = {
        "candidate_ids_unique": not candidates.property_id.duplicated().any(),
        "full_inventory_rows": all(len(frame) == len(candidates) for frame in outputs.values()),
        "route_shape": distances.shape == (len(candidates), len(origins)),
        "no_negative_routes": not bool((distances < 0).any()),
        "longer_walk_half_life_does_not_reduce_raw_access": nondecreasing(
            baseline.customer_access_opportunities, longer_walk.customer_access_opportunities),
        "higher_price_does_not_increase_raw_price_adjusted_access": nondecreasing(
            higher_price.price_adjusted_access_opportunities, baseline.price_adjusted_access_opportunities),
    }
    finite = np.isfinite(distances)
    straight = np.linalg.norm(xy(candidates.latitude, candidates.longitude)[:, None, :]
                              - xy(origins.centroid_latitude, origins.centroid_longitude)[None, :, :], axis=2)
    impossible = finite & (distances + 25 < straight)
    tests["network_distance_not_shorter_than_straight_by_25m"] = not bool(impossible.any())
    correlations = {}
    master_by_id = origins.set_index("geoid")
    epa = pd.to_numeric(candidates.geoid.map(master_by_id.national_walkability_index), errors="coerce")
    sensitivity = []
    for name, frame in outputs.items():
        values = frame.customer_access_percentile
        valid = values.notna() & epa.notna()
        rho = values[valid].corr(epa[valid], method="spearman") if valid.sum() > 2 else np.nan
        correlations[name] = None if pd.isna(rho) else float(rho)
        original = PROFILES[name]
        top = set(frame.dropna(subset=["inverse_walkability_percentile"]).nlargest(50, "inverse_walkability_percentile").property_id)
        for factor in (0.8, 1.2):
            changed = {**config, "half_life_minutes": {**config["half_life_minutes"],
                        original.service_style: config["half_life_minutes"][original.service_style] * factor}}
            alternative = access_features(origins, candidates, distances, original, changed)
            valid = frame.inverse_walkability_percentile.notna() & alternative.inverse_walkability_percentile.notna()
            rank_rho = frame.loc[valid, "inverse_walkability_percentile"].corr(
                alternative.loc[valid, "inverse_walkability_percentile"], method="spearman") if valid.sum() > 2 else np.nan
            other_top = set(alternative.dropna(subset=["inverse_walkability_percentile"]).nlargest(50, "inverse_walkability_percentile").property_id)
            sensitivity.append({"profile": name, "half_life_multiplier": factor,
                                "rank_spearman": None if pd.isna(rank_rho) else float(rank_rho),
                                "top50_overlap_fraction": len(top & other_top) / len(top) if top else None})
    if not all(tests.values()):
        raise ValueError(f"Feature validation failed: {[key for key, ok in tests.items() if not ok]}")
    for key, path in paths.items():
        if file_hash(path) != sources[key]["sha256"]:
            raise ValueError(f"Input changed while building: {key}")
    output.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(output / "routes.npz", distances=distances,
                        property_ids=candidates.property_id.to_numpy(str), geoids=origins.geoid.to_numpy(str),
                        origin_snap_meters=network_audit["origin_snap_meters"],
                        candidate_snap_meters=network_audit["candidate_snap_meters"])
    for name, frame in outputs.items():
        frame.to_csv(output / f"{name}.csv", index=False)
    context, dictionary, context_audit = feature_audit(origins)
    context.to_csv(output / "current_context_features.csv", index=False)
    dictionary.to_csv(output / "feature_dictionary.csv", index=False)
    (output / "feature_audit.json").write_text(json.dumps(context_audit, indent=2, allow_nan=False) + "\n")
    coverage = {name: {"statuses": frame.status.value_counts().to_dict(),
                       "price_adjusted_available": int(frame.inverse_walkability_percentile.notna().sum()),
                       "median_routing_mass_coverage": float(frame.routing_mass_coverage.median())}
                for name, frame in outputs.items()}
    borough_coverage = {}
    for name, frame in outputs.items():
        grouped = frame.merge(candidates[["property_id", "borough"]], on="property_id") if "borough" in candidates else None
        borough_coverage[name] = (grouped.groupby("borough").agg(
            properties=("property_id", "size"), rated=("inverse_walkability_percentile", "count")).to_dict("index")
            if grouped is not None else {})
    report = {"software_tests": tests, "coverage": coverage, "borough_coverage": borough_coverage, "sensitivity": sensitivity,
              "epa_rank_correlations": correlations,
              "interpretation": "Engineering and sensitivity checks, not predictive accuracy or survival validation",
              "unreachable_pairs": int(np.isinf(distances).sum()),
              "unknown_route_pairs": int(np.isnan(distances).sum()),
              "reachable_pairs": int(finite.sum()), "distance_sanity_failures": int(impossible.sum()),
              "survival_training_status": "Current access features excluded from historical AFT training",
              "limitations": config["limitations"]}
    (output / "validation.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    manifest = {"schema": "customer-access-features-v1", "created_at": datetime.now(timezone.utc).isoformat(),
                "as_of": date.today().isoformat(), "active_master_release": paths["master"].parent.name,
                "sources": sources, "config": config, "profiles": {k: asdict(v) for k, v in PROFILES.items()},
                "network": {key: network_audit[key] for key in ("nodes", "directed_edges")},
                "origin_tracts": len(origins), "candidate_properties": len(candidates),
                "python": platform.python_version(),
                "software": {p: importlib.metadata.version(p) for p in ("numpy", "pandas", "scipy")},
                "code_sha256": {name: file_hash(Path(__file__).with_name(name)) for name in
                                 ("customer_access.py", "engineer_customer_access.py", "model_feature_catalog.py")},
                "artifacts": {p.name: file_hash(p) for p in sorted(output.iterdir()) if p.is_file()}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    return {"output": str(output), "origin_tracts": len(origins), "candidate_properties": len(candidates),
            "coverage": coverage, "checks_passed": all(tests.values())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", type=Path, default=find("master_tract_features.csv"))
    parser.add_argument("--listings", type=Path, default=find("synthetic_properties.csv"))
    parser.add_argument("--network", type=Path, default=DATA / "osm/nyc_walk_network.sqlite")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reuse-routes", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.master, args.listings, args.network, args.output, args.config, args.reuse_routes), indent=2))
