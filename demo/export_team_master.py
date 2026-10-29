"""Export a portable, audited copy of Groundwork's active data and research inputs."""

import argparse
import csv
import hashlib
import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

from refresh_integrated import ROOT


DATA = ROOT / "data"
LIFESPAN_FILES = (
    "restaurant_lifespans_20261020_v4.csv",
    "restaurant_lifespans_20261020_v4.manifest.json",
    "review_queue_20261020_v4.csv",
    "review_queue_20261020_v4.manifest.json",
    "adjudication_packet_20261020_v5.csv",
    "adjudication_packet_20261020_v5_probability_sample.csv",
    "adjudication_packet_20261020_v5.manifest.json",
    "original_capture_operating_pairs_20261020_v3.csv",
    "original_capture_operating_pairs_20261020_v3.manifest.json",
    "disappearance_audit_20261020_v1.csv",
    "disappearance_audit_20261020_v1_sample.csv",
    "disappearance_audit_20261020_v1.manifest.json",
    "disappearance_source_review_20261020.json",
    "manual_pilot_20261020_v2.csv",
    "manual_pilot_20261020_v2.manifest.json",
    "sla_review_leads_20261020_v2.csv",
    "sla_review_leads_20261020_v2.manifest.json",
    "foursquare_review_leads_20261020_v2.csv",
    "foursquare_review_leads_20261020_v2.manifest.json",
)
INDEX_FIELDS = ("path", "section", "bytes", "sha256", "training_status")


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def collect_paths(inventory):
    release = (DATA / "integrated/current").resolve()
    if not release.is_dir() or not (release / "master_tract_features.csv").is_file():
        raise ValueError("No active integrated release is available")
    files = {}

    def add(source, destination, section, training_status):
        source = Path(source).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        if destination in files and files[destination][0] != source:
            raise ValueError(f"Duplicate destination: {destination}")
        files[destination] = (source, section, training_status)

    def tree(source, destination, section, training_status):
        for path in Path(source).rglob("*"):
            if path.is_file() and path.name != ".DS_Store":
                add(path, destination / path.relative_to(source), section, training_status)

    tree(release, Path("data/integrated/current"), "active_integrated", "current_context_only")
    add(release / "master_tract_features.csv", Path("master_tract_features.csv"),
        "active_master_copy", "current_context_only")
    add(DATA / "training_inventory.json", Path("data/training_inventory_original.json"),
        "source_inventory", "metadata_not_training")

    for source_id, details in inventory["sources"].items():
        for raw in details.get("raw_files", []):
            path = Path(raw).resolve()
            if not path.is_relative_to(DATA.resolve()):
                raise ValueError(f"Raw source outside data directory: {path}")
            add(path, Path("data") / path.relative_to(DATA), "current_raw_source", "raw_not_training_matrix")
        manifest = DATA / "raw_sources" / source_id / "manifest.json"
        if manifest.is_file():
            add(manifest, Path("data/raw_sources") / source_id / "manifest.json",
                "source_manifest", "metadata_not_training")

    for source_id in ("sla_licenses", "foursquare_os", "nyc_cuisine_atlas", "census_blocks_2020"):
        tree(DATA / "raw_sources" / source_id, Path("data/raw_sources") / source_id,
             "research_raw_source", "review_only_not_verified_survival")
    for section in ("snapshots", "source_archives", "permit_presence", "candidates", "proxy_runs"):
        tree(DATA / "evaluation" / section, Path("data/evaluation") / section,
             "historical_research", "historical_predictor_or_review_only")
    for filename in LIFESPAN_FILES:
        add(DATA / "evaluation/lifespans" / filename,
            Path("data/evaluation/lifespans") / filename,
            "survival_review", "unverified_not_training_eligible")
    for pattern in ("historical_review_20261013T193016Z.*",
                    "historical_evidence_packet_20261017T234615Z.*",
                    "outcome_candidates_20261012T040842Z_7791af4d.*"):
        for path in (DATA / "evaluation").glob(pattern):
            add(path, Path("data/evaluation") / path.name,
                "historical_research", "review_only_not_verified_survival")
    tree(DATA / "listings", Path("data/listings"), "property_data",
         "synthetic_or_public_check_each_file")
    tree(DATA / "concept_images", Path("data/concept_images"), "frontend_media",
         "not_model_training")
    tree(DATA / "subway", Path("data/subway"), "historical_transit",
         "source_observations_not_survival_labels")
    for path in (DATA / "osm/NewYork-mbtiles-shortbread/NewYork.mbtiles",
                 DATA / "osm/nyc_walk_network.sqlite"):
        add(path, Path("data") / path.relative_to(DATA), "map_and_walk_network",
            "routing_or_map_asset")
    return files, release


