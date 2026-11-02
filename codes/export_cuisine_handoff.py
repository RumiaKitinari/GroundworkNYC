"""Export an allowlisted, static team handoff without private training inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "data/output/background_tests"
SOURCES = {
    "scenarios": ("20261102_cuisine_price_batch_v3", [
        "all_scores.csv.gz", "top_selections.csv", "scenario_summary.csv", "price_sensitivity.csv",
        "selection_frequency.geojson", "results.json", "independent_checks.json", "independent_selection_concentration.csv"]),
    "maps": ("20261102_cuisine_batch_maps_v1", ["heatmaps.html", "selection_heatmaps.png"]),
    "competition_stress": ("20261102_cuisine_competition_stress_v2", [
        "competition_sensitivity.csv", "candidate_sensitivity.csv.gz", "results.json"]),
    "stage_one_control": ("20261102_cuisine_stage_one_v1", [
        "property_archive_proxy.csv", "all_scenarios_with_stage_one.csv.gz", "selected_locations_with_stage_one.csv",
        "stage_one_provenance.json", "results.json"]),
    "frozen_stage_one_evaluation": ("20261101_locked_results_v1", [
        "primary_metrics.json", "primary_results_table.csv", "primary_paired_comparisons.json", "results_for_briefing.png"]),
    "checks": ("20261102_cuisine_price_batch_qa", ["browser_checks.json"]),
}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def export(output):
    output = Path(output).resolve()
    if output.exists() or not output.is_relative_to(ROOT / "reports"):
        raise ValueError("Use a new reports/ subdirectory; existing exports are not overwritten")
    selected = []
    for section, (run, names) in SOURCES.items():
        source = RUNS / run
        if section not in {"checks", "frozen_stage_one_evaluation"}:
            manifest = json.loads((source / "manifest.json").read_text())
            for name, expected in manifest["artifact_sha256"].items():
                if digest(source / name) != expected:
                    raise ValueError("Completed run changed: " + str(source / name))
        for name in names:
            path = source / name
            if not path.is_file() or path.stat().st_size > 25_000_000:
                raise ValueError("Missing or oversized handoff artifact: " + str(path))
            selected.append((path, Path(section) / name))
    for source, relative in selected:
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    records = [{"path": str(relative), "sha256": digest(output / relative), "bytes": (output / relative).stat().st_size,
                "source_run": str(source.parent.relative_to(ROOT))} for source, relative in selected]
    (output / "artifact_manifest.json").write_text(json.dumps({
        "schema": "groundwork-static-team-handoff-v1", "date": "2026-11-02", "artifacts": records,
        "privacy_scope": "Generated property/scenario outputs and aggregate evaluation only. No raw restaurant cohort, accounts, credentials, model binaries or route matrices.",
        "production_changed": False, "verified_survival": False}, indent=2) + "\n")
    print(json.dumps({"files": len(records), "bytes": sum(record["bytes"] for record in records), "directory": str(output)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    export(parser.parse_args().output)
