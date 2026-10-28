"""Experimental walking Huff scenarios, not calibrated visits or survival.

Existing restaurants are aggregated to tract centroids. Each hypothetical
candidate is assessed independently against that fixed existing inventory.
"""
import numpy as np
import pandas as pd

from scipy.spatial.distance import cdist
from customer_access import access_features, xy
from cuisine_matrix import build_matrix
from label_cuisines import label_row


def competitor_stock(restaurants, origin_geoids, cuisine):
    matrix = build_matrix()
    if cuisine not in matrix.index:
        raise ValueError("Choose an exact supported cuisine category")
    if restaurants.camis.isna().any() or restaurants.camis.duplicated().any():
        raise ValueError("Existing inventory must have unique nonmissing CAMIS identifiers")
    active = restaurants[restaurants.active_establishment.astype(str).str.lower().isin(["true", "1"])].copy()
    labels = [label_row(str(row.cuisine_description) if pd.notna(row.cuisine_description) else "",
                        str(row.dba) if pd.notna(row.dba) else "") for row in active.itertuples()]
    active["cuisine_50"] = [item[0] for item in labels]
    active["label_source"] = [item[1] for item in labels]
    # Guessed/default labels remain visible in the audit, but do not masquerade
    # as verified absence of competitors. Tract route gaps also remain explicit.
    strong = active.label_source.isin(["direct", "keyword"]) & active.geoid.isin(origin_geoids)
    active["used_in_scenario"] = strong
    weights = active.cuisine_50.map(matrix.loc[cuisine]).where(strong)
    stock = weights.groupby(active.geoid).sum().reindex(origin_geoids, fill_value=0)
    audit = {"active_rows": len(active), "used_rows": int(strong.sum()),
             "excluded_rows": int((~strong).sum()),
             "label_sources": active.label_source.value_counts().to_dict(),
             "unmatched_tract_rows": int((~active.geoid.isin(origin_geoids)).sum()),
             "weighted_competitors": float(stock.sum())}
    return stock.to_numpy(float), audit, active[["camis", "geoid", "cuisine_50", "label_source", "used_in_scenario"]]


def scenario_shares(candidate_utility, existing_utility, outside=1.0):
    """Every candidate is a separate counterfactual, not simultaneous new supply."""
    candidate = np.asarray(candidate_utility, float)
    existing = np.asarray(existing_utility, float)
    if (candidate.ndim != 2 or existing.shape != (candidate.shape[1],)
            or not np.isfinite(candidate).all() or not np.isfinite(existing).all()
            or (candidate < 0).any() or (existing < 0).any()
            or not np.isfinite(outside) or outside <= 0):
        raise ValueError("Use finite nonnegative utilities and a positive outside option")
    total = candidate + existing[None, :] + outside
    return candidate / total, existing[None, :] / total, outside / total


def network_scenarios(origins, candidates, property_routes, tract_candidates, tract_routes,
                      stock, concept, config, outside=1.0):
    concept.validate(config)
    stock = np.asarray(stock, float)
    if (len(tract_candidates) != len(origins)
            or not np.array_equal(tract_candidates.property_id.to_numpy(str), origins.geoid.to_numpy(str))
            or tract_routes.shape != (len(origins), len(origins))
            or property_routes.shape != (len(candidates), len(origins))
            or stock.shape != (len(origins),) or not np.isfinite(stock).all() or (stock < 0).any()
            or (tract_routes < 0).any() or (property_routes < 0).any()):
        raise ValueError("Align nonnegative origin, competitor, and candidate routes explicitly")
    half_life = config["half_life_minutes"][concept.service_style]
    def decay(routes):
        minutes = routes.astype(float) / config["walking_meters_per_minute"]
        values = np.exp2(-minutes / half_life)
        values[minutes > config["max_walk_minutes"]] = 0
        return np.nan_to_num(values)
    existing_utility = stock @ decay(tract_routes)
    candidate_utility = decay(property_routes)
    candidate_share, existing_share, outside_share = scenario_shares(candidate_utility, existing_utility, outside)
    rw, ww = np.multiply(config["audience_weights"][concept.audience], config["daypart_weights"][concept.daypart])
    residents = pd.to_numeric(origins.population_2024, errors="coerce").to_numpy(float)
    jobs = pd.to_numeric(origins.total_jobs, errors="coerce").to_numpy(float)
    income = pd.to_numeric(origins.median_household_income_2024, errors="coerce").to_numpy(float)
    affordability = np.minimum(1, income / (concept.average_check * config["annual_income_per_dollar_check"]))
    affordability[(income <= 0) | ~np.isfinite(income)] = np.nan
    resident_valid = np.isfinite(residents) & (residents >= 0) & np.isfinite(affordability)
    worker_valid = np.isfinite(jobs) & (jobs >= 0)
    mass = rw * np.where(resident_valid, residents * affordability, 0) + ww * np.where(worker_valid, jobs, 0)
    features = access_features(origins, candidates, property_routes, concept, config)
    # Unknown competitor routes could inflate candidate shares. Withhold affected
    # candidate assessments rather than treating those competitors as absent.
    origin_xy = xy(origins.centroid_latitude, origins.centroid_longitude)
    competitor_xy = xy(tract_candidates.latitude, tract_candidates.longitude)
    nearby = cdist(competitor_xy, origin_xy) <= config["max_walk_minutes"] * config["walking_meters_per_minute"] * 1.01
    unknown_competitor = (stock > 0) @ (np.isnan(tract_routes) & nearby)
    affected = (candidate_utility > 0) @ np.asarray(unknown_competitor, bool)
    captured = candidate_share @ mass
    supported = features.inverse_walkability_percentile.notna().to_numpy() & ~affected
    result = candidates[["property_id", "geoid"]].copy()
    result["huff_opportunities"] = np.where(supported, captured, np.nan)
    result["huff_percentile"] = result.huff_opportunities.rank(method="average", pct=True) * 100
    result["status"] = np.where(affected, "competitor_routing_incomplete", np.where(supported, "scenario_only", "insufficient_access_coverage"))
    result["inventory_type"] = candidates.get("inventory_type", "unspecified")
    result["forecast_visits"] = np.nan
    conservation = np.max(np.abs(candidate_share + existing_share + outside_share - 1))
    return result, {"maximum_choice_mass_error": float(conservation), "outside_attractiveness": outside,
        "known_origin_opportunity_mass": float(mass.sum()), "candidate_attractiveness": 1.0,
        "competitor_centroid_aggregation": True, "calibrated": False,
        "interpretation": "Independent hypothetical entrant scenarios; not additive visits, revenue, or survival",
        "unknown_competitor_route_origins": int(np.asarray(unknown_competitor, bool).sum())}
