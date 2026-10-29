from __future__ import annotations

import csv
import json
import math
import os
import secrets
import sqlite3
from collections import defaultdict
from copy import deepcopy
from contextlib import closing
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse
from flask import Flask, Response, jsonify, render_template, request, send_from_directory, redirect, session, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from scoring import CUISINES, Concept, ScreeningModel, MODEL_VERSION, resolve_concept
from evaluation import evaluation_status, run_evaluation
from osm_network import WalkingNetwork
from financials import operating_scenario
from hex_demand import concept_surface, surface_weights
from menu_catalog import suggestions as menu_suggestions
from rent_benchmarks import load_rent_benchmarks


from survival_inference import DEFAULT_CONFIG, attach_predictions, model_state

app = Flask(__name__)
app.config["SURVIVAL_CONFIG"] = os.environ.get("GROUNDWORK_SURVIVAL_CONFIG", str(DEFAULT_CONFIG))

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTANCE_DIR = PROJECT_ROOT / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)
INSTANCE_DIR.chmod(0o700)
SECRET_PATH = INSTANCE_DIR / "flask-secret.key"
if not SECRET_PATH.exists():
    SECRET_PATH.write_text(secrets.token_hex(32))
    SECRET_PATH.chmod(0o600)
app.secret_key = os.environ.get("GROUNDWORK_SECRET_KEY") or SECRET_PATH.read_text().strip()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
ACCOUNTS_PATH = INSTANCE_DIR / "accounts.sqlite3"


def account_db():
    connection = sqlite3.connect(ACCOUNTS_PATH)
    ACCOUNTS_PATH.chmod(0o600)
    connection.execute("CREATE TABLE IF NOT EXISTS accounts (id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL)")
    connection.execute("CREATE TABLE IF NOT EXISTS account_workspaces (account_id INTEGER PRIMARY KEY, payload TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, FOREIGN KEY(account_id) REFERENCES accounts(id))")
    return connection


WORKSPACE_BRIEF_FIELDS = {
    "conceptName", "profile", "rentCap", "dealType", "preferredArea", "cuisine",
    "averageCheck", "priceMode", "priceTier", "dietary", "description",
    "purchaseBudget", "otherFixedCosts", "variableCostPct", "operatingDays",
    "serviceStyle", "audience", "daypart",
}


def valid_workspace(payload):
    if not isinstance(payload, dict) or set(payload) != {"active_brief", "briefs", "shortlists", "menus"}:
        return False
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 500_000:
        return False

    def brief_ok(brief):
        return (isinstance(brief, dict) and set(brief) <= WORKSPACE_BRIEF_FIELDS
                and isinstance(brief.get("conceptName"), str)
                and 0 < len(brief["conceptName"]) <= 80
                and all(isinstance(value, (str, int, float)) and not isinstance(value, bool)
                        and (not isinstance(value, float) or math.isfinite(value))
                        and len(str(value)) <= 500 for value in brief.values()))

    active = payload["active_brief"]
    briefs = payload["briefs"]
    shortlists = payload["shortlists"]
    menus = payload["menus"]
    if active is not None and not brief_ok(active):
        return False
    if not isinstance(briefs, list) or len(briefs) > 50 or not all(brief_ok(row) for row in briefs):
        return False
    if not isinstance(shortlists, dict) or len(shortlists) > 100:
        return False
    if not all(isinstance(key, str) and len(key) <= 500 and isinstance(ids, list)
               and len(ids) <= 4 and all(isinstance(value, str) and len(value) <= 80 for value in ids)
               for key, ids in shortlists.items()):
        return False
    if not isinstance(menus, dict) or len(menus) > 100:
        return False
    for key, items in menus.items():
        if not isinstance(key, str) or len(key) > 500 or not isinstance(items, list) or len(items) > 100:
            return False
        for item in items:
            if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                    or not isinstance(item.get("name"), str)
                    or not isinstance(item.get("section"), str)
                    or item["section"] not in {"Starters", "Mains", "Sides", "Desserts", "Drinks"}
                    or len(item["id"]) > 120 or len(item["name"]) > 80
                    or not isinstance(item.get("note", ""), str)
                    or any(not isinstance(item.get(field, ""), (str, int, float)) or isinstance(item.get(field, ""), bool)
                           for field in ("price", "cost"))
                    or any(len(str(item.get(field, ""))) > limit for field, limit in
                           (("price", 20), ("cost", 20), ("note", 200)))):
                return False
    return True


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def csrf_valid():
    saved = session.get("csrf_token", "")
    submitted = request.form.get("csrf_token", "")
    return bool(saved and submitted) and secrets.compare_digest(saved, submitted)

BASELINE_DATA_DIR = PROJECT_ROOT / "data" / "integrated" / "restaurant_bar_location_data_ready"
CURRENT_DATA_LINK = PROJECT_ROOT / "data" / "integrated" / "current"
OSM_TILES_PATH = PROJECT_ROOT / "data" / "osm" / "NewYork-mbtiles-shortbread" / "NewYork.mbtiles"
OSM_WALK_NETWORK_PATH = PROJECT_ROOT / "data" / "osm" / "nyc_walk_network.sqlite"
LISTINGS_PATH = PROJECT_ROOT / "data" / "listings" / "verified_properties.csv"
CONCEPT_IMAGE_DIR = Path(app.static_folder) / "images" / "concepts"
PRIVATE_CONCEPT_IMAGE_DIR = PROJECT_ROOT / "data" / "concept_images"
SUBWAY_HOURLY_DIR = PROJECT_ROOT / "data" / "subway"


PROFILE_WEIGHTS = {
    "restaurant": {
        "demand": 0.24,
        "customer_fit": 0.18,
        "access": 0.16,
        "market_gap": 0.16,
        "competition_balance": 0.12,
        "economics": 0.14,
    },
    "bar": {
        "demand": 0.28,
        "customer_fit": 0.14,
        "access": 0.14,
        "market_gap": 0.13,
        "competition_balance": 0.17,
        "economics": 0.14,
    },
    "coffee": {
        "demand": 0.22,
        "customer_fit": 0.16,
        "access": 0.24,
        "market_gap": 0.12,
        "competition_balance": 0.10,
        "economics": 0.16,
    },
}
PROFILE_WEIGHTS.update({
    "fast_casual": {"demand": .28, "customer_fit": .16, "access": .22, "market_gap": .13, "competition_balance": .13, "economics": .08},
    "counter_service": {"demand": .29, "customer_fit": .14, "access": .24, "market_gap": .11, "competition_balance": .14, "economics": .08},
    "bakery": {"demand": .25, "customer_fit": .17, "access": .23, "market_gap": .12, "competition_balance": .11, "economics": .12},
    "fine_dining": {"demand": .17, "customer_fit": .29, "access": .12, "market_gap": .20, "competition_balance": .09, "economics": .13},
    "takeout_delivery": {"demand": .25, "customer_fit": .21, "access": .08, "market_gap": .15, "competition_balance": .18, "economics": .13},
})


SCORING_SIGNALS = {
    "demand": {"label": "Demand Strength", "coverage": 82, "description": "Resident, Worker, Foot Traffic, And Time-Of-Day Demand Indicators."},
    "customer_fit": {"label": "Customer Fit", "coverage": 88, "description": "Alignment Between The Selected Concept And The Local Customer Base."},
    "access": {"label": "Access And Visibility", "coverage": 79, "description": "Walkability, Transit Access, And Street-Level Movement Indicators."},
    "market_gap": {"label": "Cuisine Opportunity", "coverage": 69, "description": "Demand-Supported Cuisine Gaps Or Established Dining Ecosystems."},
    "competition_balance": {"label": "Competition Balance", "coverage": 66, "description": "Direct Competitive Pressure Compared With Local Demand."},
    "economics": {"label": "Commercial Suitability", "coverage": 58, "description": "Retail Area, Mixed-Use Parcels, Storefront Records, And Walkability."},
}


PROPERTY_LISTINGS = [
    {
        "id": "lic-corner-lease",
        "location_id": "lic",
        "title": "Corner Restaurant Space",
        "address": "Vernon Blvd Near 47th Ave",
        "transaction": "lease",
        "asking_rent": 18500,
        "asking_price": None,
        "sqft": 2350,
        "frontage": "38 ft",
        "condition": "Second-Generation Restaurant",
        "availability": "Broker Preview",
        "image": "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?auto=format&fit=crop&w=900&q=80",
        "notes": "Strong fit for lunch-to-dinner service with subway and waterfront residential demand.",
    },
    {
        "id": "williamsburg-warehouse-buy",
        "location_id": "williamsburg",
        "title": "Adaptive Reuse Retail Building",
        "address": "North 6th St Corridor",
        "transaction": "purchase",
        "asking_rent": None,
        "asking_price": 3650000,
        "sqft": 3100,
        "frontage": "44 ft",
        "condition": "Shell With Restaurant Venting Path",
        "availability": "Ownership Lead",
        "image": "https://images.unsplash.com/photo-1555396273-367ea4eb4db5?auto=format&fit=crop&w=900&q=80",
        "notes": "Higher upfront capital, but ownership could protect a differentiated nightlife concept from rent escalation.",
    },
    {
        "id": "astoria-main-lease",
        "location_id": "astoria",
        "title": "Neighborhood Bar Storefront",
        "address": "Broadway Near 31st St",
        "transaction": "lease",
        "asking_rent": 12800,
        "asking_price": None,
        "sqft": 1750,
        "frontage": "26 ft",
        "condition": "Warm Shell",
        "availability": "Available Now",
        "image": "https://images.unsplash.com/photo-1552566626-52f8b828add9?auto=format&fit=crop&w=900&q=80",
        "notes": "Lower rent pressure and durable neighborhood demand make it a practical first-shortlist property.",
    },
    {
        "id": "downtown-brooklyn-lease",
        "location_id": "downtown_brooklyn",
        "title": "Transit Hub Retail Bay",
        "address": "Flatbush Ave Extension",
        "transaction": "lease",
        "asking_rent": 20500,
        "asking_price": None,
        "sqft": 2150,
        "frontage": "32 ft",
        "condition": "New Retail Delivery",
        "availability": "Landlord Review",
        "image": "https://images.unsplash.com/photo-1560624052-449f5ddf0c31?auto=format&fit=crop&w=900&q=80",
        "notes": "Excellent access and mixed-use demand, but rent must be justified by all-day throughput.",
    },
    {
        "id": "harlem-townhouse-buy",
        "location_id": "central_harlem",
        "title": "Mixed-Use Restaurant Building",
        "address": "Lenox Ave Side Street",
        "transaction": "purchase",
        "asking_rent": None,
        "asking_price": 2450000,
        "sqft": 2800,
        "frontage": "21 ft",
        "condition": "Ground-Floor Retail With Upper Units",
        "availability": "Off-Market Target",
        "image": "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=900&q=80",
        "notes": "Ownership case improves if the operator wants long-term neighborhood control and rental income upstairs.",
    },
    {
        "id": "sunset-park-lease",
        "location_id": "sunset_park",
        "title": "Low-Cost Neighborhood Space",
        "address": "5th Ave Retail Strip",
        "transaction": "lease",
        "asking_rent": 9200,
        "asking_price": None,
        "sqft": 1500,
        "frontage": "24 ft",
        "condition": "Former Food Use",
        "availability": "Available Now",
        "image": "https://images.unsplash.com/photo-1554118811-1e0d58224f24?auto=format&fit=crop&w=900&q=80",
        "notes": "A lower-risk lease for neighborhood dining if the operator can build demand locally.",
    },
]


