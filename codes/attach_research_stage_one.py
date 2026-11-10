"""Attach guarded archive-proxy outputs without inventing a calibrated blend."""
import argparse
from datetime import date
import importlib.util
import json
from pathlib import Path

import pandas as pd

from batch_cuisine_scenarios import ROOT
from customer_access import file_hash
from evaluate_matched_results import verify_manifest


def run(batch, bundle, output, acknowledgement):
    batch, bundle, output = map(lambda p: Path(p).resolve(), (batch, bundle, output))
    if output.exists() or not output.is_relative_to(ROOT / "data/output"):
        raise ValueError("Use a new private output directory")
    if acknowledgement != "archive_proxy_not_verified_survival":
        raise ValueError("Explicit acknowledgement of unverified archive-proxy target required")
    verify_manifest(batch)
    spec = importlib.util.spec_from_file_location("guarded_archive_inference", bundle / "research_inference.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = module.OfflineResearchBundle(bundle, acknowledgement)
    scores = pd.read_csv(batch / "all_scores.csv.gz", dtype={"property_id": str, "geoid": str})
    properties = scores[["property_id", "geoid"]].drop_duplicates()
    if properties.property_id.duplicated().any():
        raise ValueError("Property identity changes tract between scenarios")
    as_of = date.today().isoformat()
    predictions = engine.predict([{"business_id": row.property_id, "geoid": row.geoid, "as_of_date": as_of}
                                  for row in properties.itertuples()])
    if any(r["production_allowed"] or r["verified_survival"] for r in predictions):
        raise ValueError("Research policy unexpectedly allows production")
    frame = pd.DataFrame([{key: row[key] for key in ("business_id", "geoid", "status", "proxy_median_years", "proxy_aft_survival_3yr")}
                          for row in predictions]).rename(columns={"business_id": "property_id"})
    frame = frame.rename(columns={"status": "stage_one_research_status"})
    merged = scores.merge(frame, on=["property_id", "geoid"], how="left", validate="many_to_one")
    if merged.stage_one_research_status.isna().any():
        raise ValueError("Scenario missing a stage-one assessment")
    if (merged.groupby("property_id").proxy_median_years.nunique() > 1).any():
        raise ValueError("Stage-one output unexpectedly changes by cuisine or price")
    output.mkdir(parents=True)
    frame.to_csv(output / "property_archive_proxy.csv", index=False)
    merged.to_csv(output / "all_scenarios_with_stage_one.csv.gz", index=False)
    selected = pd.read_csv(batch / "top_selections.csv", dtype={"property_id": str, "geoid": str})
    selected.merge(frame, on=["property_id", "geoid"], how="left", validate="many_to_one").to_csv(output / "selected_locations_with_stage_one.csv", index=False)
    (output / "stage_one_provenance.json").write_text(json.dumps(predictions, indent=2, allow_nan=False) + "\n")
    report = {"status": "completed_offline_research_only", "property_calls": len(properties), "scenario_rows": len(merged),
        "stage_one_covered_properties": int(frame.proxy_median_years.notna().sum()), "as_of_date": as_of,
        "stage_one_invariant_across_cuisines_and_prices": True, "production_allowed": False,
        "interpretation": "Frozen dated-core archive-proxy AFT control; not independently verified permanent-closure survival.",
        "combined_score_created": False,
        "limitations": ["Reusing a saved model on hypothetical sites does not validate that model or establish opening-date accuracy.",
            "Cuisine and guest price are not first-stage inputs; only the second-stage scenario components respond to them.",
            "No unsupported survival/Huff blending weights were invented or deployed."]}
    (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "manifest.json").write_text(json.dumps({"input_sha256": {
        str(batch / "manifest.json"): file_hash(batch / "manifest.json"),
        str(bundle / "bundle_manifest.json"): file_hash(bundle / "bundle_manifest.json"), str(Path(__file__)): file_hash(Path(__file__))},
        "artifact_sha256": {p.name: file_hash(p) for p in output.iterdir() if p.is_file()}}, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True)
    parser.add_argument("--research-bundle", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--acknowledge", required=True)
    args = parser.parse_args()
    run(args.batch, args.research_bundle, args.output, args.acknowledge)