def export(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(f"Export already exists: {destination}")
    inventory = json.loads((DATA / "training_inventory.json").read_text(encoding="utf-8"))
    if inventory.get("feature_matrix_structurally_valid") is not True:
        raise ValueError("Active matrix is not structurally validated")
    sources, release = collect_paths(inventory)
    master = release / "master_tract_features.csv"
    if digest(master) != inventory.get("feature_matrix_sha256"):
        raise ValueError("Active master differs from its inventory fingerprint")
    with master.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        if len(rows) != inventory["tract_rows"] or len(reader.fieldnames or []) != inventory["master_columns"] or len({row["geoid"] for row in rows}) != inventory["tract_rows"]:
            raise ValueError("Master tract count, columns, or GEOIDs differ from validated release")
    destination.mkdir(parents=True)
    index = []
    for target, (source, section, status) in sorted(sources.items(), key=lambda item: str(item[0])):
        output = destination / target
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output)
        checksum = digest(output)
        if checksum != digest(source):
            raise ValueError(f"Copy integrity failed: {target}")
        index.append({"path": target.as_posix(), "section": section,
                      "bytes": output.stat().st_size, "sha256": checksum,
                      "training_status": status})
    with (destination / "FILE_INDEX.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=INDEX_FIELDS)
        writer.writeheader()
        writer.writerows(index)
    summary = {"exported_at": datetime.now(timezone.utc).isoformat(),
               "as_of": date.today().isoformat(), "active_release": release.name,
               "master_rows": len(rows), "master_columns": len(reader.fieldnames),
               "master_sha256": digest(master), "file_count": len(index),
               "total_bytes": sum(row["bytes"] for row in index),
               "source_statuses": {key: {"label": item["label"], "grain": item["grain"],
                                        "status": item["status"], "version": item.get("raw_version")}
                                   for key, item in inventory["sources"].items()},
               "historical_training_ready": False,
               "warning": "Current tract context, raw sources, synthetic property scenarios, and unverified survival leads have different roles and must not be combined into one historical training matrix."}
    (destination / "BUNDLE_MANIFEST.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (destination / "README.md").write_text(
        "# Groundwork NYC Team Master Data\n\n"
        f"Frozen active release: `{release.name}`. The convenience file `master_tract_features.csv` "
        f"is identical to `data/integrated/current/master_tract_features.csv`. It has {len(rows):,} unique "
        f"2020 NYC tracts and {len(reader.fieldnames)} columns.\n\n"
        "The `data/integrated/current/` folder contains every companion entity, feature, geography, "
        "dictionary, readiness, source catalog, QA, and release file from the active release. "
        "Use `FILE_INDEX.csv` for SHA-256 checks and `BUNDLE_MANIFEST.json` for source status. "
        "Raw current revisions, historical snapshots, survival review inputs, synthetic property scenarios, "
        "and map assets are in separate folders because they have different grains and meanings.\n\n"
        "**Do not train survival on the current master or the review queue.** All 5,999 candidate "
        "outcomes remain unverified. The 600-case probability sample is for review, not a labeled test set. "
        "Synthetic properties are not actual listings. Public opportunities are source-reported and must be "
        "rechecked; no live lease inventory is implied. The original training inventory retains machine-local "
        "paths for provenance; use this bundle's relative paths when sharing.\n\n"
        "This folder includes third-party research and map assets; review each source's license and "
        "sharing terms before distributing outside the project team. No SAMPLE cleaned-source file is in "
        "the active master. Keep this export separate from the working data directory.\n",
        encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(export(args.output), indent=2))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f"Team export failed: {error}\n")


if __name__ == "__main__":
    main()
