"""Offline 50-concept / three-price screening and walking-Huff evaluation.

Never deploys, trains against synthetic outcomes, or bypasses survival guards.
Each candidate is an independent hypothetical entrant, not simultaneous supply.
"""
import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import shutil
import sys

import h3
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "demo"))
from app import PROFILE_WEIGHTS
from scoring import CUISINES, PRICE_TIERS, Concept, ScreeningModel
from recommend import CUISINES_50
from customer_access import AccessConcept, file_hash, load_access_bundle
from evaluate_matched_results import PARENT, verify_manifest
from network_huff import competitor_stock, network_scenarios

CUISINE_KEYS = (
    "american southern_soul cajun_creole italian french spanish portuguese greek "
    "german_central eastern_european mexican peruvian brazilian colombian venezuelan "
    "cuban dominican puerto_rican jamaican haitian ethiopian west_african indian "
    "pakistani_bangladeshi chinese japanese korean taiwanese thai vietnamese filipino "
    "indonesian_malaysian middle_eastern mediterranean turkish persian_iranian "
    "steakhouse seafood barbecue pizza burgers sandwiches_deli bakery_pastries "
    "coffee_tea desserts_ice_cream salads_bowls breakfast_brunch noodles custom health_focused"
).split()


def taxonomy():
    if len(CUISINE_KEYS) != 50 or len(CUISINES_50) != 50 or len(set(CUISINE_KEYS)) != 50:
        raise ValueError("Expected 50 unique concept categories")
    if set(CUISINE_KEYS) - set(CUISINES):
        raise ValueError("Taxonomy contains unsupported screening keys")
    return list(zip(CUISINES_50, CUISINE_KEYS))


def select_top(frame, score, k):
    """Tie handling is explicit; never call an unavailable score a zero."""
    if k < 1 or frame.property_id.duplicated().any():
        raise ValueError("Use positive k and unique property identities")
    eligible = frame.loc[np.isfinite(pd.to_numeric(frame[score], errors="coerce"))].copy()
    eligible = eligible.sort_values([score, "property_id"], ascending=[False, True]).head(k)
    eligible["rank"] = np.arange(1, len(eligible) + 1)
    return eligible


def frequency_features(selections, method, tier, resolution=8):
    frame = selections[(selections.method == method) & (selections.price_tier == tier)].copy()
    if frame.empty:
        return []
    frame["cell"] = [h3.latlng_to_cell(lat, lon, resolution) for lat, lon in zip(frame.latitude, frame.longitude)]
    features = []
    for cell, group in frame.groupby("cell", sort=True):
        ring = [[lon, lat] for lat, lon in h3.cell_to_boundary(cell)]
        features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring + [ring[0]]]},
            "properties": {"cell": cell, "method": method, "price_tier": tier,
                "selection_count": len(group), "scenario_count": group.scenario_id.nunique(),
                "unique_properties": group.property_id.nunique(), "h3_resolution": resolution}})
    return features


def write_viewer(output, selections, land, holes=()):
    payload = {"selections": json.loads(selections.to_json(orient="records")), "land": land,
               "cuisines": CUISINES_50, "holes": holes,
               "frequency": [f for method in ("screening", "huff") for tier in ("$", "$$", "$$$")
                             for f in frequency_features(selections, method, tier)]}
    template = Path(__file__).with_name("batch_cuisine_heatmaps.html").read_text()
    (output / "heatmaps.html").write_text(template.replace("__SCENARIO_DATA__", json.dumps(payload).replace("</", "<\\/")))