def clamp(value: float, low: int = 0, high: int = 100) -> int:
    return round(max(low, min(high, value)))


def as_float(value: object, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_bool(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def title_case(value: str) -> str:
    return " ".join(part[:1].upper() + part[1:].lower() if part else part for part in str(value or "").split())


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Required data file not found: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


PROFILE_RESIDENT_FIELDS = ("population_2024", "population_under_18_2024", "population_65_plus_2024",
                           "median_household_income_2024", "median_household_income_margin_of_error_2024")
PROFILE_WORKER_FIELDS = (
    "total_jobs", "jobs_age_29_or_younger", "jobs_age_30_to_54", "jobs_age_55_or_older",
    "jobs_earn_1250_or_less_monthly", "jobs_earn_1251_to_3333_monthly", "jobs_earn_more_than_3333_monthly",
    "jobs_agriculture_forestry_fishing_hunting", "jobs_mining_quarrying_oil_gas", "jobs_utilities",
    "jobs_construction", "jobs_manufacturing", "jobs_wholesale_trade", "jobs_retail_trade",
    "jobs_transportation_warehousing", "jobs_information", "jobs_finance_insurance",
    "jobs_real_estate_rental_leasing", "jobs_professional_scientific_technical", "jobs_management",
    "jobs_admin_support_waste_management", "jobs_educational_services",
    "jobs_health_care_social_assistance", "jobs_arts_entertainment_recreation",
    "jobs_accommodation_food_services", "jobs_other_services", "jobs_public_administration",
)


def source_number(row: dict, column: str) -> int | float | None:
    """Keep a recorded zero, but never turn a blank source cell into zero."""
    value = row.get(column)
    if value is None or str(value).strip() == "":
        return None
    number = float(value)
    return int(number) if number.is_integer() else number


@lru_cache(maxsize=2)
def profile_source_rows(directory: Path) -> tuple[dict, dict]:
    residents = read_csv(directory / "features" / "tract_demographics_income.csv")
    workers = read_csv(directory / "features" / "tract_workers.csv")
    return ({row["geoid"]: row for row in residents}, {row["geoid"]: row for row in workers})


def resident_worker_profile(tract: dict, directory: Path | None = None) -> dict:
    residents, workers = profile_source_rows(directory or integrated_directory())
    geoid = tract["geoid"]
    resident_row = residents.get(geoid, {})
    worker_row = workers.get(geoid, {})
    return {
        "geoid": geoid,
        "name": tract_display_name(tract),
        "borough": tract["borough"],
        "market_profile": {
            "population": source_number(resident_row, "population_2024"),
            "median_household_income": source_number(resident_row, "median_household_income_2024"),
            "income_margin_of_error": source_number(resident_row, "median_household_income_margin_of_error_2024"),
            "resident_age": {key: source_number(resident_row, key) for key in PROFILE_RESIDENT_FIELDS[1:3]},
            "jobs": source_number(worker_row, "total_jobs"),
            "job_age": {key: source_number(worker_row, key) for key in PROFILE_WORKER_FIELDS[1:4]},
            "job_earnings": {key: source_number(worker_row, key) for key in PROFILE_WORKER_FIELDS[4:7]},
            "job_industry": {key: source_number(worker_row, key) for key in PROFILE_WORKER_FIELDS[7:]},
        },
        "sources": {"residents": "2024 ACS five-year estimates", "jobs": "2023 LODES workplace jobs"},
    }


def public_url(value: str | None) -> str | None:
    parsed = urlparse(value or "")
    return value if parsed.scheme == "https" and parsed.netloc else None


def percentile_maps(rows: list[dict], columns: list[str]) -> dict[str, dict[str, int]]:
    maps: dict[str, dict[str, int]] = {}
    for column in columns:
        values = sorted({as_float(row.get(column), 0.0) for row in rows if row.get(column) not in (None, "")})
        if not values:
            maps[column] = {}
            continue
        max_rank = max(1, len(values) - 1)
        maps[column] = {str(value): round(index / max_rank * 100) for index, value in enumerate(values)}
    return maps


def pct(row: dict, maps: dict[str, dict[str, int]], column: str, inverse: bool = False) -> int:
    value = as_float(row.get(column), 0.0)
    score = maps.get(column, {}).get(str(value), 0)
    return 100 - score if inverse else score


def weighted(parts: list[tuple[float, float]]) -> int:
    numerator = sum(value * weight for value, weight in parts)
    denominator = sum(weight for _, weight in parts) or 1
    return clamp(numerator / denominator)


def subway_daypart_profiles() -> dict:
    totals = defaultdict(lambda: defaultdict(float))
    days = defaultdict(set)
    for path in sorted(SUBWAY_HOURLY_DIR.glob("station_hour_*.csv")):
        with path.open(newline="", encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                moment = date.fromisoformat(row["transit_timestamp"][:10])
                if moment.weekday() >= 5:
                    continue
                station = row["station_complex"]
                days[station].add(moment)
                hour = int(row["transit_timestamp"][11:13])
                period = "morning" if 7 <= hour < 10 else "midday" if 11 <= hour < 14 else "evening" if 17 <= hour < 21 else None
                if period:
                    totals[station][period] += float(row["ridership"])
    return {station: {period: round(totals[station][period] / len(dates))
                      for period in ("morning", "midday", "evening")}
            for station, dates in days.items() if dates}


def integrated_directory() -> Path:
    configured = os.environ.get("GROUNDWORK_DATA_DIR")
    directory = Path(configured) if configured else CURRENT_DATA_LINK if CURRENT_DATA_LINK.is_dir() else BASELINE_DATA_DIR
    return directory.resolve()


def integrated_package() -> dict:
    return _load_integrated_package(integrated_directory())


@lru_cache(maxsize=2)
def _load_integrated_package(directory: Path) -> dict:
    master_rows = read_csv(directory / "master_tract_features.csv")
    restaurants = read_csv(directory / "entities" / "current_restaurants.csv")
    sources = read_csv(directory / "source_catalog.csv")
    eligible_rows = [
        row
        for row in master_rows
        if as_bool(row.get("eligible_for_location_screening"))
        and row.get("centroid_latitude")
        and row.get("centroid_longitude")
    ]
    numeric_columns = [
        "population_density_per_sq_mile",
        "median_household_income_2024",
        "total_jobs",
        "job_density_per_sq_mile",
        "jobs_accommodation_food_services",
        "national_walkability_index",
        "smart_location_score",
        "food_nightlife_poi_count",
        "restaurant_competitor_count",
        "bar_nightlife_competitor_count",
        "cafe_competitor_count",
        "food_nightlife_poi_per_sq_mile",
        "active_restaurant_count",
        "grade_a_share",
        "subway_weekly_ridership",
        "nearest_subway_distance_miles",
        "nearest_subway_weekly_ridership",
        "citibike_departures_august_2026",
        "citibike_departures_latest_month",
        "citibike_evening_departures_latest_month",
        "nearest_citibike_distance_miles",
        "nearest_pedestrian_count_site_distance_miles",
        "nearest_pedestrian_count_site_latest_pedestrian_count_total",
        "pickups_may_2026",
        "dropoffs_may_2026",
        "pickups_latest_month",
        "dropoffs_latest_month",
        "retail_area_sqft",
        "mixed_use_parcel_count",
        "vacant_land_parcel_count",
        "reported_storefront_property_count",
        "reported_vacant_storefront_count",
        "reported_storefront_vacancy_share",
        "permitted_event_count_2026",
        "permitted_event_hours_2026",
        "permitted_event_count_next_90_days",
        "permitted_event_hours_next_90_days",
        "food_nightlife_pois_per_1000_residents",
        "jobs_per_1000_residents",
    ]
    latitudes = [as_float(row["centroid_latitude"]) for row in eligible_rows]
    longitudes = [as_float(row["centroid_longitude"]) for row in eligible_rows]
    return {
        "tracts": eligible_rows,
        "percentiles": percentile_maps(eligible_rows, numeric_columns),
        "storefronts": read_csv(directory / "entities" / "current_storefronts.csv"),
        "restaurants": restaurants,
        "subway_stations": read_csv(directory / "entities" / "subway_stations_weekly_activity.csv"),
        "subway_dayparts": subway_daypart_profiles(),
        "walking_network": WalkingNetwork(OSM_WALK_NETWORK_PATH),
        "sources": sources,
        "subway_vintage": next((row["vintage"] for row in sources if row.get("source") == "MTA ridership"), "Nearest station · one complete week"),
        "readiness": read_csv(directory / "feature_readiness.csv"),
        "data_release": directory.name,
        "data_path": str(directory.relative_to(PROJECT_ROOT)) if directory.is_relative_to(PROJECT_ROOT) else directory.name,
        "screening_model": ScreeningModel(eligible_rows, restaurants),
        "bounds": {
            "lat_min": min(latitudes),
            "lat_max": max(latitudes),
            "lon_min": min(longitudes),
            "lon_max": max(longitudes),
        },
    }


def restaurant_map_data() -> dict:
    return _restaurant_map_data(integrated_directory())


@lru_cache(maxsize=2)
def _restaurant_map_data(directory: Path) -> dict:
    features = []
    seen = set()
    excluded = {"inactive": 0, "missing_coordinates": 0, "outside_nyc_bounds": 0, "missing_identifier": 0, "duplicate_identifier": 0}
    for row in _load_integrated_package(directory)["restaurants"]:
        if not as_bool(row.get("active_establishment")):
            excluded["inactive"] += 1
            continue
        identifier = (row.get("camis") or "").strip()
        if not identifier:
            excluded["missing_identifier"] += 1
            continue
        try:
            latitude = float(row.get("latitude") or "")
            longitude = float(row.get("longitude") or "")
        except ValueError:
            excluded["missing_coordinates"] += 1
            continue
        if not math.isfinite(latitude) or not math.isfinite(longitude):
            excluded["missing_coordinates"] += 1
            continue
        if not 40.43 <= latitude <= 40.97 or not -74.32 <= longitude <= -73.65:
            excluded["outside_nyc_bounds"] += 1
            continue
        if identifier in seen:
            excluded["duplicate_identifier"] += 1
            continue
        seen.add(identifier)
        street_address = " ".join(part for part in ((row.get("building") or "").strip(), (row.get("street") or "").strip()) if part)
        address = ", ".join(part for part in (street_address, (row.get("boro") or "").strip(), (row.get("zipcode") or "").strip()) if part)
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                         "properties": {"id": identifier, "name": (row.get("dba") or "").strip(),
                                        "cuisine": (row.get("cuisine_description") or "").strip(), "address": address}})
    return {"type": "FeatureCollection", "features": features,
            "meta": {"mapped": len(features), "excluded": excluded}}


def concept_competition_column(profile: str) -> str:
    if profile == "bar":
        return "bar_nightlife_competitor_count"
    if profile in {"coffee", "bakery"}:
        return "cafe_competitor_count"
    return "restaurant_competitor_count"


def tract_display_name(row: dict) -> str:
    nta = row.get("nta_name") or row.get("community_district_name") or "NYC Trade Area"
    return f"{nta} Tract {row.get('tract_label') or row.get('tract_code')}"


def map_position(row: dict, bounds: dict) -> tuple[int, int]:
    lat = as_float(row.get("centroid_latitude"))
    lon = as_float(row.get("centroid_longitude"))
    x = 8 + ((lon - bounds["lon_min"]) / max(0.0001, bounds["lon_max"] - bounds["lon_min"])) * 82
    y = 8 + ((bounds["lat_max"] - lat) / max(0.0001, bounds["lat_max"] - bounds["lat_min"])) * 82
    return clamp(x, 4, 92), clamp(y, 4, 92)


def real_location_from_tract(row: dict, profile: str, rent_cap: int, package: dict, concept: Concept) -> dict:
    maps = package["percentiles"]
    competitor_column = concept_competition_column(profile)
    weights = PROFILE_WEIGHTS.get(profile, PROFILE_WEIGHTS["restaurant"])
    assessment = package["screening_model"].evaluate(row, concept, weights, profile)
    components = {key: item["score"] for key, item in assessment["components"].items()}
    demand = components["demand"]
    customer_fit = components["customer_fit"]
    market_gap = components["market_gap"]
    commercial = components["economics"]
    competition_pressure = pct(row, maps, competitor_column)
    confidence_score = assessment["confidence_score"]
    risk_flags = assessment["risk_flags"]
    x, y = map_position(row, package["bounds"])
    component_rows = [
        {
            "key": key,
            "label": SCORING_SIGNALS[key]["label"],
            "score": components[key],
            "weight": round(weights[key] * 100),
            "coverage": assessment["components"][key]["coverage"],
            "description": SCORING_SIGNALS[key]["description"],
        }
        for key in weights
    ]
    opportunity = assessment["opportunity"]
    return {
        "id": row["geoid"],
        "geoid": row["geoid"],
        "name": tract_display_name(row),
        "borough": row.get("borough") or "NYC",
        "latitude": as_float(row.get("centroid_latitude")),
        "longitude": as_float(row.get("centroid_longitude")),
        "x": x,
        "y": y,
        "opportunity": opportunity,
        "walkability": assessment["walkability"],
        "business_draw": assessment["business_draw"],
        "business_draw_coverage": assessment["business_draw_coverage"],
        "concept_evidence": assessment["concept_evidence"],
        "market_profile": {
            "population": as_float(row.get("population_2024")) if row.get("population_2024") else None,
            "jobs": as_float(row.get("total_jobs")) if row.get("total_jobs") else None,
            "median_household_income": as_float(row.get("median_household_income_2024")) if row.get("median_household_income_2024") else None,
            "income_margin_of_error": as_float(row.get("median_household_income_margin_of_error_2024")) if row.get("median_household_income_margin_of_error_2024") else None,
            "subway_distance_miles": as_float(row.get("nearest_subway_distance_miles")) if row.get("nearest_subway_distance_miles") else None,
            "nearest_subway_station": row.get("nearest_subway_station_complex") or None,
            "nearest_subway_weekly_ridership": as_float(row.get("nearest_subway_weekly_ridership")) if row.get("nearest_subway_weekly_ridership") else None,
            "subway_vintage": package["subway_vintage"],
            "nearest_subway_dayparts": package["subway_dayparts"].get(row.get("nearest_subway_station_complex")),
            "pedestrian_counter_distance_miles": as_float(row.get("nearest_pedestrian_count_site_distance_miles")) if row.get("nearest_pedestrian_count_site_distance_miles") else None,
            "pedestrian_counter_latest": as_float(row.get("nearest_pedestrian_count_site_latest_pedestrian_count_total")) if row.get("nearest_pedestrian_count_site_latest_pedestrian_count_total") else None,
            "bike_departures_august_2026": as_float(row.get("citibike_departures_august_2026")) if row.get("citibike_departures_august_2026") else None,
            "bike_departures_latest_month": as_float(row.get("citibike_departures_latest_month")) if row.get("citibike_departures_latest_month") else None,
            "bike_activity_month": row.get("citibike_activity_month") or None,
            "taxi_pickups_latest_month": as_float(row.get("pickups_latest_month")) if row.get("pickups_latest_month") else None,
            "taxi_dropoffs_latest_month": as_float(row.get("dropoffs_latest_month")) if row.get("dropoffs_latest_month") else None,
            "taxi_activity_month": row.get("taxi_activity_month") or None,
            "active_restaurants": as_float(row.get("active_restaurant_count")) if row.get("active_restaurant_count") else None,
            "reported_vacant_storefronts": as_float(row.get("reported_vacant_storefront_count")) if row.get("reported_vacant_storefront_count") else None,
            "neighborhood": row.get("nta_name") or None,
        },
        "model_version": MODEL_VERSION,
        "activity": demand,
        "whitespace": market_gap,
        "transit": pct(row, maps, "nearest_subway_weekly_ridership"),
        "customer": customer_fit,
        "competition": competition_pressure,
        "cost": commercial,
        "confidence": "high" if confidence_score >= 84 else "medium high" if confidence_score >= 70 else "medium" if confidence_score >= 55 else "limited",
        "confidence_score": confidence_score,
        "archetype": profile.replace("_", " "),
        "rent": rent_cap,
        "rent_label": "Pending",
        "sqft": round(as_float(row.get("retail_area_sqft")) or as_float(row.get("commercial_area_sqft")) or 0),
        "score_components": component_rows,
        "risk_flags": risk_flags,
        "recommendation": recommendation_for(opportunity, confidence_score, risk_flags),
        "why": [
            f"Demand score is {demand}, using resident and worker density, transit access, pedestrian evidence, and cycling activity proxies.",
            f"Competition pressure is {competition_pressure}, based on tract-level {profile} competitor counts from the integrated POI layer.",
            f"Commercial suitability is {commercial}, using retail area, mixed-use parcels, and storefront records.",
        ],
        "source_notes": [
            "Master tract features are the primary source.",
            "Exact asking rent, sale price, listing images, and confirmed transaction status are not included in the integrated dataset.",
        ],
    }


BASE_LOCATIONS = [
    {
        "id": "williamsburg",
        "name": "Williamsburg North",
        "borough": "Brooklyn",
        "x": 49,
        "y": 53,
        "opportunity": 91,
        "walkability": 86,
        "activity": 84,
        "whitespace": 79,
        "transit": 83,
        "customer": 92,
        "competition": 64,
        "cost": 68,
        "confidence": "medium high",
        "archetype": "gastropub",
        "rent": 16500,
        "sqft": 1900,
        "why": [
            "Strong evening demand, dense residents, and a durable nightlife signal.",
            "High competition, but the direct gastropub gap remains better than nearby restaurant clusters.",
            "Works best for concepts with clear differentiation and higher average check size.",
        ],
    },
    {
        "id": "lic",
        "name": "Long Island City Core",
        "borough": "Queens",
        "x": 62,
        "y": 43,
        "opportunity": 87,
        "walkability": 82,
        "activity": 80,
        "whitespace": 86,
        "transit": 92,
        "customer": 88,
        "competition": 57,
        "cost": 71,
        "confidence": "medium",
        "archetype": "restaurant",
        "rent": 18800,
        "sqft": 2300,
        "why": [
            "Worker density, resident growth, and subway access create demand across lunch and dinner windows.",
            "Expected supply is above observed supply for several restaurant and bar formats.",
            "Lease economics need close review because rent is rising faster than surrounding outer-borough peers.",
        ],
    },
    {
        "id": "east_village",
        "name": "East Village",
        "borough": "Manhattan",
        "x": 42,
        "y": 45,
        "opportunity": 82,
        "walkability": 94,
        "activity": 91,
        "whitespace": 49,
        "transit": 88,
        "customer": 86,
        "competition": 89,
        "cost": 58,
        "confidence": "high",
        "archetype": "bar",
        "rent": 24000,
        "sqft": 1600,
        "why": [
            "One of the strongest nightlife and pedestrian-activity zones in the current market set.",
            "Market gap is weak because existing restaurant and bar density is already high.",
            "Best treated as a high-demand, high-saturation market for distinctive operators.",
        ],
    },
    {
        "id": "astoria",
        "name": "Astoria Broadway",
        "borough": "Queens",
        "x": 65,
        "y": 34,
        "opportunity": 81,
        "walkability": 78,
        "activity": 75,
        "whitespace": 85,
        "transit": 78,
        "customer": 82,
        "competition": 53,
        "cost": 80,
        "confidence": "medium",
        "archetype": "neighborhood bar",
        "rent": 13200,
        "sqft": 1700,
        "why": [
            "Healthy customer fit with lower rent pressure than the highest-activity locations.",
            "Competition is present but not as compressed as the Manhattan clusters.",
            "Useful candidate for a neighborhood-first restaurant or bar concept.",
        ],
    },
    {
        "id": "downtown_brooklyn",
        "name": "Downtown Brooklyn",
        "borough": "Brooklyn",
        "x": 45,
        "y": 64,
        "opportunity": 84,
        "walkability": 86,
        "activity": 85,
        "whitespace": 70,
        "transit": 95,
        "customer": 82,
        "competition": 69,
        "cost": 65,
        "confidence": "medium high",
        "archetype": "fast casual",
        "rent": 19800,
        "sqft": 2100,
        "why": [
            "Transit access and mixed worker-resident demand lift the baseline score.",
            "Higher rent pressure makes the financial tab important before shortlisting.",
            "Best fit for concepts that can serve lunch, dinner, and event spillover demand.",
        ],
    },
    {
        "id": "central_harlem",
        "name": "Central Harlem",
        "borough": "Manhattan",
        "x": 40,
        "y": 24,
        "opportunity": 77,
        "walkability": 79,
        "activity": 72,
        "whitespace": 81,
        "transit": 82,
        "customer": 78,
        "competition": 48,
        "cost": 84,
        "confidence": "medium",
        "archetype": "casual dining",
        "rent": 11800,
        "sqft": 1800,
        "why": [
            "Lower cost pressure improves the risk-adjusted view for first-time owners.",
            "Market-gap signal is promising, especially for neighborhood dining.",
            "More mobility data is needed before treating pedestrian activity as high confidence.",
        ],
    },
    {
        "id": "flushing",
        "name": "Flushing Main Street",
        "borough": "Queens",
        "x": 79,
        "y": 36,
        "opportunity": 80,
        "walkability": 82,
        "activity": 90,
        "whitespace": 56,
        "transit": 91,
        "customer": 83,
        "competition": 83,
        "cost": 70,
        "confidence": "medium high",
        "archetype": "restaurant",
        "rent": 17600,
        "sqft": 1550,
        "why": [
            "Activity and transit are extremely strong for food and beverage.",
            "Existing restaurant density lowers WhiteSpace despite strong demand.",
            "Better for operators who want volume and can survive heavy direct competition.",
        ],
    },
    {
        "id": "sunset_park",
        "name": "Sunset Park",
        "borough": "Brooklyn",
        "x": 39,
        "y": 79,
        "opportunity": 74,
        "walkability": 69,
        "activity": 64,
        "whitespace": 86,
        "transit": 70,
        "customer": 74,
        "competition": 44,
        "cost": 89,
        "confidence": "low medium",
        "archetype": "neighborhood restaurant",
        "rent": 9400,
        "sqft": 1450,
        "why": [
            "Cost pressure and market gap look favorable for smaller operators.",
            "Pedestrian activity confidence is lower until additional mobility evidence is available.",
            "A strong candidate for a local concept rather than a destination concept.",
        ],
    },
]


DATA_FEEDS = [
    {"name": "Census ACS", "status": "mapped", "records": "2,327 Tracts", "signal": 91, "join": "Census Tract", "owner": "market"},
    {"name": "Census LODES", "status": "mapped", "records": "NY WAC 2023", "signal": 88, "join": "Workplace Block To Tract", "owner": "market"},
    {"name": "MTA Ridership", "status": "cleaning", "records": "574,950 Rows", "signal": 74, "join": "Nearest Station", "owner": "mobility"},
    {"name": "DOT Pedestrian Counts", "status": "review", "records": "114 Counters", "signal": 62, "join": "Nearest Count Site", "owner": "mobility"},
    {"name": "Restaurant Inspections", "status": "dedupe", "records": "294,841 Rows", "signal": 69, "join": "Location To Tract", "owner": "competition"},
    {"name": "PLUTO And Storefronts", "status": "queued", "records": "Tax Lots", "signal": 55, "join": "Parcel To Tract", "owner": "lease"},
]


WHITESPACE = [
    {"category": "Gastropub", "current": 4, "expected": 7.4, "gap": 3.4, "score": 88},
    {"category": "Bakery Cafe", "current": 3, "expected": 5.9, "gap": 2.9, "score": 84},
    {"category": "Late-Night Dessert", "current": 2, "expected": 4.2, "gap": 2.2, "score": 79},
    {"category": "Full-service Italian", "current": 9, "expected": 7.1, "gap": -1.9, "score": 43},
]


VENDOR_WINDOWS = [
    {"concept": "Coffee Cart", "window": "7 AM-11 AM", "demand": 93, "eligibility": "Likely", "note": "Weather And Transit Proximity Increase Morning Demand."},
    {"concept": "Lunch Truck", "window": "11 AM-2 PM", "demand": 86, "eligibility": "Review", "note": "Worker Density Supports Midday Demand."},
    {"concept": "Dessert Cart", "window": "6 PM-10 PM", "demand": 81, "eligibility": "Likely", "note": "Event Spillover Supports Evening Demand."},
]


FEATURE_GROUPS = [
    {
        "group": "Demand",
        "features": ["resident density", "worker density", "transit exits", "event proximity"],
        "ready": 72,
        "target": "Demand potential and time-of-day demand",
    },
    {
        "group": "Customer Fit",
        "features": ["income", "age bands", "households", "worker mix"],
        "ready": 86,
        "target": "Restaurant/bar target customer match",
    },
    {
        "group": "Competition",
        "features": ["direct competitors", "category density", "inspection history", "review proxy"],
        "ready": 64,
        "target": "Direct, secondary, and complementary competition",
    },
    {
        "group": "Built Environment",
        "features": ["walkability", "sidewalk proxy", "POI diversity", "barriers"],
        "ready": 58,
        "target": "Access, movement, and street suitability",
    },
    {
        "group": "Lease Fit",
        "features": ["rent", "square footage", "storefront vacancy", "land use"],
        "ready": 47,
        "target": "Property compatibility and break-even pressure",
    },
]


DATA_LAYERS = [
    {"name": "Customer Base", "description": "Resident, Income, Household, And Daytime Worker Indicators.", "coverage": 91, "status": "Decision-Ready"},
    {"name": "Transit And Mobility", "description": "Subway Activity, Station Access, Taxi Movement, And Bike Activity.", "coverage": 74, "status": "Decision-Ready"},
    {"name": "Restaurant Market", "description": "Existing Restaurants, Bars, Inspection Records, Category Density, And Saturation.", "coverage": 69, "status": "Decision-Ready"},
    {"name": "Built Environment", "description": "Walkability, Point-Of-Interest Diversity, Parcel Context, And Street Conditions.", "coverage": 58, "status": "Developing"},
    {"name": "Property Context", "description": "Storefront Inventory, Land Use, Commercial Area, And Vacancy Signals.", "coverage": 55, "status": "Developing"},
]


REPORTS = [
    {"name": "Location Shortlist", "audience": "Founder Or Operator", "includes": "Top Locations, Score Drivers, Risk Factors, And Recommended Next Steps", "status": "Preview"},
    {"name": "Property Fit Report", "audience": "Tenant Or Broker", "includes": "Lease Comparison, Rent Pressure, Customer Fit, And Nearby Competition", "status": "Preview"},
    {"name": "Neighborhood Opportunity Brief", "audience": "Operator", "includes": "Market Gaps, Demand Signals, And Strongest Business Categories", "status": "Planned"},
    {"name": "Investor Snapshot", "audience": "Advisor Or Lender", "includes": "Break-Even Assumptions, Runway, And Confidence Tier", "status": "Planned"},
]


def tuned_locations(profile: str, rent_cap: int, borough: str = "", concept: Concept | None = None, limit: int | None = 24) -> list[dict]:
    package = integrated_package()
    rows = package["tracts"]
    if borough:
        rows = [row for row in rows if row.get("borough") == borough]
    locations = [real_location_from_tract(row, profile, rent_cap, package, concept or Concept()) for row in rows]
    ranked = sorted(locations, key=lambda row: row["opportunity"], reverse=True)
    return ranked[:limit] if limit is not None else ranked


def listing_source_paths() -> list[Path]:
    paths = [path for path in (LISTINGS_PATH, LISTINGS_PATH.parent / "public_opportunities.csv") if path.is_file()]
    return paths + sorted((LISTINGS_PATH.parent / "authorized").glob("*.csv"))


def matching_properties(locations: list[dict], deal_type: str, rent_cap: int, purchase_budget: int, concept: Concept | None = None, profile: str | None = None) -> list[dict]:
    package = integrated_package()
    location_lookup = {location["geoid"]: location for location in locations}
    properties = []
    listing_paths = listing_source_paths()
    for listing_path in listing_paths:
        for listing in read_csv(listing_path):
            location = location_lookup.get(listing.get("geoid"))
            transaction = listing.get("transaction", "").lower()
            if not location or transaction not in {"lease", "purchase"} or deal_type not in {transaction, "either"}:
                continue
            source_url = public_url(listing.get("source_url"))
            if not source_url or not listing.get("checked_at"):
                continue
            try:
                checked_at = date.fromisoformat(listing["checked_at"])
            except ValueError:
                continue
            if not date.today() - timedelta(days=90) <= checked_at <= date.today():
                continue
            price = as_float(listing.get("asking_price")) or None
            rent = as_float(listing.get("asking_rent_monthly")) or None
            if transaction == "lease" and (rent is None or rent <= 0) or transaction == "purchase" and (price is None or price <= 0):
                continue
            if (transaction == "lease" and rent > rent_cap) or (transaction == "purchase" and price > purchase_budget):
                continue
            source_type = listing.get("source_type") or "partner"
            if source_type == "official_public_page" and profile == "bar":
                continue
            properties.append({
                "id": listing.get("listing_id") or f"listing-{len(properties)}",
                "location_id": location["id"], "geoid": location["geoid"],
                "title": listing.get("title") or "Restaurant Property", "address": listing.get("address") or "Address Pending",
                "borough": location["borough"], "transaction": transaction,
                "transaction_label": "Public Leasing Opportunity" if source_type == "official_public_page" else "Lease Listing" if transaction == "lease" else "Purchase Listing",
                "lead_type": "listing", "asking_rent": rent, "asking_price": price,
                "source_type": source_type,
                "price_label": (f"${rent:,.2f}/Month" if rent % 1 else f"${rent:,.0f}/Month") if rent else
                               (f"${price:,.2f}" if price % 1 else f"${price:,.0f}"),
                "sqft": as_float(listing.get("sqft")) or 0, "sqft_label": listing.get("sqft") or "Size Pending",
                "frontage": listing.get("frontage") or "Frontage Pending", "condition": listing.get("condition") or "Condition Pending",
                "availability": listing.get("availability") or "Status Unverified",
                "image": (public_url(listing.get("image_url")) or "") if as_bool(listing.get("photo_display_permission")) else "",
                "image_label": "Property Listing", "location_name": location["name"], "location_score": location["opportunity"],
                "confidence_score": location["confidence_score"], "monthly_basis": rent_cap, "monthly_basis_label": f"{round(rent_cap / 1000)}k Target",
                "fit_score": location["opportunity"], "ranking_basis": "Area Score; Listing Within Budget", "notes": listing.get("notes") or "Confirm Listing Details With Source.",
                "latitude": listing.get("latitude") or None, "longitude": listing.get("longitude") or None,
                "broker_name": listing.get("broker_name") or None, "broker_contact": listing.get("broker_contact") or None,
                "source_url": source_url, "checked_at": listing.get("checked_at"),
            })
    if deal_type == "purchase":
        candidates = sorted(properties, key=lambda row: row["fit_score"], reverse=True)[:12]
        return add_site_evidence(candidates, package, concept)
    seen_bbls = set()
    storefronts = sorted(
        package["storefronts"],
        key=lambda row: (
            not as_bool(row.get("vacant_current")),
            row.get("borough") or "",
            row.get("property_street_address_or") or "",
        ),
    )
    for listing in storefronts:
        location = location_lookup.get(listing.get("geoid"))
        if not location:
            continue
        if not as_bool(listing.get("vacant_current")):
            continue
        bbl = listing.get("borough_block_lot") or f"{listing.get('geoid')}-{listing.get('property_street_address_or')}"
        if bbl in seen_bbls:
            continue
        seen_bbls.add(bbl)
        address = title_case(listing.get("property_street_address_or") or "Storefront Address Not In Source")
        reported_activity = title_case(listing.get("primary_business_activity") or "Not In Source")
        properties.append(
            {
                "id": bbl,
                "location_id": location["id"],
                "geoid": listing.get("geoid"),
                "title": "Reported Vacant Storefront",
                "address": address,
                "borough": location["borough"],
                "transaction": "unknown",
                "transaction_label": "Storefront Research",
                "lead_type": "registry_record",
                "asking_rent": None,
                "asking_price": None,
                "price_label": "Not In Source",
                "sqft": 0,
                "sqft_label": "Size Not In Source",
                "frontage": "Frontage Pending",
                "condition": reported_activity,
                "availability": "Reported Vacant; Lease Status Unverified",
                "image": "",
                "image_label": "Storefront Registry",
                "location_name": location["name"],
                "location_score": location["opportunity"],
                "confidence_score": location["confidence_score"],
                "monthly_basis": rent_cap,
                "monthly_basis_label": f"{round(rent_cap / 1000)}k Target",
                "fit_score": location["opportunity"], "ranking_basis": "Area Score; Registry Vacancy Filing",
                "notes": "Matched From The NYC Storefront Registry. Asking Rent, Sale Price, Listing Photo, And Confirmed Deal Status Are Not Included In The Uploaded Source.",
                "broker_name": None, "broker_contact": None, "source_url": None, "checked_at": None,
                "latitude": listing.get("latitude"),
                "longitude": listing.get("longitude"),
                "zip_code": listing.get("zip_code") or listing.get("postcode"),
            }
        )
    candidates = sorted(properties, key=lambda row: (row["lead_type"] == "listing", row["fit_score"]), reverse=True)[:12]
    return add_site_evidence(candidates, package, concept)


def add_site_evidence(properties: list[dict], package: dict, concept: Concept | None = None) -> list[dict]:
    network = package.get("walking_network")
    if network is None:
        return properties
    for property_row in properties:
        latitude, longitude = as_float(property_row.get("latitude")), as_float(property_row.get("longitude"))
        if latitude and longitude:
            property_row["site_evidence"] = network.site_evidence(
                latitude, longitude, package.get("restaurants", []), package.get("subway_stations", []))
            evidence = property_row["site_evidence"]
            if evidence["status"] == "available" and concept is not None:
                labels = CUISINES.get(concept.cuisine, ())
                evidence["same_cuisine_restaurants"] = sum(
                    evidence["restaurant_cuisine_counts"].get(label, 0) for label in labels) if labels else None
        else:
            property_row["site_evidence"] = {"status": "unavailable", "reason": "Property coordinates are not in the source."}
    return properties


def data_feeds() -> list[dict]:
    feeds = [
        {
            "name": row.get("source") or "Source",
            "vintage": row.get("vintage") or "Not Specified",
            "grain": row.get("native_grain") or "Not Specified",
            "purpose": row.get("purpose") or "Location Intelligence",
            "coverage": row.get("coverage") or "Not Specified",
            "url": public_url(row.get("url")),
        }
        for row in integrated_package()["sources"]
    ]
    rent = load_rent_benchmarks(PROJECT_ROOT / "data")
    if rent["status"] == "available" and not any(feed["name"] == "NYC Storefront Rent Statistics" for feed in feeds):
        feeds.append({"name": "NYC Storefront Rent Statistics", "vintage": str(rent["reporting_year"]),
                      "grain": "Class 2 And 4 Registered Storefronts By Census Tract",
                      "purpose": "Reported Occupied-Rent Context; Not Asking Rent",
                      "coverage": f"{rent['tracts_with_reported_median']:,} Tracts With Published Medians",
                      "url": rent["source_url"]})
    public_opportunities = LISTINGS_PATH.parent / "public_opportunities.csv"
    if public_opportunities.is_file():
        rows = read_csv(public_opportunities)
        fresh_rows = []
        for row in rows:
            try:
                checked = date.fromisoformat(row.get("checked_at") or "")
            except ValueError:
                continue
            if date.today() - timedelta(days=90) <= checked <= date.today():
                fresh_rows.append(row)
        if fresh_rows:
            feeds.append({"name": "NYCHA Store Leasing Opportunities", "vintage": max(row["checked_at"] for row in fresh_rows),
                          "grain": "Source-Reported Individual Storefronts", "purpose": "Public Lease Offers; Availability Requires Confirmation",
                          "coverage": f"{len(fresh_rows)} Manually Checked Restaurant-Ready " + ("Opportunity" if len(fresh_rows) == 1 else "Opportunities"),
                          "url": "https://www.nyc.gov/site/nycha/business/store-leasing-available-properties.page"})
    return feeds


def market_gap_rows(locations: list[dict]) -> list[dict]:
    top = locations[:8] or locations
    if not top:
        return []

    def avg(key: str) -> int | None:
        values = [value for row in top if (value := row.get(key)) is not None]
        return round(sum(values) / len(values)) if values else None

    return [
        {
            "category": "Food And Beverage Demand",
            "current_label": f"Competition Index {avg('competition')}",
            "expected_label": f"Demand Index {avg('activity')}",
            "gap_label": f"{avg('whitespace')} Opportunity",
            "score": avg("whitespace"),
        },
        {
            "category": "Customer Fit",
            "current_label": f"Customer Index {avg('customer')}",
            "expected_label": "Concept Match",
            "gap_label": f"{avg('customer')} Fit",
            "score": avg("customer"),
        },
        {
            "category": "Access And Mobility",
            "current_label": f"Transit Index {avg('transit')}",
            "expected_label": "Walkability And Mobility",
            "gap_label": f"{avg('walkability')} Walkability" if avg("walkability") is not None else "Walkability Unavailable",
            "score": avg("walkability"),
        },
        {
            "category": "Commercial Suitability",
            "current_label": "Storefront And Land-Use Records",
            "expected_label": "Budget Scenario",
            "gap_label": f"{avg('cost')} Suitability",
            "score": avg("cost"),
        },
    ]


def unsupported_values(properties: list[dict]) -> list[str]:
    listings = [row for row in properties if row.get("lead_type") == "listing"]
    unavailable = []
    if not any(row.get("transaction") == "lease" and row.get("asking_rent") for row in listings):
        unavailable.append("Current Lease Asking Rent")
    if not any(row.get("transaction") == "purchase" and row.get("asking_price") for row in listings):
        unavailable.append("Current Sale Asking Price")
    if not any(row.get("image") for row in listings):
        unavailable.append("Listing Photos")
    if not any(row.get("broker_contact") for row in listings):
        unavailable.append("Direct Leasing Contact")
    unavailable.extend(["Confirmed Property Availability", "Restaurant Review Sentiment", "Mobile-Phone Foot Traffic"])
    return unavailable


def recommendation_for(score: int, confidence: int, risks: list[str]) -> str:
    if score >= 84 and confidence >= 76 and "Rent above current ceiling" not in risks:
        return "Strong shortlist candidate. Prioritize broker review and comparable lease research."
    if score >= 78:
        return "Promising location. Keep it in the shortlist, but pressure-test the flagged risks."
    if score >= 68:
        return "Watchlist location. Needs stronger evidence or a more specific concept fit."
    return "Lower priority for this profile unless new data changes the demand or rent picture."


@app.context_processor
def map_availability():
    return {"street_tiles_available": OSM_TILES_PATH.is_file()}


@app.errorhandler(FileNotFoundError)
def missing_dataset(error):
    return jsonify({"error": "Required local data is unavailable. See demo/README.md."}), 503


@app.route("/")
def index():
    return render_template("index.html", access=session.get("access"), email=session.get("email"), csrf=csrf_token(), auth_error=None, auth_mode="login")


@app.post("/auth/<action>")
def auth_action(action):
    if action not in {"login", "signup", "guest", "logout"}:
        return "Not found", 404
    if not csrf_valid():
        return "Invalid CSRF token. Reload the page and try again.", 400
    if action == "logout":
        session.clear()
        return redirect(url_for("index"))
    if action == "guest":
        session.clear()
        session["access"] = "guest"
        return redirect(url_for("index"))
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    error = None
    if len(email) > 254 or "@" not in email or email.startswith("@") or email.endswith("@"):
        error = "Enter a valid email address."
    elif not 8 <= len(password) <= 128:
        error = "Password must be 8-128 characters."
    elif action == "signup" and password != request.form.get("confirmation", ""):
        error = "Passwords do not match."
    if not error:
        with closing(account_db()) as connection, connection:
            if action == "signup":
                try:
                    cursor = connection.execute("INSERT INTO accounts (email, password_hash) VALUES (?, ?)", (email, generate_password_hash(password)))
                    account_id = cursor.lastrowid
                except sqlite3.IntegrityError:
                    error = "An account with this email already exists."
            else:
                row = connection.execute("SELECT id, password_hash FROM accounts WHERE email=?", (email,)).fetchone()
                if not row or not check_password_hash(row[1], password):
                    error = "Email or password is incorrect."
                else:
                    account_id = row[0]
    if error:
        return render_template("index.html", access=None, email=None, csrf=csrf_token(), auth_error=error, auth_mode=action), 400
    session.clear()
    session["access"] = "account"
    session["account_id"] = account_id
    session["email"] = email
    return redirect(url_for("index"))


@app.route("/api/workspace", methods=["GET", "PUT"])
def account_workspace():
    if session.get("access") != "account" or not session.get("account_id"):
        return jsonify({"error": "Log in to save your workspace."}), 401
    account_id = session["account_id"]
    if request.method == "PUT":
        token = request.headers.get("X-CSRF-Token", "")
        if not token or not secrets.compare_digest(token, session.get("csrf_token", "")):
            return jsonify({"error": "Invalid CSRF token."}), 403
        if request.content_length is not None and request.content_length > 550_000:
            return jsonify({"error": "Workspace is too large."}), 413
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not valid_workspace(body.get("workspace")):
            return jsonify({"error": "Invalid workspace data."}), 400
        expected_revision = body.get("revision")
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
            return jsonify({"error": "Invalid workspace revision."}), 400
        with closing(account_db()) as connection, connection:
            # Serialize the revision check and write across tabs and processes.
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT revision FROM account_workspaces WHERE account_id=?", (account_id,)).fetchone()
            revision = current[0] if current else 0
            if revision != expected_revision:
                return jsonify({"error": "Workspace changed in another session.", "revision": revision}), 409
            payload = json.dumps(body["workspace"], ensure_ascii=False, separators=(",", ":"))
            connection.execute(
                "INSERT INTO account_workspaces(account_id, payload, revision) VALUES (?, ?, ?) "
                "ON CONFLICT(account_id) DO UPDATE SET payload=excluded.payload, revision=excluded.revision",
                (account_id, payload, revision + 1),
            )
        response = jsonify({"revision": revision + 1})
    else:
        with closing(account_db()) as connection:
            row = connection.execute("SELECT payload, revision FROM account_workspaces WHERE account_id=?", (account_id,)).fetchone()
        response = jsonify({"workspace": json.loads(row[0]) if row else None, "revision": row[1] if row else 0})
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/concepts/images")
def concept_images():
    allowed = set(CUISINES) | {"general"}
    images = {}
    for directory in (CONCEPT_IMAGE_DIR, PRIVATE_CONCEPT_IMAGE_DIR):
        for path in directory.iterdir() if directory.exists() else ():
            if path.stem in allowed and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                images[path.stem] = ("/api/concepts/image/" if directory == PRIVATE_CONCEPT_IMAGE_DIR
                                     else "/static/images/concepts/") + path.name
    return jsonify({"images": images})


@app.get("/api/concepts/image/<path:filename>")
def concept_image(filename):
    path = Path(filename)
    if path.stem not in set(CUISINES) | {"general"} or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        return jsonify({"error": "Image not found."}), 404
    return send_from_directory(PRIVATE_CONCEPT_IMAGE_DIR, filename)


@app.post("/api/concepts/resolve")
def resolve_concept_api():
    values = request.get_json(silent=True)
    if not isinstance(values, dict):
        return jsonify({"error": "Submit a concept brief as a JSON object."}), 400
    try:
        return jsonify(resolve_concept(values))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@app.get("/api/menu/suggestions")
def menu_suggestions_api():
    try:
        resolved = resolve_concept(request.args)
        query = request.args.get("q", "")
        if len(query) > 80:
            raise ValueError("Menu search must be 80 characters or less.")
        result = menu_suggestions(resolved["concept"]["cuisine"], resolved["profile"],
                                  resolved["concept"]["dietary"], query,
                                  resolved["concept"]["average_check"])
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({**result, "profile": resolved["profile"], "concept": resolved["concept"],
                    "catalog_version": "editorial-2026-10-03",
                    "sections": ["Starters", "Mains", "Sides", "Desserts", "Drinks"],
                    "review_method": "No dish ratings are inferred from restaurant ratings."})


@app.post("/api/sites/analyze")
def analyze_site_api():
    values = request.get_json(silent=True)
    if not isinstance(values, dict):
        return jsonify({"error": "Submit a site coordinate as a JSON object."}), 400
    latitude, longitude = as_float(values.get("latitude")), as_float(values.get("longitude"))
    if not 40.47 <= latitude <= 40.95 or not -74.28 <= longitude <= -73.65:
        return jsonify({"error": "Choose a coordinate within the supported NYC area."}), 400
    try:
        resolved = resolve_concept(values)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    package = integrated_package()
    evidence = package["walking_network"].site_evidence(
        latitude, longitude, package["restaurants"], package["subway_stations"])
    if evidence["status"] == "available":
        labels = CUISINES[resolved["concept"]["cuisine"]]
        evidence["same_cuisine_restaurants"] = sum(
            evidence["restaurant_cuisine_counts"].get(label, 0) for label in labels) if labels else None
    return jsonify({"latitude": latitude, "longitude": longitude,
                    "concept_resolution": resolved, "site_evidence": evidence})


@app.route("/api/osm/tiles/<int:z>/<int:x>/<int:y>.pbf")
def osm_tile(z: int, x: int, y: int):
    if not OSM_TILES_PATH.is_file() or not 0 <= z <= 14 or not 0 <= x < 2 ** z or not 0 <= y < 2 ** z:
        return "", 404
    with closing(sqlite3.connect(f"file:{OSM_TILES_PATH}?mode=ro", uri=True)) as connection:
        row = connection.execute(
            "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
            (z, x, 2 ** z - 1 - y),
        ).fetchone()
    if row is None:
        return "", 404
    response = Response(row[0], mimetype="application/x-protobuf")
    if row[0][:2] == b"\x1f\x8b":
        response.headers["Content-Encoding"] = "gzip"
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@app.get("/api/map/restaurants")
def map_restaurants():
    return jsonify(restaurant_map_data())


@app.get("/api/areas")
def profile_areas():
    return jsonify({"areas": [
        {"geoid": row["geoid"], "name": tract_display_name(row), "borough": row["borough"]}
        for row in integrated_package()["tracts"]
    ]})


@app.get("/api/areas/<geoid>/profile")
def area_profile(geoid: str):
    if len(geoid) != 11 or not geoid.isdigit():
        return jsonify({"error": "Invalid tract identifier."}), 400
    tract = next((row for row in integrated_package()["tracts"] if row["geoid"] == geoid), None)
    if tract is None:
        return jsonify({"error": "Area not found."}), 404
    return jsonify(resident_worker_profile(tract))


@lru_cache(maxsize=2)
def transit_activity_tables(directory: Path) -> dict:
    paths = {
        "subway": "features/tract_subway_access.csv",
        "bike": "features/tract_citibike_activity.csv",
        "pedestrian": "features/tract_pedestrian_access.csv",
        "taxi": "features/tract_taxi_activity.csv",
    }
    tables = {name: {row["geoid"]: row for row in read_csv(directory / path)} for name, path in paths.items()}
    stations = read_csv(directory / "entities/subway_stations_weekly_activity.csv")
    bike_path = directory / "entities/citibike_stations_latest_month.csv"
    bike_stations = read_csv(bike_path if bike_path.is_file() else directory / "entities/citibike_stations_august_2026.csv")
    sites = {}
    for row in read_csv(directory / "entities/pedestrian_counts_long.csv"):
        identifier = row.get("objectid")
        period = (int(row.get("count_year") or 0), int(row.get("count_month") or 0))
        if identifier and period > sites.get(identifier, ((0, 0), []))[0]:
            sites[identifier] = (period, [row])
        elif identifier and period == sites.get(identifier, ((0, 0), []))[0]:
            sites[identifier][1].append(row)
    tables["stations"] = stations
    tables["bike_stations"] = bike_stations
    tables["sites"] = sites
    tables["taxi_zones"] = {row["location_id"]: row for row in read_csv(directory / "features/taxi_zone_monthly_activity.csv")}
    return tables


@app.get("/api/areas/<geoid>/transit-activity")
def area_transit_activity(geoid: str):
    if len(geoid) != 11 or not geoid.isdigit():
        return jsonify({"error": "Invalid tract identifier."}), 400
    tract = next((row for row in integrated_package()["tracts"] if row["geoid"] == geoid), None)
    if tract is None:
        return jsonify({"error": "Area not found."}), 404
    try:
        tables = transit_activity_tables(integrated_directory())
    except FileNotFoundError:
        return jsonify({"error": "Transit or activity source table is unavailable."}), 503
    subway = tables["subway"].get(geoid, {})
    bike = tables["bike"].get(geoid, {})
    pedestrian = tables["pedestrian"].get(geoid, {})
    taxi = tables["taxi"].get(geoid, {})
    in_tract_stations = [row for row in tables["stations"] if row.get("geoid") == geoid]
    in_tract_bikes = [row for row in tables["bike_stations"] if row.get("geoid") == geoid]
    site_period, site_rows = tables["sites"].get(pedestrian.get("nearest_pedestrian_count_site_objectid"), ((0, 0), []))
    zone = tables["taxi_zones"].get(taxi.get("location_id"), {})
    number = source_number
    package = integrated_package()
    bike_suffix = "latest_month" if "citibike_departures_latest_month" in bike else "august_2026"
    taxi_suffix = "latest_month" if "pickups_latest_month" in taxi else "may_2026"
    def month_label(value, fallback):
        return date.fromisoformat(value + "-01").strftime("%B %Y") if value else fallback
    return jsonify({
        "geoid": geoid, "tract_name": tract_display_name(tract), "borough": tract.get("borough"),
        "subway": {
            "station_count": len(in_tract_stations),
            "weekly_entries": sum(number(row, "weekly_ridership") or 0 for row in in_tract_stations),
            "weekly_transfers": sum(number(row, "weekly_transfers") or 0 for row in in_tract_stations),
            "stations": [{"name": row.get("station_complex") or "Unnamed station", "weekly_entries": number(row, "weekly_ridership"),
                          "weekly_transfers": number(row, "weekly_transfers")} for row in in_tract_stations],
            "nearest_name": subway.get("nearest_subway_station_complex") or None,
            "nearest_distance_miles": number(subway, "nearest_subway_distance_miles"),
            "nearest_weekly_entries": number(subway, "nearest_subway_weekly_ridership"),
            "period": package["subway_vintage"], "source": "MTA hourly ridership",
            "nearest_dayparts": package["subway_dayparts"].get(subway.get("nearest_subway_station_complex")),
        },
        "bike": {
            "station_count": len(in_tract_bikes),
            "departures": number(bike, f"citibike_departures_{bike_suffix}"),
            "arrivals": number(bike, f"citibike_arrivals_{bike_suffix}"),
            "evening_departures": number(bike, f"citibike_evening_departures_{bike_suffix}"),
            "weekend_departures": number(bike, f"citibike_weekend_departures_{bike_suffix}"),
            "nearest_name": bike.get("nearest_citibike_station_name") or None,
            "nearest_distance_miles": number(bike, "nearest_citibike_distance_miles"),
            "nearest_departures": number(bike, f"nearest_citibike_departures_{bike_suffix}"),
            "period": month_label(bike.get("citibike_activity_month"), "August 2026"), "source": "Citi Bike trip archive",
        },
        "pedestrian": {
            "monitor_name": pedestrian.get("nearest_pedestrian_count_site_loc") or None,
            "distance_miles": number(pedestrian, "nearest_pedestrian_count_site_distance_miles"),
            "observed_total": number(pedestrian, "nearest_pedestrian_count_site_latest_pedestrian_count_total"),
            "period": f"{date(site_period[0], site_period[1], 1).strftime('%B %Y')}" if site_period[0] and site_period[1] else None,
            "period_counts": {row["time_period"]: number(row, "pedestrian_count") for row in site_rows},
            "source": "NYC DOT pedestrian counts",
        },
        "taxi": {
            "zone": taxi.get("taxi_zone") or zone.get("taxi_zone") or None,
            "zone_borough": taxi.get("taxi_borough") or zone.get("taxi_borough") or None,
            "pickups": number(taxi, f"pickups_{taxi_suffix}"), "dropoffs": number(taxi, f"dropoffs_{taxi_suffix}"),
            "active_days": number(taxi, f"active_days_{taxi_suffix}"),
            "period": month_label(taxi.get("taxi_activity_month"), "May 2026"), "source": "TLC HVFHV trip records",
        },
    })


@app.get("/api/storefronts")
def storefront_registry():
    directory = integrated_directory()
    if not (directory / "entities/current_storefronts.csv").is_file():
        return jsonify({"error": "Storefront registry file is unavailable."}), 503
    rows = integrated_package().get("storefronts")
    if rows is None:
        return jsonify({"error": "Storefront registry records are unavailable."}), 503
    records = []
    for row in rows:
        reported = as_bool(row.get("vacant_current"))
        records.append({
            "id": row.get("borough_block_lot") or None,
            "address": (row.get("property_street_address_or") or "").strip() or None,
            "borough": row.get("borough") or None,
            "geoid": row.get("geoid") or None,
            "zip_code": row.get("zip_code") or row.get("postcode") or None,
            "unit": row.get("unit") or None,
            "reported_activity": row.get("primary_business_activity") or None,
            "vacancy_status": "reported_vacant" if reported else "unknown",
            "vacant_on_dec_31": str(row.get("vacant_on_12_31") or "").lower() == "yes",
            "vacant_on_jun_30_or_sale": str(row.get("vacant_6_30_or_date_sold") or "").lower() == "yes",
            "reporting_year": row.get("reporting_year") or None,
            "filing_due_date": row.get("filing_due_date") or None,
        })
    return jsonify({"records": records, "total": len(records), "source": "NYC Storefront Registry",
                    "reporting_years": sorted({row["reporting_year"] for row in records if row["reporting_year"]}),
                    "filing_due_dates": sorted({row["filing_due_date"] for row in records if row["filing_due_date"]})})


def current_restaurant_records(rows: list[dict]) -> list[dict]:
    """Keep one latest recorded row per establishment before checking its current status."""
    by_id = {}
    for row in rows:
        identifier = (row.get("camis") or "").strip()
        if identifier and (identifier not in by_id or
                           (row.get("inspection_date") or "") >= (by_id[identifier].get("inspection_date") or "")):
            by_id[identifier] = row
    return [row for row in by_id.values() if as_bool(row.get("active_establishment"))]


@app.get("/api/locations/<geoid>/competition")
def location_competition(geoid: str):
    if len(geoid) != 11 or not geoid.isdigit():
        return jsonify({"error": "Invalid tract identifier."}), 400
    cuisine = request.args.get("cuisine", "any")
    if cuisine not in CUISINES:
        return jsonify({"error": "Unsupported cuisine."}), 400
    directory = integrated_directory()
    restaurant_file = directory / "entities" / "current_restaurants.csv"
    if not restaurant_file.is_file():
        return jsonify({"error": "Restaurant records are unavailable."}), 503
    package = integrated_package()
    tract = next((row for row in package["tracts"] if row["geoid"] == geoid), None)
    if tract is None:
        return jsonify({"error": "Location not found."}), 404
    source_rows = package.get("restaurants")
    if not source_rows:
        return jsonify({"error": "Restaurant records are unavailable."}), 503
    labels = set(CUISINES[cuisine])
    active = current_restaurant_records(source_rows)
    eligible = [row for row in active if row.get("geoid") == geoid]
    neighborhood = [row for row in active if tract.get("nta_code") and row.get("nta") == tract["nta_code"]]
    counts = {}
    restaurants = []
    for row in eligible:
        classification = (row.get("cuisine_description") or "").strip() or "Unclassified"
        counts[classification] = counts.get(classification, 0) + 1
        restaurants.append({
            "name": (row.get("dba") or "").strip() or "Unnamed Restaurant",
            "cuisine": classification,
            "address": " ".join(part for part in ((row.get("building") or "").strip(),
                                                      (row.get("street") or "").strip()) if part),
            "same_cuisine": classification in labels,
        })
    restaurants.sort(key=lambda row: (row["name"].casefold(), row["cuisine"].casefold(), row["address"].casefold()))
    return jsonify({
        "geoid": geoid,
        "tract_name": tract_display_name(tract),
        "borough": tract.get("borough") or "Borough unavailable",
        "tract_restaurant_count": len(restaurants),
        "neighborhood": tract.get("nta_name"),
        "neighborhood_restaurant_count": len(neighborhood),
        "tract_same_cuisine_count": sum(row["same_cuisine"] for row in restaurants) if labels else None,
        "neighborhood_same_cuisine_count": sum((row.get("cuisine_description") or "").strip() in labels for row in neighborhood) if labels else None,
        "cuisine_counts": [{"cuisine": label, "count": count} for label, count in
                           sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))],
        "same_cuisine_count": sum(row["same_cuisine"] for row in restaurants) if labels else None,
        "cuisine_supported": bool(labels),
        "restaurants": restaurants,
        "source": "NYC DOHMH restaurant inspections, integrated current establishments",
        "latest_inspection_date": max((row.get("inspection_date") or "" for row in source_rows), default="") or None,
    })


