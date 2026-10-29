"""Prospective customer-access features, deliberately separate from survival labels."""

from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree


CONFIG_PATH = Path(__file__).with_name("customer_access_config.json")


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_config(path=CONFIG_PATH):
    config = json.loads(Path(path).read_text())
    for key in ("walking_meters_per_minute", "max_walk_minutes", "max_snap_meters",
                "annual_income_per_dollar_check"):
        if not np.isfinite(config[key]) or config[key] <= 0:
            raise ValueError(f"Invalid positive parameter: {key}")
    if not 0 < config["minimum_mass_coverage"] <= 1:
        raise ValueError("minimum_mass_coverage must be in (0,1]")
    for value in config["half_life_minutes"].values():
        if not np.isfinite(value) or value <= 0:
            raise ValueError("Travel half-lives must be positive")
    for group in ("audience_weights", "daypart_weights"):
        for value in config[group].values():
            if len(value) != 2 or not np.isfinite(value).all() or min(value) < 0 or sum(value) <= 0:
                raise ValueError("Use two finite nonnegative audience/daypart weights")
    return config


@dataclass(frozen=True)
class AccessConcept:
    service_style: str = "casual"
    average_check: float = 35.0
    audience: str = "residents"
    daypart: str = "all_day"

    def validate(self, config):
        if (self.service_style not in config["half_life_minutes"]
                or self.audience not in config["audience_weights"]
                or self.daypart not in config["daypart_weights"]):
            raise ValueError("Unsupported service style, audience, or daypart")
        if not np.isfinite(self.average_check) or not 5 <= self.average_check <= 250:
            raise ValueError("Average check must be between 5 and 250 dollars")


def xy(lat, lon):
    # Local metric coordinates used only for nearest-node lookup and a radius screen.
    return np.column_stack((np.asarray(lon, dtype=float) * 111195 * np.cos(np.radians(40.7)),
                            np.asarray(lat, dtype=float) * 111195))


def validate_points(frame, key, latitude, longitude):
    if frame.empty or frame[key].isna().any() or frame[key].astype(str).eq("").any() or frame[key].duplicated().any():
        raise ValueError(f"Provide nonempty unique {key} values")
    lat = pd.to_numeric(frame[latitude], errors="coerce")
    lon = pd.to_numeric(frame[longitude], errors="coerce")
    if not (lat.between(40.45, 40.96) & lon.between(-74.31, -73.64)).all():
        raise ValueError("All origins and candidates must have usable NYC coordinates")


def route_matrix(origins, candidates, network_path, config, progress=None):
    """Bounded Dijkstra distances, with NaN for bad snaps and inf for no path.

    The private graph's directed edges are retained. Reverse routing from each
    destination gives origin-to-destination distances without assuming symmetry.
    Only one full-node distance vector is held at a time.
    """
    validate_points(origins, "geoid", "centroid_latitude", "centroid_longitude")
    validate_points(candidates, "property_id", "latitude", "longitude")
    path = Path(network_path)
    if not path.is_file():
        raise FileNotFoundError(f"Walking network is required, not a straight-line fallback: {path}")
    with closing(sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)) as db:
        node_count = db.execute("SELECT count(*) FROM nodes").fetchone()[0]
        ids = np.empty(node_count, dtype=np.int64)
        points = np.empty((node_count, 2), dtype=float)
        offset = 0
        cursor = db.execute("SELECT id, latitude, longitude FROM nodes ORDER BY id")
        while batch := cursor.fetchmany(50000):
            block = np.array(batch)
            ids[offset:offset + len(batch)] = [r[0] for r in batch]
            points[offset:offset + len(batch)] = xy(block[:, 1], block[:, 2])
            offset += len(batch)
        if node_count == 0:
            raise ValueError("Walking network is empty")
        edge_count = db.execute("SELECT count(*) FROM edges").fetchone()[0]
        source = np.empty(edge_count, dtype=np.int32)
        target = np.empty(edge_count, dtype=np.int32)
        meters = np.empty(edge_count, dtype=float)
        cursor = db.execute("SELECT source, target, meters FROM edges")
        offset = 0
        while batch := cursor.fetchmany(50000):
            src = np.array([r[0] for r in batch], dtype=np.int64)
            dst = np.array([r[1] for r in batch], dtype=np.int64)
            si, ti = np.searchsorted(ids, src), np.searchsorted(ids, dst)
            if ((si >= node_count).any() or (ti >= node_count).any()
                    or not np.array_equal(ids[si], src) or not np.array_equal(ids[ti], dst)):
                raise ValueError("Network edge references missing nodes")
            weight = np.array([r[2] for r in batch], dtype=float)
            if not np.isfinite(weight).all() or (weight <= 0).any():
                raise ValueError("Network edges need finite positive meter lengths")
            source[offset:offset + len(batch)], target[offset:offset + len(batch)] = ti, si
            meters[offset:offset + len(batch)] = weight
            offset += len(batch)
    graph = csr_matrix((meters, (source, target)), shape=(node_count, node_count))
    tree = cKDTree(points)
    origin_xy = xy(origins.centroid_latitude, origins.centroid_longitude)
    dest_xy = xy(candidates.latitude, candidates.longitude)
    osnap, onode = tree.query(origin_xy)
    dsnap, dnode = tree.query(dest_xy)
    max_distance = config["max_walk_minutes"] * config["walking_meters_per_minute"]
    matrix = np.full((len(candidates), len(origins)), np.nan, dtype=np.float32)
    valid_origin = osnap <= config["max_snap_meters"]
    for j, node in enumerate(dnode):
        if dsnap[j] <= config["max_snap_meters"]:
            distances = dijkstra(graph, directed=True, indices=int(node), limit=max_distance)
            values = distances[onode] + osnap + dsnap[j]
            values[values > max_distance] = np.inf
            matrix[j, valid_origin] = values[valid_origin]
        if progress and (j + 1) % 100 == 0:
            progress(f"Routed {j + 1}/{len(candidates)} properties")
    return matrix, {"origin_snap_meters": osnap, "candidate_snap_meters": dsnap,
                    "nodes": node_count, "directed_edges": edge_count}