def write_figure(output, selections, land, holes=()):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["text.parse_math"] = False
    from matplotlib.collections import PolyCollection
    from matplotlib.colors import Normalize
    fig, axes = plt.subplots(2, 3, figsize=(14, 11), constrained_layout=True)
    for i, method in enumerate(("screening", "huff")):
        frames = [frequency_features(selections, method, tier) for tier in ("$", "$$", "$$$")]
        norm = Normalize(0, max((f["properties"]["scenario_count"] for fs in frames for f in fs), default=1))
        for ax, tier, features in zip(axes[i], ("$", "$$", "$$$"), frames):
            ax.add_collection(PolyCollection(land, facecolors="#eff1f0", edgecolors="#bec9c7", linewidths=.25))
            if holes:
                ax.add_collection(PolyCollection(holes, facecolors="white", edgecolors="#bec9c7", linewidths=.2))
            collection = PolyCollection([f["geometry"]["coordinates"][0] for f in features],
                array=np.array([f["properties"]["scenario_count"] for f in features]), cmap="YlOrRd", norm=norm,
                edgecolors="#6b3d32", linewidths=.3)
            ax.add_collection(collection)
            ax.set(xlim=(-74.26, -73.69), ylim=(40.49, 40.93), title=f"{method.title()} | {tier} (${PRICE_TIERS[tier]}/guest)")
            ax.set_aspect(1 / np.cos(np.radians(40.7)))
            ax.axis("off")
        fig.colorbar(collection, ax=list(axes[i]), shrink=.7, label="Concept scenarios selecting at least one property in cell (out of 50)")
    fig.suptitle("Where the top-five selections concentrate across 50 restaurant concepts", fontsize=17)
    fig.text(.5, .005, "H3 resolution 8; synthetic inventory; fixed casual / resident / all-day assumptions. Not observed demand or survival accuracy.", ha="center", fontsize=9)
    fig.savefig(output / "selection_heatmaps.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def run(output, top_k=5, style="casual", audience="residents", daypart="all_day"):
    output = Path(output).resolve()
    if output.exists() or not output.is_relative_to(ROOT / "data/output"):
        raise ValueError("Use a new private data/output directory; existing runs are never overwritten")
    if not 1 <= top_k <= 100:
        raise ValueError("top-k must be between 1 and 100")
    categories = taxonomy()
    verify_manifest(PARENT, "run_manifest.json")
    repair = ROOT / "data/output/access_optimization/20261027_v3"
    verify_manifest(repair, key="artifacts")
    bundle = ROOT / "data/output/feature_engineering/20261027_v3"
    tract_bundle = ROOT / "data/output/customer_access_dashboard/20261027_v1/tracts"
    origins, properties, routes, manifest = load_access_bundle(bundle, date.today().isoformat())
    other_origins, tracts, tract_routes, _ = load_access_bundle(tract_bundle, date.today().isoformat())
    if origins.geoid.tolist() != other_origins.geoid.tolist():
        raise ValueError("Competitor and property origin orders differ")
    anchors = pd.read_csv(repair / "competitor_anchors.csv", dtype={"property_id": str, "geoid": str})
    if anchors.property_id.tolist() != tracts.property_id.tolist():
        raise ValueError("Repaired competitor anchor order differs")
    with np.load(repair / "replacement_routes.npz", allow_pickle=False) as patch:
        if patch["geoids"].tolist() != origins.geoid.tolist():
            raise ValueError("Repair origin order differs")
        indices = pd.Index(tracts.property_id).get_indexer(patch["property_ids"].astype(str))
        if (indices < 0).any():
            raise ValueError("Unknown repaired competitor anchor")
        tract_routes[indices] = patch["distances"]
    frozen = PARENT / "frozen_root/data"
    master_path, restaurant_path = frozen / "master_tract_features.csv", frozen / "current_restaurants.csv"
    if file_hash(master_path) != manifest["sources"]["master"]["sha256"]:
        raise ValueError("Screening and network master versions differ")
    if file_hash(restaurant_path) != json.loads((repair / "results.json").read_text())["sources"]["restaurants"]:
        raise ValueError("Competition inventory differs from pinned route repair")
    if not properties.inventory_type.eq("synthetic_demonstration").all():
        raise ValueError("Expected explicitly synthetic demonstration inventory")
    master = pd.read_csv(master_path, dtype={"geoid": str}, keep_default_na=False)
    restaurants = pd.read_csv(restaurant_path, dtype=str, keep_default_na=False)
    model = ScreeningModel(master.to_dict("records"), restaurants.to_dict("records"))
    lookup = master.set_index("geoid").to_dict("index")
    if set(properties.geoid) - set(lookup):
        raise ValueError("Property missing from screening geography")
    profile = {"casual": "restaurant", "quick_service": "counter_service", "fine_dining": "fine_dining"}[style]
    config = manifest["config"]
    AccessConcept(style, 18, audience, daypart).validate(config)
    geography = Path(manifest["sources"]["master"]["path"]).parent / "geography/nyc_2020_census_tracts.geojson"
    from shapely.geometry import shape, mapping
    from shapely.ops import unary_union
    city = unary_union([shape(f["geometry"]) for f in json.loads(geography.read_text())["features"]])
    city_geojson = mapping(city)
    polygons = city_geojson["coordinates"] if city_geojson["type"] == "MultiPolygon" else [city_geojson["coordinates"]]
    land = [polygon[0] for polygon in polygons]
    holes = [ring for polygon in polygons for ring in polygon[1:]]
    tracked_sources = [master_path, restaurant_path, geography, bundle / "manifest.json", bundle / "routes.npz",
        tract_bundle / "manifest.json", tract_bundle / "routes.npz", repair / "manifest.json",
        repair / "replacement_routes.npz", repair / "competitor_anchors.csv", Path(__file__),
        Path(__file__).with_name("batch_cuisine_heatmaps.html"), ROOT / "demo/scoring.py", ROOT / "demo/evidence_policy.py",
        ROOT / "demo/app.py", Path(__file__).with_name("network_huff.py"), Path(__file__).with_name("customer_access.py"),
        Path(__file__).with_name("cuisine_matrix.py"), Path(__file__).with_name("label_cuisines.py")]
    hashes = {str(p): file_hash(p) for p in tracked_sources}
    output.mkdir(parents=True)
    all_frames, selected, summaries, sensitivities = [], [], [], []
    for n, (label, key) in enumerate(categories, 1):
        print(f"{n}/50: {label}", flush=True)
        stock, label_audit, _ = competitor_stock(restaurants, origins.geoid, label)
        prior = None
        for tier in ("$", "$$", "$$$"):
            check = PRICE_TIERS[tier]
            concept = Concept(key, style, check, audience, daypart, tier)
            results = {geoid: model.evaluate({"geoid": geoid, **lookup[geoid]}, concept, PROFILE_WEIGHTS[profile], profile)
                       for geoid in sorted(set(properties.geoid))}
            huff, audit = network_scenarios(origins, properties, routes, anchors, tract_routes, stock,
                AccessConcept(style, check, audience, daypart), config)
            if audit["maximum_choice_mass_error"] > 1e-12 or huff.forecast_visits.notna().any():
                raise ValueError("Huff conservation or nonforecast contract failed")
            frame = properties[["property_id", "geoid", "borough", "neighborhood", "latitude", "longitude", "inventory_type"]].copy()
            frame["scenario_id"] = f"{n:02d}_{len(tier)}"
            frame["cuisine"] = label
            frame["cuisine_key"] = key
            frame["price_tier"], frame["average_check"] = tier, check
            assessments = [results[g] for g in frame.geoid]
            frame["screening_score"] = [r["opportunity"] if r["assessment_policy"]["recommendation_eligible"] else np.nan for r in assessments]
            frame["cuisine_support_mode"] = [r["concept_evidence"]["support"]["mode"] for r in assessments]
            frame["screening_coverage"] = [r["confidence_score"] for r in assessments]
            if frame.property_id.tolist() != huff.property_id.tolist():
                raise ValueError("Huff and screening properties differ")
            frame["huff_opportunities"] = huff.huff_opportunities.to_numpy()
            frame["huff_status"] = huff.status.to_numpy()
            frame["cuisine_separately_classified"] = bool(CUISINES[key])
            for method, column in (("screening", "screening_score"), ("huff", "huff_opportunities")):
                top = select_top(frame, column, top_k)
                top["method"], top["selected_score"] = method, top[column]
                top["tied_at_cutoff"] = int((frame[column] == top[column].iloc[-1]).sum()) if len(top) else 0
                selected.append(top)
                summaries.append({"scenario_id": frame.scenario_id.iloc[0], "cuisine": label, "cuisine_key": key,
                    "price_tier": tier, "average_check": check, "method": method, "assessed": int(frame[column].notna().sum()),
                    "unassessed": int(frame[column].isna().sum()), "selected": len(top),
                    "city_cuisine_classified": bool(CUISINES[key]), "huff_calibrated": False,
                    "label_excluded_rows": label_audit["excluded_rows"], "choice_conservation_error": audit["maximum_choice_mass_error"],
                    "tied_at_cutoff": int(top.tied_at_cutoff.iloc[0]) if len(top) else 0})
                if prior is not None:
                    a = set(select_top(prior, column, top_k).property_id)
                    b = set(top.property_id)
                    common = prior[column].notna() & frame[column].notna()
                    sensitivities.append({"cuisine": label, "method": method, "from_tier": prior.price_tier.iloc[0], "to_tier": tier,
                        "common_assessed": int(common.sum()), "top_k_shared": len(a & b),
                        "top_k_union": len(a | b), "rank_spearman": prior.loc[common, column].corr(frame.loc[common, column], method="spearman")})
            if prior is not None:
                common = prior.huff_opportunities.notna() & frame.huff_opportunities.notna()
                if (frame.loc[common, "huff_opportunities"] > prior.loc[common, "huff_opportunities"] + 1e-7).any():
                    raise ValueError("Higher guest price increased captured affordability-adjusted mass")
            prior = frame
            all_frames.append(frame)
    scores, selections = pd.concat(all_frames, ignore_index=True), pd.concat(selected, ignore_index=True)
    scores.to_csv(output / "all_scores.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    selections.to_csv(output / "top_selections.csv", index=False)
    pd.DataFrame(summaries).to_csv(output / "scenario_summary.csv", index=False)
    pd.DataFrame(sensitivities).to_csv(output / "price_sensitivity.csv", index=False)
    frequencies = [f for method in ("screening", "huff") for tier in ("$", "$$", "$$$")
                   for f in frequency_features(selections, method, tier)]
    (output / "selection_frequency.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": frequencies}))
    write_viewer(output, selections, land, holes)
    write_figure(output, selections, land, holes)
    duplicates = []
    for method in ("screening", "huff"):
        for tier in ("$", "$$", "$$$"):
            sub = selections[(selections.method == method) & (selections.price_tier == tier)]
            signatures = sub.sort_values("rank").groupby("cuisine").property_id.agg(tuple)
            groups = {}
            for label, signature in signatures.items():
                groups.setdefault(signature, []).append(label)
            for labels in groups.values():
                if len(labels) > 1:
                    duplicates.append({"method": method, "price_tier": tier, "cuisines_with_identical_ordered_top_k": labels})
    for path, digest in hashes.items():
        if file_hash(path) != digest:
            raise ValueError("Input changed during batch: " + path)
    report = {"status": "completed_offline_scenario_audit", "scenarios": len(categories) * 3,
        "candidate_properties": len(properties), "origin_tracts": len(origins), "score_rows": len(scores),
        "selection_rows": len(selections), "top_k": top_k, "source_as_of": manifest["as_of"],
        "held_fixed": {"style": style, "audience": audience, "daypart": daypart, "screening_profile": profile},
        "tiers": {t: PRICE_TIERS[t] for t in ("$", "$$", "$$$")},
        "no_separate_source_classification": [label for label, key in categories if not CUISINES[key]],
        "identical_selection_groups": duplicates, "production_changed": False, "survival_accuracy_improvement_claimed": False,
        "limitations": ["Synthetic properties; no verified real-time listings or observed visits/sales.",
            "Screening and Huff are separate scenario rankings, not a newly calibrated combined model.",
            "Stage-one survival is cuisine/price-independent and is not rerun or promoted here.",
            "Huff uses related-category and name-label assumptions; screening fallback flags remain visible.",
            "Supply categories and inferred names do not establish cuisine-specific consumer preferences.",
            "Fixed style isolates price; tiers are hypothetical checks, not observed menu prices or rent budgets.",
            "No rent/size/transaction eligibility filter is applied in this unconstrained comparison.",
            "Screening is tract-based: co-tract properties can tie; property ID breaks ties reproducibly.",
            "Heatmap frequency reflects this fixed inventory and scenario grid, not citywide demand.",
            "No predictive model improvement can be inferred without independent outcomes."]}
    (output / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    for path in (Path(__file__), Path(__file__).with_name("batch_cuisine_heatmaps.html")):
        shutil.copy2(path, output / path.name)
    (output / "manifest.json").write_text(json.dumps({"created_at": datetime.now(timezone.utc).isoformat(),
        "input_sha256": hashes, "artifact_sha256": {p.name: file_hash(p) for p in output.iterdir() if p.is_file()}}, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("scenarios", "candidate_properties", "score_rows", "selection_rows")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--style", choices=("casual", "quick_service", "fine_dining"), default="casual")
    parser.add_argument("--audience", choices=("residents", "workers", "destination"), default="residents")
    parser.add_argument("--daypart", choices=("all_day", "morning", "lunch", "evening"), default="all_day")
    args = parser.parse_args()
    run(args.output, args.top_k, args.style, args.audience, args.daypart)
