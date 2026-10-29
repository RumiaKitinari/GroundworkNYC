"""Freeze and rerun archive-proxy research without changing verified-model guards."""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pandas as pd

from customer_access import file_hash
from paths import find

ROOT = Path(__file__).resolve().parents[1]


def execute(name, command, environment, directory, log_directory):
    print(f"\n[{name}] starting", flush=True)
    with (log_directory / (name + ".log")).open("x") as log:
        process = subprocess.Popen(command, cwd=directory, env=environment, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in process.stdout:
            log.write(line)
            log.flush()
            print(line.rstrip(), flush=True)
        if process.wait():
            raise RuntimeError(f"{name} failed; inspect {log_directory / (name + '.log')}")


def copy_scenarios(source, destination, frozen):
    source = Path(source)
    report = json.loads((source / "report.json").read_text())
    for name, digest in report["artifacts"].items():
        if file_hash(source / name) != digest:
            raise ValueError("Scenario artifact checksum mismatch: " + name)
    manifest_path = ROOT / "data/output/feature_engineering/20261027_v3/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if report["inputs"]["property_manifest"] != file_hash(manifest_path):
        raise ValueError("Scenario input manifest changed")
    for key, filename in (("master", "master_tract_features.csv"), ("listings", "synthetic_properties.csv")):
        if manifest["sources"][key]["sha256"] != file_hash(frozen / filename):
            raise ValueError("Scenario and training input versions differ: " + key)
    if report["inputs"]["restaurants"]["sha256"] != file_hash(frozen / "current_restaurants.csv"):
        raise ValueError("Scenario and current restaurant input versions differ")
    shutil.copytree(source, destination)


def combine_scenarios(run):
    scores = pd.read_csv(run / "corrected_research/property_proxy_scores.csv", dtype={"property_id": str})
    key = "corrected_context_plus_restaurant_proxy_aft_3yr"
    scores["full_inventory_proxy_percentile"] = scores[key].rank(method="average", pct=True)
    summaries = []
    for name in ("neighborhood_cafe", "office_lunch", "casual_dinner", "premium_dinner"):
        path = run / "scenarios" / (name + ".csv")
        frame = pd.read_csv(path, dtype={"property_id": str})
        frame = frame.merge(scores[["property_id", key, "full_inventory_proxy_percentile"]],
                            on="property_id", validate="one_to_one")
        if len(frame) != len(scores):
            raise ValueError("Property scenario coverage changed")
        frame["research_60_40"] = .6 * frame.full_inventory_proxy_percentile + .4 * frame.cuisine_gap
        for weight in (.1, .2):
            for component, column in (("access", "customer_access_percentile"), ("huff", "huff_percentile")):
                label = f"research_{component}_{int(weight * 100)}pct"
                frame[label] = (1 - weight) * frame.research_60_40 + weight * frame[column] / 100
                eligible = frame.dropna(subset=[label])
                k = min(50, len(eligible))
                base = set(eligible.nlargest(k, "research_60_40").property_id)
                alternative = set(eligible.nlargest(k, label).property_id)
                summaries.append({"profile": name, "component": component, "weight": weight,
                    "supported_candidates": len(eligible), "top_k": k,
                    "top_k_retention": len(base & alternative) / k if k else None})
        frame["assessment_scope"] = "Synthetic property/archive-proxy research scenario, not validated survival or visits"
        frame.to_csv(run / "scenarios" / (name + "_research_rankings.csv"), index=False)
    pd.DataFrame(summaries).to_csv(run / "scenarios/ranking_weight_sensitivity.csv", index=False)


def run(output, acknowledge_proxy, scenario_source):
    if not acknowledge_proxy:
        raise ValueError("Use --acknowledge-proxy: this is not verified permanent-closure survival")
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT / "data/output") or output.exists():
        raise ValueError("Choose a new run directory under private data/output")
    plan_path = Path(__file__).with_name("archive_research_plan.json")
    plan = json.loads(plan_path.read_text())
    inputs = {"master_tract_features.csv": find("master_tract_features.csv").resolve(),
              "current_restaurants.csv": find("current_restaurants.csv").resolve(),
              "restaurants_raw.parquet": find("restaurants_raw.parquet").resolve(),
              "synthetic_properties.csv": find("synthetic_properties.csv").resolve()}
    if not all(path.is_file() for path in inputs.values()):
        raise FileNotFoundError("A complete source input is missing")
    hashes = {name: file_hash(path) for name, path in inputs.items()}
    output.mkdir(parents=True, exist_ok=False)
    frozen = output / "frozen_root/data"
    frozen.mkdir(parents=True)
    log_directory = output / "logs"
    log_directory.mkdir()
    for name, source in inputs.items():
        shutil.copy2(source, frozen / name)
        if file_hash(frozen / name) != hashes[name]:
            raise ValueError("Source changed while freezing: " + name)
    snapshot = output / "code_snapshot"
    for folder in ("codes", "demo"):
        target = snapshot / folder
        target.mkdir(parents=True)
        for path in (ROOT / folder).glob("*.py"):
            shutil.copy2(path, target / path.name)
        for path in (ROOT / folder).glob("*.json"):
            shutil.copy2(path, target / path.name)
    reference = snapshot / "reference"
    reference.mkdir()
    for filename in ("train_survival.py", "features.py"):
        source = subprocess.check_output(["git", "show", plan["reference_revision"] + ":codes/" + filename], cwd=ROOT)
        (reference / filename).write_bytes(source)
    shutil.copy2(ROOT / "codes/paths.py", reference / "paths.py")
    shutil.copy2(plan_path, output / "research_plan.json")
    manifest = {"schema": "archive-research-run-v1", "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(), "plan": plan,
        "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "input_sources": {name: {"path": str(path), "sha256": hashes[name]} for name, path in inputs.items()},
        "source_snapshot_sha256": {str(path.relative_to(snapshot)): file_hash(path) for path in snapshot.rglob("*") if path.is_file()},
        "python": sys.version, "software": {package: importlib.metadata.version(package) for package in
            ("numpy", "pandas", "scipy", "scikit-learn", "xgboost", "h3")},
        "deployment_allowed": False, "verified_survival_validation": False}
    (output / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    environment = dict(os.environ, CAPSTONE_ROOT=str(output / "frozen_root"),
                       CAPSTONE_OUTPUTS=str(output / "outputs"), PYTHONUNBUFFERED="1")
    try:
        copy_scenarios(scenario_source, output / "scenarios", frozen)
        for step in ("labels", "matrix", "heatmaps", "lifespans"):
            execute(step, [sys.executable, str(ROOT / "codes/run_all.py"), "--only", step],
                    environment, ROOT, log_directory)
        execute("reference_training", [sys.executable, str(reference / "train_survival.py"),
            "--master", str(frozen / "master_tract_features.csv"),
            "--lifespans", str(output / "outputs/restaurant_lifespans.csv"),
            "--out-dir", str(output / "reference_model")], environment, ROOT, log_directory)
        execute("corrected_feature_training", [sys.executable, str(ROOT / "codes/train_archive_aft.py"),
            "--master", str(frozen / "master_tract_features.csv"),
            "--lifespans", str(output / "outputs/restaurant_lifespans.csv"),
            "--listings", str(frozen / "synthetic_properties.csv"),
            "--reference", str(reference / "train_survival.py"),
            "--output", str(output / "corrected_research"), "--plan", str(output / "research_plan.json")],
            environment, ROOT, log_directory)
        combine_scenarios(output)
        manifest["status"] = "completed_offline_proxy_research"
        manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
        manifest["artifact_sha256"] = {str(path.relative_to(output)): file_hash(path)
            for path in output.rglob("*") if path.is_file() and path.name != "run_manifest.json"}
        for name in inputs:
            if file_hash(frozen / name) != hashes[name]:
                raise ValueError("Frozen input changed during the run")
        (output / "run_manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
        pointer = ROOT / "data/output/current_archive_research_run.json"
        temporary = pointer.with_suffix(".tmp")
        temporary.write_text(json.dumps({"schema": manifest["schema"], "run": str(output),
            "manifest_sha256": file_hash(output / "run_manifest.json"), "deployment_allowed": False}, indent=2) + "\n")
        temporary.replace(pointer)
    except Exception as error:
        manifest.update(status="failed", error=str(error))
        (output / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        raise
    print(json.dumps({"status": manifest["status"], "output": str(output), "deployment_allowed": False}, indent=2))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--acknowledge-proxy", action="store_true")
    parser.add_argument("--scenario-source", type=Path, default=ROOT / "data/output/model_evaluation/20261027_v3")
    arguments = parser.parse_args()
    run(arguments.output, arguments.acknowledge_proxy, arguments.scenario_source)