@app.route("/api/dashboard")
def dashboard():
    try:
        resolution = resolve_concept(request.args)
        concept = Concept(**resolution["concept"])
        rent_cap = int(request.args.get("rent_cap", "18000"))
        purchase_budget = int(request.args.get("purchase_budget", "3000000"))
        if not 8000 <= rent_cap <= 35000:
            raise ValueError("Monthly budget must be between $8,000 and $35,000.")
        if not 100000 <= purchase_budget <= 50000000:
            raise ValueError("Purchase budget must be between $100,000 and $50 million.")
        deal_type = request.args.get("deal_type", "lease")
        if deal_type not in {"lease", "purchase", "either"}:
            raise ValueError("Choose lease, purchase, or both.")
        finance = operating_scenario(request.args, rent_cap, concept.average_check, deal_type)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    concept_name = (request.args.get("concept_name", "Restaurant Concept") or "Restaurant Concept").strip()[:80]
    profile = resolution["profile"]
    borough = request.args.get("borough", "")
    if borough not in {"", "Brooklyn", "Queens", "Manhattan", "Bronx", "Staten Island"}:
        borough = ""
    ranked_locations = tuned_locations(profile, rent_cap, borough, concept, limit=None)
    if not ranked_locations:
        return jsonify({"locations": [], "error": "No eligible tracts match this borough."})
    locations = ranked_locations[:24]
    best = locations[0]
    requested_ids = list(dict.fromkeys(
        value for value in request.args.getlist("saved_id")[:4]
        if len(value) == 11 and value.isdigit()
    ))
    ranked_lookup = {row["id"]: row for row in ranked_locations}
    missing_ids = set(requested_ids) - ranked_lookup.keys()
    if missing_ids:
        package = integrated_package()
        for row in package["tracts"]:
            if row["geoid"] in missing_ids:
                ranked_lookup[row["geoid"]] = real_location_from_tract(row, profile, rent_cap, package, concept)
    saved_locations = [ranked_lookup[value] for value in requested_ids if value in ranked_lookup]
    survival_status = attach_predictions(locations + saved_locations, app.config["SURVIVAL_CONFIG"])
    avg_confidence = round(sum(row["confidence_score"] for row in locations) / len(locations))
    finance["purchase_budget"] = purchase_budget
    finance["average_check"] = concept.average_check
    properties = matching_properties(ranked_locations, deal_type, rent_cap, purchase_budget, concept, profile)
    rent_data = load_rent_benchmarks(PROJECT_ROOT / "data")
    rent_by_geoid = rent_data.get("by_geoid", {})
    return jsonify(
        {
            "survival_model": survival_status,
            "locations": locations,
            "saved_locations": saved_locations,
            "selected": best["id"],
            "feeds": data_feeds(),
            "whitespace": market_gap_rows(locations),
            "vendor_windows": VENDOR_WINDOWS,
            "properties": properties,
            "listing_source_connected": bool(listing_source_paths()),
            "data_layers": DATA_LAYERS,
            "reports": REPORTS,
            "scoring": {
                "weights": PROFILE_WEIGHTS.get(profile, PROFILE_WEIGHTS["restaurant"]),
                "signals": {component["key"]: {"label": component["label"], "coverage": component["coverage"], "description": component["description"]} for component in best["score_components"]},
                "avg_confidence": avg_confidence,
                "method": "Weighted Location-Fit Score Across Demand, Customer Fit, Access, Market Gap, Competition Balance, And Commercial Suitability",
            },
            "finance": finance,
            "rent_benchmarks": {
                "status": rent_data["status"], "reporting_year": rent_data.get("reporting_year"),
                "source_url": rent_data["source_url"], "retrieved_at": rent_data.get("retrieved_at"),
                "tracts_with_reported_median": rent_data.get("tracts_with_reported_median", 0),
                "by_geoid": {row["id"]: rent_by_geoid[row["id"]]
                             for row in locations + saved_locations if row["id"] in rent_by_geoid},
            },
            "meta": {
                "project": "Groundwork NYC",
                "concept_name": concept_name,
                "concept": concept.public(),
                "concept_resolution": resolution,
                "model_version": MODEL_VERSION,
                "assessment_type": "Uncalibrated Screening Index",
                "scope": "NYC Restaurant And Bar Site Selection",
                "architecture": "Flask API Using Integrated NYC Tract, Storefront, Mobility, Competition, Demographic, And Land-Use Features",
                "api_contract": "Locations, Properties, Feeds, Data Quality, Reports, Finance",
                "deal_type": deal_type,
                "borough": borough or "All NYC",
                "primary_dataset": f"{integrated_package()['data_path']}/master_tract_features.csv",
                "data_release": integrated_package()["data_release"],
                "unsupported_values": unsupported_values(properties),
            },
        }
    )


