"""Cached, read-only dashboard inference for prospective walking-access bundles."""

from datetime import date
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "codes") not in sys.path:
    sys.path.append(str(ROOT / "codes"))
DEFAULT_ACCESS_CONFIG = ROOT / "data/output/customer_access_dashboard/dashboard_access.json"


def clean(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def parameters(concept):
    return concept.service_style, float(concept.average_check), concept.audience, concept.daypart


class CustomerAccessInference:
    def __init__(self, config):
        import pandas as pd
        self.runs = {key: Path(config[key]) for key in ("tract_run", "property_run")}
        self.manifests, self.candidates = {}, {}
        for kind, path in self.runs.items():
            manifest = json.loads((path / "manifest.json").read_text())
            if manifest["schema"] != "customer-access-features-v1":
                raise ValueError("Unsupported accessibility bundle")
            self.manifests[kind] = manifest
            self.candidates[kind] = pd.read_csv(manifest["sources"]["listings"]["path"],
                                                 dtype={"property_id": str, "geoid": str})

    @lru_cache(maxsize=16)
    def table(self, kind, concept_key, today):
        from customer_access import AccessConcept, score_cached_run
        frame = score_cached_run(self.runs[kind], AccessConcept(*concept_key), self.candidates[kind], today)
        frame["property_id"] = self.candidates[kind].property_id
        return frame.set_index("property_id")

    def assessment(self, kind, identity, concept):
        frame = self.table(kind, parameters(concept), date.today().isoformat())
        if str(identity) not in frame.index:
            return {"status": "not_in_snapshot", "index": None}
        row = frame.loc[str(identity)]
        raw = clean(row.inverse_walkability_percentile)
        return {"status": str(row.status) if raw is not None else "insufficient_coverage",
                "index": round(raw, 1) if raw is not None else None,
                "walking_index": clean(row.customer_access_percentile),
                "resident_opportunities": clean(row.decay_resident_opportunities),
                "worker_opportunities": clean(row.decay_worker_opportunities),
                "weighted_opportunities": clean(row.price_adjusted_access_opportunities),
                "routing_coverage": clean(row.routing_mass_coverage),
                "income_coverage": clean(row.resident_price_coverage),
                "reachable_origin_tracts": int(row.reachable_origin_tracts),
                "max_walk_minutes": self.manifests[kind]["config"]["max_walk_minutes"],
                "travel_half_life_minutes": float(row.travel_half_life_minutes),
                "scope": "tract_centroid" if kind == "tract_run" else "synthetic_property_scenario",
                "as_of": self.manifests[kind]["as_of"], "source": "Local OSM Walking Network; ACS; LODES",
                "visit_forecast": None, "assessment_type": "Uncalibrated customer-access index"}

    def attach(self, locations, properties, concept):
        for row in locations:
            assessment = self.assessment("tract_run", row["geoid"], concept)
            row["customer_access"] = assessment
            row["inverse_walkability"] = assessment["index"]
        for row in properties:
            assessment = (self.assessment("property_run", row["id"], concept)
                          if row.get("lead_type") == "synthetic"
                          else {"status": "not_in_snapshot", "index": None})
            row["customer_access"] = assessment
        return {"status": "available", "version": self.manifests["tract_run"]["config"]["version"],
                "as_of": self.manifests["tract_run"]["as_of"],
                "basis": "Network walking access from tract resident and workplace origins",
                "calibrated": False, "concept": dict(zip(("service_style", "average_check", "audience", "daypart"), parameters(concept))),
                "ranking_changed": False, "limitations": self.manifests["tract_run"]["config"]["limitations"]}

    def origins(self, geoid, concept, limit=8):
        import numpy as np
        import pandas as pd
        from customer_access import AccessConcept
        manifest = self.manifests["tract_run"]
        config = manifest["config"]
        AccessConcept(*parameters(concept)).validate(config)
        inventory = self.candidates["tract_run"]
        matches = inventory.index[inventory.property_id.eq(str(geoid))]
        if not len(matches):
            raise KeyError("Location not in accessibility snapshot")
        # table() checks source and cache hashes before the matrix is consulted.
        self.table("tract_run", parameters(concept), date.today().isoformat())
        origins = pd.read_csv(manifest["sources"]["master"]["path"], dtype={"geoid": str})
        with np.load(self.runs["tract_run"] / "routes.npz", allow_pickle=False) as saved:
            times = saved["distances"][matches[0]].astype(float) / config["walking_meters_per_minute"]
        known = np.isfinite(times)
        half_life = config["half_life_minutes"][concept.service_style]
        decay = np.exp2(-times / half_life)
        rw, ww = np.multiply(config["audience_weights"][concept.audience], config["daypart_weights"][concept.daypart])
        residents = pd.to_numeric(origins.population_2024, errors="coerce").to_numpy(float)
        jobs = pd.to_numeric(origins.total_jobs, errors="coerce").to_numpy(float)
        income = pd.to_numeric(origins.median_household_income_2024, errors="coerce").to_numpy(float)
        fit = np.minimum(1, income / (concept.average_check * config["annual_income_per_dollar_check"]))
        fit[~np.isfinite(income) | (income <= 0)] = np.nan
        contribution = decay * (rw * np.nan_to_num(residents * fit) + ww * np.nan_to_num(jobs))
        eligible = np.flatnonzero(known & np.isfinite(contribution) & (contribution > 0))
        top = eligible[np.argsort(-contribution[eligible])[:limit]]
        return [{"geoid": str(origins.iloc[i].geoid), "name": str(origins.iloc[i].get("nta_name", origins.iloc[i].geoid)),
                 "borough": str(origins.iloc[i].borough), "walking_minutes": round(float(times[i]), 1),
                 "weighted_opportunities": round(float(contribution[i]), 1),
                 "resident_price_coverage": "available" if np.isfinite(fit[i]) else "unavailable"}
                for i in top]


@lru_cache(maxsize=2)
def _engine(config_text, signature):
    return CustomerAccessInference(json.loads(config_text))


def access_engine(config_path=DEFAULT_ACCESS_CONFIG):
    try:
        text = Path(config_path).read_text()
        config = json.loads(text)
        if config.get("schema") != "dashboard-customer-access-v1":
            raise ValueError("Unsupported dashboard-access configuration")
        paths = [Path(config_path)]
        for kind in ("tract_run", "property_run"):
            run = Path(config[kind])
            manifest_path = run / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            paths += [manifest_path, run / "routes.npz"]
            paths += [Path(manifest["sources"][name]["path"]) for name in ("master", "listings")]
        def signature_for(path):
            stat = path.stat()
            return str(path), stat.st_mtime_ns, stat.st_size, stat.st_ino, stat.st_ctime_ns
        signature = tuple(signature_for(path) for path in paths)
        identity = hashlib.sha256(repr(signature[1:5]).encode()).hexdigest()
        return _engine(text, signature), {"status": "available", "artifact_id": identity}
    except (OSError, ValueError, KeyError, TypeError, ImportError):
        return None, {"status": "unavailable", "basis": "Customer-access snapshot unavailable", "calibrated": False}


def attach_access(locations, properties, concept, config_path=DEFAULT_ACCESS_CONFIG):
    engine, status = access_engine(config_path)
    if engine is not None:
        try:
            return {**status, **engine.attach(locations, properties, concept)}
        except (OSError, ValueError, KeyError, TypeError, ImportError):
            status = {"status": "unavailable", "basis": "Customer-access snapshot requires review", "calibrated": False}
    for row in locations:
        row["inverse_walkability"] = None
        row["customer_access"] = {"status": "unavailable", "index": None}
    for row in properties:
        row["customer_access"] = {"status": "unavailable", "index": None}
    return status
