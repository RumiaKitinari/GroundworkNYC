from __future__ import annotations

import csv
import os
import secrets
import sqlite3
from copy import deepcopy
from contextlib import closing
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse
from flask import Flask, Response, jsonify, render_template, request, redirect, session, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from scoring import CUISINES, Concept, ScreeningModel, MODEL_VERSION, resolve_concept
from evaluation import evaluation_status, run_evaluation
from osm_network import WalkingNetwork
from financials import operating_scenario


app = Flask(__name__)
INSTANCE_DIR = Path(__file__).resolve().parents[1] / "instance"
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
    return connection


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def csrf_valid():
    saved = session.get("csrf_token", "")
    submitted = request.form.get("csrf_token", "")
    return bool(saved and submitted) and secrets.compare_digest(saved, submitted)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INTEGRATED_DATA_DIR = PROJECT_ROOT / "data" / "integrated" / "restaurant_bar_location_data_ready"
MASTER_TRACT_PATH = INTEGRATED_DATA_DIR / "master_tract_features.csv"
STOREFRONTS_PATH = INTEGRATED_DATA_DIR / "entities" / "current_storefronts.csv"
SOURCE_CATALOG_PATH = INTEGRATED_DATA_DIR / "source_catalog.csv"
FEATURE_READINESS_PATH = INTEGRATED_DATA_DIR / "feature_readiness.csv"
OSM_TILES_PATH = PROJECT_ROOT / "data" / "osm" / "NewYork-mbtiles-shortbread" / "NewYork.mbtiles"
OSM_WALK_NETWORK_PATH = PROJECT_ROOT / "data" / "osm" / "nyc_walk_network.sqlite"
LISTINGS_PATH = PROJECT_ROOT / "data" / "listings" / "verified_properties.csv"


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


@lru_cache(maxsize=1)
def integrated_package() -> dict:
    master_rows = read_csv(MASTER_TRACT_PATH)
    restaurants = read_csv(INTEGRATED_DATA_DIR / "entities" / "current_restaurants.csv")
    eligible_rows = [
        row
        for row in master_rows
        if as_bool(row.get("eligible_for_location_screening"))
        and row.get("centroid_latitude")
        and row.get("centroid_longitude")
        and row.get("borough") != "Staten Island"
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
        "nearest_citibike_distance_miles",
        "nearest_pedestrian_count_site_distance_miles",
        "nearest_pedestrian_count_site_latest_pedestrian_count_total",
        "pickups_may_2026",
        "dropoffs_may_2026",
        "retail_area_sqft",
        "mixed_use_parcel_count",
        "vacant_land_parcel_count",
        "reported_storefront_property_count",
        "reported_vacant_storefront_count",
        "reported_storefront_vacancy_share",
        "permitted_event_count_2026",
        "permitted_event_hours_2026",
        "food_nightlife_pois_per_1000_residents",
        "jobs_per_1000_residents",
    ]
    latitudes = [as_float(row["centroid_latitude"]) for row in eligible_rows]
    longitudes = [as_float(row["centroid_longitude"]) for row in eligible_rows]
    return {
        "tracts": eligible_rows,
        "percentiles": percentile_maps(eligible_rows, numeric_columns),
        "storefronts": read_csv(STOREFRONTS_PATH),
        "restaurants": restaurants,
        "subway_stations": read_csv(INTEGRATED_DATA_DIR / "entities" / "subway_stations_weekly_activity.csv"),
        "walking_network": WalkingNetwork(OSM_WALK_NETWORK_PATH),
        "sources": read_csv(SOURCE_CATALOG_PATH),
        "readiness": read_csv(FEATURE_READINESS_PATH),
        "screening_model": ScreeningModel(eligible_rows, restaurants),
        "bounds": {
            "lat_min": min(latitudes),
            "lat_max": max(latitudes),
            "lon_min": min(longitudes),
            "lon_max": max(longitudes),
        },
    }


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