def access_features(origins, candidates, distances, concept, config):
    """Return concept-specific reach, preserving missing measurements separately."""
    concept.validate(config)
    if distances.shape != (len(candidates), len(origins)) or (distances < 0).any():
        raise ValueError("Invalid route matrix shape or negative distance")
    populations = pd.to_numeric(origins.population_2024, errors="coerce").to_numpy(dtype=float, copy=True)
    jobs = pd.to_numeric(origins.total_jobs, errors="coerce").to_numpy(dtype=float, copy=True)
    incomes = pd.to_numeric(origins.median_household_income_2024, errors="coerce").to_numpy(dtype=float, copy=True)
    for values in (populations, jobs, incomes):
        values[~np.isfinite(values) | (values < 0)] = np.nan
    resident_weight, worker_weight = np.multiply(config["audience_weights"][concept.audience],
                                                config["daypart_weights"][concept.daypart])
    affordability = np.minimum(1.0, incomes / (concept.average_check * config["annual_income_per_dollar_check"]))
    affordability[incomes <= 0] = np.nan
    half_life = config["half_life_minutes"][concept.service_style]
    minutes = distances.astype(float) / config["walking_meters_per_minute"]
    decay = np.exp2(-minutes / half_life)
    decay[minutes > config["max_walk_minutes"]] = 0
    origin_xy = xy(origins.centroid_latitude, origins.centroid_longitude)
    dest_xy = xy(candidates.latitude, candidates.longitude)
    max_distance = config["max_walk_minutes"] * config["walking_meters_per_minute"]
    records = []
    for j, candidate in enumerate(candidates.to_dict("records")):
        nearby = np.linalg.norm(origin_xy - dest_xy[j], axis=1) <= max_distance * 1.01
        route_known = ~np.isnan(distances[j])
        population_known, jobs_known = np.isfinite(populations), np.isfinite(jobs)
        potential = (np.nan_to_num(populations) * resident_weight + np.nan_to_num(jobs) * worker_weight)
        total_mass = potential[nearby].sum()
        mass_coverage = potential[nearby & route_known].sum() / total_mass if total_mass > 0 else None
        feature_coverage = ((population_known.astype(float) * resident_weight + jobs_known.astype(float) * worker_weight)
                            / (resident_weight + worker_weight))[nearby].mean() if nearby.any() else None
        usable = route_known & population_known
        residents = float(np.sum(decay[j, usable] * populations[usable]))
        usable_workers = route_known & jobs_known
        workers = float(np.sum(decay[j, usable_workers] * jobs[usable_workers]))
        price_known = usable & np.isfinite(affordability)
        resident_price_coverage = (float(np.sum(decay[j, price_known] * populations[price_known])) / residents
                                  if residents > 0 else None)
        adjusted = float(np.sum(decay[j, price_known] * populations[price_known] * affordability[price_known]))
        status = "available" if (mass_coverage is not None and mass_coverage >= config["minimum_mass_coverage"]
                                  and feature_coverage is not None and feature_coverage >= config["minimum_mass_coverage"]) else "limited_coverage"
        if not route_known.any():
            status = "network_unavailable"
        price_ok = resident_price_coverage is not None and resident_price_coverage >= config["minimum_mass_coverage"]
        records.append({"property_id": str(candidate["property_id"]), "geoid": str(candidate["geoid"]),
                        "inventory_type": candidate.get("inventory_type", "unknown"),
                        "status": status, "decay_resident_opportunities": residents if route_known.any() else None,
                        "decay_worker_opportunities": workers if route_known.any() else None,
                        "customer_access_opportunities": resident_weight * residents + worker_weight * workers if route_known.any() else None,
                        "price_adjusted_access_opportunities": resident_weight * adjusted + worker_weight * workers if price_ok else None,
                        "resident_price_coverage": resident_price_coverage, "routing_mass_coverage": mass_coverage,
                        "origin_count_coverage": float(route_known[nearby].mean()) if nearby.any() else None,
                        "origin_feature_coverage": feature_coverage,
                        "reachable_origin_tracts": int(np.isfinite(distances[j]).sum()),
                        "service_style": concept.service_style, "average_check": concept.average_check,
                        "audience": concept.audience, "daypart": concept.daypart,
                        "travel_half_life_minutes": half_life, "visit_forecast": None,
                        "assessment_type": "Uncalibrated walking-access opportunity proxy"})
    result = pd.DataFrame(records)
    # Fixed full supplied inventory, never normalized after a user's price filter.
    for column, label in (("customer_access_opportunities", "customer_access_percentile"),
                          ("price_adjusted_access_opportunities", "inverse_walkability_percentile")):
        values = result[column].where(result.status.eq("available"))
        result[label] = values.rank(method="average", pct=True) * 100
    return result


