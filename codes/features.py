r"""
Feature preparation for the restaurant research workflows.

Historical AFT training and scoring use build_historical_features ONLY.
The older current-context helpers below are retained for legacy analysis,
not for training or scoring the temporal model.

Design decisions
  - Cuisine is NOT a feature. The survival model scores how well a location
    keeps any restaurant open; cuisine is handled by the heatmap / matrix.
  - Rent is NOT a feature. It is a filter in recommend.py.
  - DOHMH "current restaurant" columns (active count, grades, scores) are
    excluded: they only describe survivors and would leak the answer.
"""
import warnings
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", message="Mean of empty slice")

EARTH_R_M = 6_371_000
COMPETITION_RADIUS_M = 400

# Reuse the independently maintained provenance checks instead of accepting
# a current master CSV relabeled with an earlier observation year.
sys.path.append(str(Path(__file__).resolve().parents[1] / "demo"))
from prepare_historical_cohort import read_snapshots, select_snapshot
from evaluation import HISTORICAL_CORE_FEATURES

TEMPORAL_SCHEMA = "historical-aft-v1"
HISTORICAL_FEATURES = tuple(HISTORICAL_CORE_FEATURES)


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

# --------------------------------------------------------------------------
# Tract features
# --------------------------------------------------------------------------
# Columns whose neighbour average is added as <col>_nbr
NEIGHBOUR_COLS = [
    "rideshare_dropoffs_per_sq_mile",
    "subway_ridership_per_sq_mile",
    "citibike_departures_per_sq_mile",
    "national_walkability_index",
    "retail_area_sqft_per_sq_mile",
    "food_poi_per_sq_mile",
    "storefront_vacancy_rate",
    "job_density",
]


def _safe_div(a, b):
    a = pd.to_numeric(a, errors="coerce")
    b = pd.to_numeric(b, errors="coerce")
    return a / b.where(b > 0)


def build_tract_features(master: pd.DataFrame) -> pd.DataFrame:
    """Return one row per tract (index = geoid) with model-ready features."""
    m = master.copy()
    m["geoid"] = m["geoid"].astype("int64")
    area = m["land_area_sq_miles"]
    f = pd.DataFrame(index=m["geoid"])

    def col(name):
        return m[name].values if name in m else np.nan

    def optional(name):
        # An absent source column is unknown, not a measured zero.
        return m.get(name, pd.Series(np.nan, index=m.index))

    # Residents
    income = m["median_household_income_2024"].fillna(m.get("neighbor_income_2024_estimate", np.nan))
    f["population_density"] = col("population_density_per_sq_mile")
    f["pct_under_18"] = col("pct_residents_under_18")
    f["pct_65_plus"] = col("pct_residents_65_plus")
    f["median_household_income"] = income.values
    f["income_was_missing"] = col("income_missing_2024")

    # Workers (jobs share instead of jobs_per_resident, which explodes
    # in tracts with almost no residents)
    f["job_density"] = col("job_density_per_sq_mile")
    f["jobs_share_of_daytime_pop"] = _safe_div(
        m["total_jobs"], m["total_jobs"] + m["population_2024"]).values
    for c in ["pct_jobs_retail", "pct_jobs_accommodation_food",
              "pct_jobs_high_earning", "pct_jobs_office_industries"]:
        f[c] = col(c)

    # Walkability
    f["national_walkability_index"] = col("national_walkability_index")
    f["smart_location_score"] = col("smart_location_score")

    # Subway
    f["subway_ridership_per_sq_mile"] = _safe_div(m["subway_weekly_ridership"], area).values
    f["subway_station_count"] = col("subway_station_complex_count")
    f["nearest_subway_miles"] = col("nearest_subway_distance_miles")
    f["nearest_subway_ridership"] = col("nearest_subway_weekly_ridership")

    # Citi Bike: blank means "no station in tract" -> 0, not unknown
    f["citibike_departures_per_sq_mile"] = (
        (m["citibike_departures_per_sq_mile_latest_month"].fillna(0).values
         if "citibike_departures_per_sq_mile_latest_month" in m else np.nan))
    f["citibike_evening_share"] = col("citibike_evening_departure_share_latest_month")
    f["citibike_weekend_share"] = col("citibike_weekend_departure_share_latest_month")
    f["nearest_citibike_miles"] = col("nearest_citibike_distance_miles")

    # Uber/Lyft: the master gives every tract its WHOLE zone's total.
    # Convert to a density over the zone's land area so it is not
    # multiplied by the number of tracts in the zone.
    zone_area = m.groupby("taxi_zone")["land_area_sq_miles"].transform("sum")
    f["rideshare_dropoffs_per_sq_mile"] = _safe_div(optional("dropoffs_latest_month"), zone_area).values
    f["rideshare_pickups_per_sq_mile"] = _safe_div(optional("pickups_latest_month"), zone_area).values

    # Pedestrians (keep the distance so the model knows how far the counter is)
    f["ped_count_nearest"] = col("nearest_pedestrian_count_site_latest_pedestrian_count_total")
    f["ped_counter_distance_miles"] = col("nearest_pedestrian_count_site_distance_miles")

    # Built environment
    f["retail_area_sqft_per_sq_mile"] = col("retail_area_sqft_per_sq_mile")
    f["office_area_sqft_per_sq_mile"] = col("office_area_sqft_per_sq_mile")
    f["commercial_mixed_lot_share"] = col("commercial_mixed_lot_share_all")
    f["vacant_land_share"] = col("vacant_land_share_all_lots")
    f["mean_commercial_floors"] = col("mean_commercial_mixed_num_floors")
    f["storefronts_per_sq_mile"] = _safe_div(optional("registered_storefronts"), area).values
    f["storefront_vacancy_rate"] = (1 - _safe_div(optional("leased_storefronts"),
                                                  optional("registered_storefronts"))).clip(0, 1).values

    # Food market (OpenStreetMap, not DOHMH survivors)
    f["food_poi_per_sq_mile"] = _safe_div(optional("food_nightlife_poi_count"), area).values
    f["bar_per_sq_mile"] = _safe_div(optional("bar_nightlife_competitor_count"), area).values
    f["cafe_per_sq_mile"] = _safe_div(optional("cafe_competitor_count"), area).values

    # Events (currently "next 90 days"; swap for past-year counts when available)
    f["events_next_90_days"] = col("permitted_event_count_next_90_days")

    # Neighbour features already in the master
    f["nbr_population_density"] = col("neighbor_population_density_per_sq_mile")
    f["nbr_jobs_per_resident"] = col("neighbor_jobs_per_resident")
    f["nbr_income"] = col("neighbor_income_2024_estimate")

    # Neighbour averages computed here
    nbrs = pd.Series(optional("neighbor_geoids").fillna("").values, index=m["geoid"])
    nbr_lists = {g: [int(x) for x in s.split(";") if x] for g, s in nbrs.items()}
    for c in NEIGHBOUR_COLS:
        vals = f[c]
        f[c + "_nbr"] = [np.nanmean(vals.reindex(nbr_lists[g]).values)
                         if nbr_lists[g] else np.nan for g in f.index]

    # Heavy-tailed counts -> log scale (trees don't need it, but it keeps
    # SHAP plots and partial dependence readable)
    for c in f.columns:
        if c.endswith(("per_sq_mile", "per_sq_mile_nbr", "_density", "_density_nbr", "_ridership")):
            f[c] = np.log1p(f[c].clip(lower=0))

    f["borough"] = m["borough"].values
    f["nta_code"] = m["nta_code"].values
    return f