@lru_cache(maxsize=16)
def cached_hex_surface(directory: Path, concept: Concept, profile: str, borough: str, cell_resolution: int):
    package = _load_integrated_package(directory)
    return concept_surface(package, directory, concept, profile,
                           PROFILE_WEIGHTS.get(profile, PROFILE_WEIGHTS["restaurant"]), borough,
                           cell_resolution=cell_resolution)


@app.get("/api/hex-demand")
def hex_demand():
    try:
        level = request.args.get("level", "sector")
        if level not in {"sector", "cell", "fine"}:
            raise ValueError("Choose sector, cell or fine detail.")
        borough = request.args.get("borough", "")
        if borough not in {"", "Brooklyn", "Queens", "Manhattan", "Bronx", "Staten Island"}:
            raise ValueError("Choose a supported borough.")
        resolution = resolve_concept(request.args)
        concept = Concept(**resolution["concept"])
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    package = integrated_package()
    directory = integrated_directory()
    cell_resolution = 9 if level == "fine" else 8
    surface = cached_hex_surface(directory, concept, resolution["profile"], borough, cell_resolution)
    return jsonify({"type": "FeatureCollection", "features": surface["sector" if level == "sector" else "cell"], "meta": {
        "level": level, "resolution": 7 if level == "sector" else cell_resolution,
        "data_release": package["data_release"], "concept": resolution["concept"],
        "assessment_type": "Concept-specific screening index, not measured visits or a revenue forecast",
        "basis": "Concept-specific demand, customer fit, access, market opportunity and competition balance; format-specific weights and cell-center transit access",
        "signal_weights": surface_weights(PROFILE_WEIGHTS.get(resolution["profile"], PROFILE_WEIGHTS["restaurant"])),
        "field_sources": resolution["field_sources"],
        "not_scored": ["Lease or purchase choice", "Rent and purchase budgets", "Unclassified free-text details"] +
                      (["Dietary customer demand for this identity"] if concept.dietary in {"halal", "kosher", "gluten_free"} else []),
    }})