def matching_properties(locations: list[dict], deal_type: str, rent_cap: int, purchase_budget: int, concept: Concept | None = None) -> list[dict]:
    package = integrated_package()
    location_lookup = {location["geoid"]: location for location in locations}
    properties = []
    if LISTINGS_PATH.is_file():
        for listing in read_csv(LISTINGS_PATH):
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
            if transaction == "lease" and rent is None or transaction == "purchase" and price is None:
                continue
            if (transaction == "lease" and rent > rent_cap) or (transaction == "purchase" and price > purchase_budget):
                continue
            properties.append({
                "id": listing.get("listing_id") or f"listing-{len(properties)}",
                "location_id": location["id"], "geoid": location["geoid"],
                "title": listing.get("title") or "Restaurant Property", "address": listing.get("address") or "Address Pending",
                "borough": location["borough"], "transaction": transaction, "transaction_label": "Lease Listing" if transaction == "lease" else "Purchase Listing",
                "lead_type": "listing", "asking_rent": rent, "asking_price": price,
                "price_label": f"${round(rent):,}/Month" if rent else f"${round(price):,}",
                "sqft": as_float(listing.get("sqft")) or 0, "sqft_label": listing.get("sqft") or "Size Pending",
                "frontage": listing.get("frontage") or "Frontage Pending", "condition": listing.get("condition") or "Condition Pending",
                "availability": listing.get("availability") or "Status Unverified", "image": public_url(listing.get("image_url")) or "",
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
    status_for_coverage = {
        "complete": "mapped",
        "full": "mapped",
        "filtered": "mapped",
        "sparse": "review",
    }
    feeds = []
    for index, row in enumerate(integrated_package()["sources"][:10]):
        coverage = (row.get("coverage") or "").lower()
        status = "review"
        for token, mapped_status in status_for_coverage.items():
            if token in coverage:
                status = mapped_status
                break
        feeds.append(
            {
                "name": row.get("source") or "Source",
                "status": status,
                "records": row.get("vintage") or row.get("native_grain") or "Source Available",
                "signal": clamp(92 - index * 4 if status == "mapped" else 72 - index),
                "join": row.get("native_grain") or "Integrated",
                "owner": row.get("purpose") or "Location Intelligence",
            }
        )
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


def unsupported_values() -> list[str]:
    return [
        "Exact Asking Rent",
        "Asking Sale Price",
        "Listing Photos",
        "Confirmed Lease Or Purchase Availability",
        "Restaurant Review Sentiment",
        "Mobile-Phone Foot Traffic",
    ]


def recommendation_for(score: int, confidence: int, risks: list[str]) -> str:
    if score >= 84 and confidence >= 76 and "Rent above current ceiling" not in risks:
        return "Strong shortlist candidate. Prioritize broker review and comparable lease research."
    if score >= 78:
        return "Promising location. Keep it in the shortlist, but pressure-test the flagged risks."
    if score >= 68:
        return "Watchlist location. Needs stronger evidence or a more specific concept fit."
    return "Lower priority for this profile unless new data changes the demand or rent picture."


@app.route("/")
def index():
    return render_template("index.html", access=session.get("access"), email=session.get("email"), csrf=csrf_token(), auth_error=None, auth_mode="login", street_tiles_available=OSM_TILES_PATH.is_file())


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
        error = "Password must be 8–128 characters."
    elif action == "signup" and password != request.form.get("confirmation", ""):
        error = "Passwords do not match."
    if not error:
        with account_db() as connection:
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
        return render_template("index.html", access=None, email=None, csrf=csrf_token(), auth_error=error, auth_mode=action, street_tiles_available=OSM_TILES_PATH.is_file()), 400
    session.clear()
    session["access"] = "account"
    session["account_id"] = account_id
    session["email"] = email
    return redirect(url_for("index"))


@app.post("/api/concepts/resolve")
def resolve_concept_api():
    values = request.get_json(silent=True)
    if not isinstance(values, dict):
        return jsonify({"error": "Submit a concept brief as a JSON object."}), 400
    try:
        return jsonify(resolve_concept(values))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


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
    if borough not in {"", "Brooklyn", "Queens", "Manhattan", "Bronx"}:
        borough = ""
    ranked_locations = tuned_locations(profile, rent_cap, borough, concept, limit=None)
    if not ranked_locations:
        return jsonify({"locations": [], "error": "No eligible tracts match this borough."})
    locations = ranked_locations[:24]
    best = locations[0]
    avg_confidence = round(sum(row["confidence_score"] for row in locations) / len(locations))
    finance["purchase_budget"] = purchase_budget
    finance["average_check"] = concept.average_check
    return jsonify(
        {
            "locations": locations,
            "selected": best["id"],
            "feeds": data_feeds(),
            "whitespace": market_gap_rows(locations),
            "vendor_windows": VENDOR_WINDOWS,
            "properties": matching_properties(ranked_locations, deal_type, rent_cap, purchase_budget, concept),
            "data_layers": DATA_LAYERS,
            "reports": REPORTS,
            "scoring": {
                "weights": PROFILE_WEIGHTS.get(profile, PROFILE_WEIGHTS["restaurant"]),
                "signals": {component["key"]: {"label": component["label"], "coverage": component["coverage"], "description": component["description"]} for component in best["score_components"]},
                "avg_confidence": avg_confidence,
                "method": "Weighted Location-Fit Score Across Demand, Customer Fit, Access, Market Gap, Competition Balance, And Commercial Suitability",
            },
            "finance": finance,
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
                "primary_dataset": "data/integrated/restaurant_bar_location_data_ready/master_tract_features.csv",
                "unsupported_values": unsupported_values(),
            },
        }
    )


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


if __name__ == "__main__":
    app.run(debug=True, port=5001)