def load_access_bundle(directory, prediction_date):
    """Load identified, checksummed routes for prospective feature experiments."""
    from datetime import date
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("schema") != "customer-access-features-v1":
        raise ValueError("Unsupported customer-access manifest")
    if not date.fromisoformat(manifest["as_of"]) <= date.fromisoformat(str(prediction_date)) <= date.today():
        raise ValueError("Customer-access features cannot be backdated")
    for name in ("master", "listings"):
        record = manifest["sources"][name]
        if file_hash(record["path"]) != record["sha256"]:
            raise ValueError(f"Pinned customer-access input changed: {name}")
    if file_hash(directory / "routes.npz") != manifest["artifacts"]["routes.npz"]:
        raise ValueError("Customer-access route checksum mismatch")
    origins = pd.read_csv(manifest["sources"]["master"]["path"], dtype={"geoid": str})
    inventory = pd.read_csv(manifest["sources"]["listings"]["path"], dtype={"geoid": str, "property_id": str})
    with np.load(directory / "routes.npz", allow_pickle=False) as saved:
        if (saved["geoids"].tolist() != origins.geoid.tolist()
                or saved["property_ids"].tolist() != inventory.property_id.tolist()):
            raise ValueError("Route matrix identifier order mismatch")
        distances = saved["distances"].copy()
    if distances.shape != (len(inventory), len(origins)) or (distances < 0).any():
        raise ValueError("Invalid cached route matrix")
    return origins, inventory, distances, manifest


def score_cached_run(directory, concept, candidates, prediction_date):
    """Score the pinned full inventory before selecting rows; never backdate."""
    origins, inventory, distances, manifest = load_access_bundle(directory, prediction_date)
    result = access_features(origins, inventory, distances, concept, manifest["config"])
    requested = candidates.copy()
    requested["property_id"] = requested.property_id.astype(str)
    if requested.property_id.duplicated().any():
        raise ValueError("Duplicate scoring candidates")
    pinned = inventory.set_index("property_id").reindex(requested.property_id)
    if pinned.geoid.isna().any():
        raise ValueError("Candidate is not in the pinned accessibility inventory")
    for column in ("latitude", "longitude"):
        if not np.allclose(pinned[column].to_numpy(float), requested[column].to_numpy(float), atol=1e-8, rtol=0):
            raise ValueError("Candidate coordinates differ from the route cache")
    if not np.array_equal(pinned.geoid.to_numpy(str), requested.geoid.to_numpy(str)):
        raise ValueError("Candidate tract differs from the route cache")
    selected = result.set_index("property_id").reindex(requested.property_id)
    selected.index = candidates.index
    return selected
