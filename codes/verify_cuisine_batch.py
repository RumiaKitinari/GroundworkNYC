"""Independently check a completed batch and quantify selection concentration."""
import argparse
import json
from pathlib import Path

import h3
import numpy as np
import pandas as pd

from customer_access import file_hash


def verify(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / "manifest.json").read_text())
    for name, digest in manifest["artifact_sha256"].items():
        if file_hash(directory / name) != digest:
            raise ValueError("Batch artifact changed: " + name)
    for name, digest in manifest["input_sha256"].items():
        if file_hash(name) != digest:
            raise ValueError("Batch input changed: " + name)
    report = json.loads((directory / "results.json").read_text())
    scores = pd.read_csv(directory / "all_scores.csv.gz", dtype={"geoid": str, "property_id": str, "scenario_id": str})
    selected = pd.read_csv(directory / "top_selections.csv", dtype={"geoid": str, "property_id": str, "scenario_id": str})
    summary = pd.read_csv(directory / "scenario_summary.csv")
    k = report["top_k"]
    if (len(scores) != report["scenarios"] * report["candidate_properties"]
            or scores.duplicated(["scenario_id", "property_id"]).any()
            or scores.scenario_id.nunique() != 150 or scores.cuisine.nunique() != 50
            or set(scores.price_tier) != {"$", "$$", "$$$"}
            or not scores.inventory_type.eq("synthetic_demonstration").all()):
        raise ValueError("Inventory or scenario coverage contract failed")
    concentration = []
    for scenario, frame in scores.groupby("scenario_id", sort=True):
        for method, column in (("screening", "screening_score"), ("huff", "huff_opportunities")):
            available = frame[np.isfinite(frame[column])].sort_values([column, "property_id"], ascending=[False, True])
            expected = available.head(k)
            actual = selected[(selected.scenario_id == scenario) & (selected.method == method)].sort_values("rank")
            if expected.property_id.tolist() != actual.property_id.tolist():
                raise ValueError("Selections do not match full-inventory ranks")
            if not np.allclose(expected[column], actual.selected_score):
                raise ValueError("Selection scores do not match candidate scores")
            diverse = available.drop_duplicates("geoid").head(k)
            concentration.append({"scenario_id": scenario, "method": method, "cuisine": frame.cuisine.iloc[0],
                "price_tier": frame.price_tier.iloc[0], "selected_properties": len(actual),
                "unique_selected_tracts": actual.geoid.nunique(), "unique_selected_boroughs": actual.borough.nunique(),
                "distinct_area_alternative": diverse.property_id.tolist()})
    frequencies = json.loads((directory / "selection_frequency.geojson").read_text())["features"]
    independent = {}
    for row in selected.itertuples():
        key = (row.method, row.price_tier, h3.latlng_to_cell(row.latitude, row.longitude, 8))
        entry = independent.setdefault(key, {"count": 0, "scenarios": set(), "properties": set()})
        entry["count"] += 1
        entry["scenarios"].add(row.scenario_id)
        entry["properties"].add(row.property_id)
    if len(independent) != len(frequencies):
        raise ValueError("Heatmap cell count differs")
    for f in frequencies:
        p = f["properties"]
        entry = independent[(p["method"], p["price_tier"], p["cell"])]
        if (p["selection_count"] != entry["count"] or p["scenario_count"] != len(entry["scenarios"])
                or p["unique_properties"] != len(entry["properties"])):
            raise ValueError("Heatmap counts differ from actual selected locations")
    price = pd.read_csv(directory / "price_sensitivity.csv")
    if len(price) != 200 or len(summary) != 300 or summary.choice_conservation_error.max() > 1e-12:
        raise ValueError("Missing comparisons or failed choice conservation")
    concentration_frame = pd.DataFrame(concentration)
    concentration_frame.to_csv(directory / "independent_selection_concentration.csv", index=False)
    findings = {"status": "passed", "candidate_scenario_rows": len(scores), "selection_rows": len(selected),
        "scenario_method_checks": 300, "frequency_cells_checked": len(frequencies),
        "input_and_artifact_hashes_verified": True,
        "methods": {method: {
            "unique_selected_properties": int(selected.loc[selected.method == method, "property_id"].nunique()),
            "unique_selected_tracts": int(selected.loc[selected.method == method, "geoid"].nunique()),
            "scenarios_fewer_than_five_distinct_tracts": int((concentration_frame.loc[concentration_frame.method == method, "unique_selected_tracts"] < k).sum()),
            "price_transitions_changing_top_five": int((price.loc[price.method == method, "top_k_shared"] < k).sum()),
            "price_transitions_checked": int((price.method == method).sum()),
            "median_rank_correlation_between_adjacent_prices": float(price.loc[price.method == method, "rank_spearman"].median()),
            "minimum_assessed_properties": int(summary.loc[summary.method == method, "assessed"].min())}
            for method in ("screening", "huff")},
        "no_separate_source_classification": report["no_separate_source_classification"],
        "note": "Distinct-area alternatives are diagnostics, not a silent change to production selection."}
    (directory / "independent_checks.json").write_text(json.dumps(findings, indent=2, allow_nan=False) + "\n")
    print(json.dumps(findings, indent=2, allow_nan=False))
    return findings


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    verify(parser.parse_args().directory)