# Columns used as model inputs (everything except identifiers)
def model_columns(tract_feats: pd.DataFrame):
    return [c for c in tract_feats.columns if c not in ("borough", "nta_code")]


# --------------------------------------------------------------------------
# Location helpers
# --------------------------------------------------------------------------
def nearest_tract(lat, lon, tracts: pd.DataFrame):
    """Assign points to the tract with the nearest centroid (no shapefile needed)."""
    t_lat = np.radians(tracts["centroid_latitude"].values)
    t_lon = np.radians(tracts["centroid_longitude"].values)
    out = np.empty(len(lat), dtype="int64")
    lat_r, lon_r = np.radians(np.asarray(lat)), np.radians(np.asarray(lon))
    for s in range(0, len(lat), 2000):
        la, lo = lat_r[s:s + 2000, None], lon_r[s:s + 2000, None]
        d2 = (la - t_lat) ** 2 + ((lo - t_lon) * np.cos(la)) ** 2
        out[s:s + 2000] = tracts["geoid"].values[d2.argmin(axis=1)]
    return out


class CompetitionIndex:
    """Counts restaurants open within 400 m of a point on a given date."""

    CELL_DEG = 0.004  # ~445 m north-south

    def __init__(self, lifespans: pd.DataFrame, latest_snapshot):
        r = lifespans.dropna(subset=["lat", "lon", "open_date"])
        r = r[r["lat"].between(40.4, 41.0)]
        self.lat = r["lat"].values
        self.lon = r["lon"].values
        self.open = r["open_date"].values.astype("datetime64[D]")
        close = r["close_date"].fillna(pd.Timestamp(latest_snapshot) + pd.Timedelta(days=36500))
        self.close = close.values.astype("datetime64[D]")
        self.camis = r["camis"].values
        cy = np.floor(self.lat / self.CELL_DEG).astype(int)
        cx = np.floor(self.lon / (self.CELL_DEG * 1.32)).astype(int)
        self.cells = pd.Series(np.arange(len(r))).groupby([cy, cx]).apply(np.array).to_dict()

    def count(self, lat, lon, date, exclude_camis=None):
        cy = int(np.floor(lat / self.CELL_DEG))
        cx = int(np.floor(lon / (self.CELL_DEG * 1.32)))
        idx = [self.cells.get((cy + dy, cx + dx)) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
        idx = [i for i in idx if i is not None]
        if not idx:
            return 0
        idx = np.concatenate(idx)
        d = np.datetime64(pd.Timestamp(date).date())
        alive = (self.open[idx] <= d) & (self.close[idx] > d)
        if exclude_camis is not None:
            alive &= self.camis[idx] != exclude_camis
        idx = idx[alive]
        dy = np.radians(self.lat[idx] - lat) * EARTH_R_M
        dx = np.radians(self.lon[idx] - lon) * EARTH_R_M * np.cos(np.radians(lat))
        return int((dy * dy + dx * dx <= COMPETITION_RADIUS_M ** 2).sum())


def chain_names(lifespans: pd.DataFrame, min_locations=5):
    """DBA names that appear at 5+ locations are treated as chains."""
    n = lifespans["dba"].str.upper().str.strip().value_counts()
    return set(n[n >= min_locations].index)
