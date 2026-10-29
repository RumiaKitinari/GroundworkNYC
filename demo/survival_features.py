"""Inference-only dated-feature helpers extracted from Otis Week 10 dce1e03.

Keep the historical-aft-v1 transform and validation shared with that artifact
contract; no research training entry points are imported by the dashboard.
"""
import csv
import json
import math
from datetime import date
from pathlib import Path
import numpy as np
import pandas as pd
from evaluation import FEATURES, fingerprint

TEMPORAL_SCHEMA = "historical-aft-v1"
HISTORICAL_FEATURES = tuple(FEATURES[:4])

def read_snapshots(manifest_path, data_dir, features=FEATURES, today=None):
    today = today or date.today()
    data_dir = Path(data_dir).resolve()
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("snapshots"), list):
        raise ValueError("The manifest must contain a snapshots list.")
    snapshots = {feature: [] for feature in features}
    for entry in manifest["snapshots"]:
        if not isinstance(entry, dict) or entry.get("feature") not in FEATURES:
            raise ValueError("Every snapshot needs a supported feature name.")
        if entry["feature"] not in snapshots:
            continue
        if entry.get("historical_reconstruction_verified") is not True or not entry.get("source_url"):
            raise ValueError("A snapshot needs verified historical provenance and a source URL.")
        path = (data_dir / entry.get("path", "")).resolve()
        if not path.is_relative_to(data_dir) or not path.is_file() or "sample" in str(path).lower():
            raise ValueError(f"Snapshot path is missing, outside private data, or a SAMPLE: {path}")
        observed = date.fromisoformat(entry["observed_through"])
        available = date.fromisoformat(entry["available_on"])
        if observed > available or available > today:
            raise ValueError(f"Invalid observation/release dates for {path}")
        digest = fingerprint(path)
        if digest != entry.get("sha256"):
            raise ValueError(f"Snapshot fingerprint mismatch for {path}")
        column = entry.get("column", entry["feature"])
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if not {"geoid", column} <= set(reader.fieldnames or []):
                raise ValueError(f"Snapshot needs geoid and {column}: {path}")
            values = {}
            for row in reader:
                geoid = row["geoid"].strip()
                if not geoid or geoid in values:
                    raise ValueError(f"Missing or duplicate tract ID in {path}")
                value = row[column].strip()
                if value:
                    parsed = float(value)
                    if not math.isfinite(parsed) or parsed < 0:
                        raise ValueError(f"Invalid {column} value in {path}")
                values[geoid] = value
        snapshots[entry["feature"]].append({"path": str(path.relative_to(data_dir)),
                                              "observed": observed, "available": available,
                                              "values": values, "sha256": digest,
                                              "source_url": entry["source_url"]})
    for entries in snapshots.values():
        entries.sort(key=lambda item: (item["available"], item["observed"]), reverse=True)
    return snapshots


def select_snapshot(entries, geoid, as_of):
    """Latest usable vintage that was public by the prediction date.

    Selection is independent of outcomes and other cohort rows. Publication
    dates, not just observation years, determine eligibility.
    """
    return next((item for item in entries
                 if item["observed"] <= item["available"] <= as_of
                 and item["values"].get(geoid, "") != ""), None)


def load_historical_snapshots(manifests, data_dir, as_of):
    """Combine explicitly pinned manifests; reject ambiguous same-date vintages."""
    snapshots = {feature: [] for feature in HISTORICAL_FEATURES}
    analysis_date = date.fromisoformat(str(as_of))
    for manifest in manifests:
        loaded = read_snapshots(manifest, data_dir, HISTORICAL_FEATURES)
        for feature, entries in loaded.items():
            snapshots[feature].extend(item for item in entries if item["available"] <= analysis_date)
    for feature, entries in snapshots.items():
        seen, unique = {}, []
        for item in entries:
            key = item["available"], item["observed"]
            if key in seen:
                if seen[key]["values"] != item["values"]:
                    raise ValueError(f"Conflicting same-date snapshots for {feature}")
                continue
            seen[key] = item
            unique.append(item)
        snapshots[feature] = sorted(unique, key=lambda x: (x["available"], x["observed"]),
                                    reverse=True)
    return snapshots


def build_historical_features(baselines, snapshots):
    """Point-in-time core features and per-value provenance, without imputation.

    Input has string GEOID and open_date (prediction date). No name, chain,
    current tract attributes, future events, labels, or cohort-wide statistics
    are consulted. Missing historical values stay NaN, never recorded zero.
    A fixed log1p transformation is shared with prospective scoring.
    """
    vectors, audit = [], []
    for row in baselines.to_dict("records"):
        day = date.fromisoformat(str(row["open_date"])[:10])
        geoid = str(row["geoid"])
        if len(geoid) != 11 or not geoid.isdigit():
            raise ValueError("Historical features require an explicit 11-digit GEOID")
        values = {}
        for feature in HISTORICAL_FEATURES:
            item = select_snapshot(snapshots[feature], geoid, day)
            values[feature] = np.log1p(float(item["values"][geoid])) if item else np.nan
            audit.append({"camis": str(row.get("camis", row.get("property_id", ""))),
                          "geoid": geoid, "prediction_date": day.isoformat(), "feature": feature,
                          "observed_through": item["observed"].isoformat() if item else "",
                          "available_on": item["available"].isoformat() if item else "",
                          "path": item["path"] if item else "",
                          "sha256": item["sha256"] if item else "",
                          "source_url": item["source_url"] if item else "",
                          "raw_value": item["values"][geoid] if item else "",
                          "status": "historical_observation" if item else "unavailable"})
        vectors.append(values)
    return pd.DataFrame(vectors, index=baselines.index, columns=HISTORICAL_FEATURES), audit

def validate_temporal_model(meta, prediction_date):
    if meta.get("schema") != TEMPORAL_SCHEMA or meta.get("features") != list(HISTORICAL_FEATURES):
        raise ValueError("Legacy/current-context survival model rejected; retrain using dated evidence.")
    day = date.fromisoformat(prediction_date)
    if not date.fromisoformat(meta["trained_as_of"]) <= day <= date.today():
        raise ValueError("Prediction date must be on/after model training as-of and not in the future")


def survival_prob(pred_time, horizon, scale):
    # Normal-AFT survival function, equivalent to train_survival.survival_prob.
    mu = np.log(np.clip(pred_time, 1e-6, None))
    return np.array([.5 * math.erfc((math.log(horizon) - value) / (scale * math.sqrt(2))) for value in mu])