@app.get("/api/evaluation")
def get_evaluation_status():
    return jsonify(evaluation_status(PROJECT_ROOT / "data"))


@app.post("/api/evaluation/run")
def evaluate_model():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "A JSON object is required."}), 400
    if any(not isinstance(value, str) for value in payload.values()):
        return jsonify({"error": "Evaluation parameters must be strings."}), 400
    try:
        result = run_evaluation(integrated_package(), PROJECT_ROOT / "data",
                                cuisine=payload.get("cuisine", "korean"),
                                target=payload.get("target", "market_presence"), cutoff=payload.get("cutoff"))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except ImportError:
        return jsonify({"error": "Install demo/requirements-evaluation.txt to run evaluation."}), 503
    return jsonify(result)


@app.get("/api/models/survival")
def survival_model_status():
    _, status = model_state(app.config["SURVIVAL_CONFIG"])
    return jsonify(status)


@app.get("/api/geography/nyc-boundary")
def nyc_map_boundary():
    from map_geography import city_partition
    try:
        directory = integrated_directory()
        path = directory / "geography/nyc_2020_census_tracts.geojson"
        result = city_partition(str(path), (path.stat().st_mtime_ns, path.stat().st_size))
        return jsonify({**result, "meta": {**result["meta"], "data_release": directory.name}})
    except (OSError, ValueError):
        return jsonify({"error": "NYC boundary is temporarily unavailable."}), 503


if __name__ == "__main__":
    app.run(debug=True, port=5001)
