from __future__ import annotations

import csv
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from flask import Flask, jsonify, render_template, request


app = Flask(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INTEGRATED_DATA_DIR = PROJECT_ROOT / "data" / "integrated" / "restaurant_bar_location_data_ready"
MASTER_TRACT_PATH = INTEGRATED_DATA_DIR / "master_tract_features.csv"
STOREFRONTS_PATH = INTEGRATED_DATA_DIR / "entities" / "current_storefronts.csv"
SOURCE_CATALOG_PATH = INTEGRATED_DATA_DIR / "source_catalog.csv"
FEATURE_READINESS_PATH = INTEGRATED_DATA_DIR / "feature_readiness.csv"


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


SCORING_SIGNALS = {
    "demand": {"label": "Demand Strength", "coverage": 82, "description": "Resident, Worker, Foot Traffic, And Time-Of-Day Demand Indicators."},
    "customer_fit": {"label": "Customer Fit", "coverage": 88, "description": "Alignment Between The Selected Concept And The Local Customer Base."},
    "access": {"label": "Access And Visibility", "coverage": 79, "description": "Walkability, Transit Access, And Street-Level Movement Indicators."},
    "market_gap": {"label": "Market Gap", "coverage": 69, "description": "Underserved Food And Beverage Categories Near The Selected Trade Area."},
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
        "sources": read_csv(SOURCE_CATALOG_PATH),
        "readiness": read_csv(FEATURE_READINESS_PATH),
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
    if profile == "coffee":
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


def real_location_from_tract(row: dict, profile: str, rent_cap: int, package: dict) -> dict:
    maps = package["percentiles"]
    competitor_column = concept_competition_column(profile)
    taxi_activity = as_float(row.get("pickups_may_2026")) + as_float(row.get("dropoffs_may_2026"))
    row_with_taxi = dict(row, taxi_total_activity=taxi_activity)
    if "taxi_total_activity" not in maps:
        taxi_values = sorted({as_float(r.get("pickups_may_2026")) + as_float(r.get("dropoffs_may_2026")) for r in package["tracts"]})
        maps["taxi_total_activity"] = {str(value): round(i / max(1, len(taxi_values) - 1) * 100) for i, value in enumerate(taxi_values)}

    demand = weighted(
        [
            (pct(row, maps, "population_density_per_sq_mile"), 0.18),
            (pct(row, maps, "job_density_per_sq_mile"), 0.18),
            (pct(row, maps, "nearest_subway_weekly_ridership"), 0.13),
            (pct(row_with_taxi, maps, "taxi_total_activity"), 0.13),
            (pct(row, maps, "nearest_pedestrian_count_site_latest_pedestrian_count_total"), 0.13),
            (pct(row, maps, "permitted_event_hours_2026"), 0.10),
            (pct(row, maps, "citibike_departures_august_2026"), 0.08),
            (pct(row, maps, "jobs_accommodation_food_services"), 0.07),
        ]
    )
    customer_fit = weighted(
        [
            (pct(row, maps, "median_household_income_2024"), 0.28),
            (pct(row, maps, "population_density_per_sq_mile"), 0.24),
            (pct(row, maps, "jobs_per_1000_residents"), 0.18),
            (pct(row, maps, "jobs_accommodation_food_services"), 0.16),
            (pct(row, maps, "permitted_event_count_2026"), 0.14),
        ]
    )
    access = weighted(
        [
            (pct(row, maps, "national_walkability_index"), 0.26),
            (pct(row, maps, "smart_location_score"), 0.22),
            (pct(row, maps, "nearest_subway_distance_miles", inverse=True), 0.18),
            (pct(row, maps, "nearest_citibike_distance_miles", inverse=True), 0.12),
            (pct(row, maps, "nearest_pedestrian_count_site_distance_miles", inverse=True), 0.10),
            (pct(row, maps, "subway_weekly_ridership"), 0.12),
        ]
    )
    competition_pressure = pct(row, maps, competitor_column)
    competition_balance = clamp(100 - competition_pressure * 0.68 + demand * 0.24 + pct(row, maps, "grade_a_share") * 0.08)
    market_gap = clamp(demand * 0.55 + (100 - competition_pressure) * 0.30 + pct(row, maps, "reported_vacant_storefront_count") * 0.15)
    commercial = weighted(
        [
            (pct(row, maps, "retail_area_sqft"), 0.24),
            (pct(row, maps, "mixed_use_parcel_count"), 0.18),
            (pct(row, maps, "reported_storefront_property_count"), 0.18),
            (pct(row, maps, "reported_vacant_storefront_count"), 0.18),
            (pct(row, maps, "national_walkability_index"), 0.12),
            (pct(row, maps, "vacant_land_parcel_count"), 0.10),
        ]
    )
    components = {
        "demand": demand,
        "customer_fit": customer_fit,
        "access": access,
        "market_gap": market_gap,
        "competition_balance": competition_balance,
        "economics": commercial,
    }
    weights = PROFILE_WEIGHTS.get(profile, PROFILE_WEIGHTS["restaurant"])
    raw_score = sum(components[key] * weight for key, weight in weights.items())
    confidence_score = weighted(
        [
            (100 if row.get("population_2024") else 0, 0.15),
            (100 if row.get("median_household_income_2024") else 0, 0.12),
            (100 if row.get("food_nightlife_poi_count") not in ("", None) else 0, 0.14),
            (100 if row.get("nearest_subway_distance_miles") else 0, 0.12),
            (100 if row.get("nearest_pedestrian_count_site_latest_pedestrian_count_total") else 0, 0.10),
            (100 if row.get("pickups_may_2026") else 0, 0.12),
            (100 if row.get("retail_area_sqft") else 0, 0.12),
            (100 if row.get("reported_storefront_property_count") not in ("", None) else 0, 0.13),
        ]
    )
    risk_flags = []
    if competition_pressure >= 84:
        risk_flags.append("High Direct Competition")
    if as_float(row.get("nearest_pedestrian_count_site_distance_miles"), 99) > 1.5:
        risk_flags.append("Pedestrian Count Site Is Distant")
    if not row.get("reported_vacant_storefront_count") or as_float(row.get("reported_vacant_storefront_count")) == 0:
        risk_flags.append("No Reported Vacant Storefronts In Source")
    if as_float(row.get("median_household_income_2024")) == 0:
        risk_flags.append("Income Estimate Missing")
    if not risk_flags:
        risk_flags.append("No Major Data-Supported Risk Flag")

    x, y = map_position(row, package["bounds"])
    component_rows = [
        {
            "key": key,
            "label": SCORING_SIGNALS[key]["label"],
            "score": components[key],
            "weight": round(weights[key] * 100),
            "coverage": SCORING_SIGNALS[key]["coverage"],
            "description": SCORING_SIGNALS[key]["description"],
        }
        for key in weights
    ]
    opportunity = clamp(raw_score, 1, 99)
    return {
        "id": row["geoid"],
        "geoid": row["geoid"],
        "name": tract_display_name(row),
        "borough": row.get("borough") or "NYC",
        "x": x,
        "y": y,
        "opportunity": opportunity,
        "walkability": pct(row, maps, "national_walkability_index"),
        "activity": demand,
        "whitespace": market_gap,
        "transit": pct(row, maps, "nearest_subway_weekly_ridership"),
        "customer": customer_fit,
        "competition": competition_pressure,
        "cost": commercial,
        "confidence": "high" if confidence_score >= 84 else "medium high" if confidence_score >= 70 else "medium" if confidence_score >= 55 else "limited",
        "confidence_score": confidence_score,
        "archetype": "bar/nightlife" if profile == "bar" else "coffee/breakfast" if profile == "coffee" else "restaurant",
        "rent": rent_cap,
        "rent_label": "Pending",
        "sqft": round(as_float(row.get("retail_area_sqft")) or as_float(row.get("commercial_area_sqft")) or 0),
        "score_components": component_rows,
        "risk_flags": risk_flags,
        "recommendation": recommendation_for(opportunity, confidence_score, risk_flags),
        "why": [
            f"Demand score is {demand}, supported by population density, jobs, transit, taxi activity, pedestrian counts, and event indicators.",
            f"Competition pressure is {competition_pressure}, based on tract-level {profile} competitor counts from the integrated POI layer.",
            f"Commercial suitability is {commercial}, using retail area, mixed-use parcels, storefront records, and walkability.",
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


def tuned_locations(profile: str, rent_cap: int, borough: str = "") -> list[dict]:
    package = integrated_package()
    rows = package["tracts"]
    if borough:
        rows = [row for row in rows if row.get("borough") == borough]
    locations = [real_location_from_tract(row, profile, rent_cap, package) for row in rows]
    return sorted(locations, key=lambda row: row["opportunity"], reverse=True)[:24]


def matching_properties(locations: list[dict], deal_type: str, rent_cap: int) -> list[dict]:
    package = integrated_package()
    location_lookup = {location["geoid"]: location for location in locations}
    transaction = "purchase" if deal_type == "purchase" else "lease"
    transaction_label = "Registry Lead"
    properties = []
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
        bbl = listing.get("borough_block_lot") or f"{listing.get('geoid')}-{listing.get('property_street_address_or')}"
        if bbl in seen_bbls:
            continue
        seen_bbls.add(bbl)
        vacant_bonus = 10 if as_bool(listing.get("vacant_current")) else 0
        budget_fit = 74 if rent_cap >= 18000 else 68
        address = title_case(listing.get("property_street_address_or") or "Storefront Address Not In Source")
        property_type = title_case(listing.get("primary_business_activity") or "Storefront Record")
        properties.append(
            {
                "id": bbl,
                "location_id": location["id"],
                "geoid": listing.get("geoid"),
                "title": f"{property_type} Storefront",
                "address": address,
                "borough": location["borough"],
                "transaction": transaction,
                "transaction_label": transaction_label,
                "asking_rent": None,
                "asking_price": None,
                "price_label": "Pending",
                "sqft": 0,
                "sqft_label": "Size Pending",
                "frontage": "Frontage Pending",
                "condition": property_type,
                "availability": "Reported Vacant" if as_bool(listing.get("vacant_current")) else "Storefront Filing",
                "image": "",
                "image_label": "Storefront Registry",
                "location_name": location["name"],
                "location_score": location["opportunity"],
                "confidence_score": location["confidence_score"],
                "monthly_basis": rent_cap,
                "monthly_basis_label": f"{round(rent_cap / 1000)}k Target",
                "fit_score": clamp(location["opportunity"] * 0.62 + location["confidence_score"] * 0.18 + budget_fit * 0.10 + vacant_bonus),
                "notes": "Matched From The NYC Storefront Registry. Asking Rent, Sale Price, Listing Photo, And Confirmed Deal Status Are Not Included In The Uploaded Source.",
                "latitude": listing.get("latitude"),
                "longitude": listing.get("longitude"),
                "zip_code": listing.get("zip_code") or listing.get("postcode"),
            }
        )
        if len(properties) >= 12:
            break
    return sorted(properties, key=lambda row: row["fit_score"], reverse=True)


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

    def avg(key: str) -> int:
        return round(sum(row.get(key, 0) for row in top) / len(top))

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
            "gap_label": f"{avg('walkability')} Walkability",
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
    return render_template("index.html")


@app.route("/api/dashboard")
def dashboard():
    concept_name = (request.args.get("concept_name", "Restaurant Concept") or "Restaurant Concept").strip()[:80]
    profile = request.args.get("profile", "restaurant")
    if profile not in PROFILE_WEIGHTS:
        profile = "restaurant"
    rent_cap = int(request.args.get("rent_cap", "18000"))
    deal_type = request.args.get("deal_type", "lease")
    borough = request.args.get("borough", "")
    if deal_type not in {"lease", "purchase", "either"}:
        deal_type = "lease"
    if borough not in {"", "Brooklyn", "Queens", "Manhattan", "Bronx"}:
        borough = ""
    locations = tuned_locations(profile, rent_cap, borough)
    if not locations:
        locations = tuned_locations(profile, rent_cap)
    best = locations[0]
    avg_confidence = round(sum(row["confidence_score"] for row in locations) / len(locations))
    finance = {
        "rent_cap": rent_cap,
        "break_even_revenue": round(rent_cap * 3.15),
        "orders_per_day": round((rent_cap * 3.15) / 30 / 28),
        "runway_months": max(7, round(18 - rent_cap / 3200)),
        "capture_rate": "2.1-3.8%",
    }
    return jsonify(
        {
            "locations": locations,
            "selected": best["id"],
            "feeds": data_feeds(),
            "whitespace": market_gap_rows(locations),
            "vendor_windows": VENDOR_WINDOWS,
            "properties": matching_properties(locations, deal_type, rent_cap),
            "data_layers": DATA_LAYERS,
            "reports": REPORTS,
            "scoring": {
                "weights": PROFILE_WEIGHTS.get(profile, PROFILE_WEIGHTS["restaurant"]),
                "signals": SCORING_SIGNALS,
                "avg_confidence": avg_confidence,
                "method": "Weighted Location-Fit Score Across Demand, Customer Fit, Access, Market Gap, Competition Balance, And Commercial Suitability",
            },
            "finance": finance,
            "meta": {
                "project": "Groundwork NYC",
                "concept_name": concept_name,
                "scope": "NYC Restaurant And Bar Site Selection",
                "architecture": "Flask API Using Integrated NYC Tract, Storefront, Mobility, Competition, Demographic, And Land-Use Features",
                "api_contract": "Locations, Properties, Feeds, Data Quality, Reports, Finance",
                "deal_type": deal_type,
                "borough": borough or "All NYC",
                "primary_dataset": str(MASTER_TRACT_PATH),
                "unsupported_values": unsupported_values(),
            },
        }
    )


if __name__ == "__main__":
    app.run(debug=True, port=5001)
