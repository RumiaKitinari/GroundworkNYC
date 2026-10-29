"""Explicit current-context feature contract; never a historical AFT allowlist."""

import numpy as np
import pandas as pd


# name, source column, domain, transform, group
SPECS = [
    ("population_density", "population_density_per_sq_mile", "nonnegative", "log1p", "residents"),
    ("resident_under18_share", "pct_residents_under_18", "percent", "share", "residents"),
    ("resident_65plus_share", "pct_residents_65_plus", "percent", "share", "residents"),
    ("median_household_income", "median_household_income_2024", "positive", "log1p", "residents"),
    ("income_uncertainty", "median_household_income_margin_of_error_2024", "nonnegative", "log1p", "coverage"),
    ("poverty_share", "poverty_share_2024", "share", "identity", "residents"),
    ("job_density", "job_density_per_sq_mile", "nonnegative", "log1p", "employment"),
    ("office_job_share", "pct_jobs_office_industries", "percent", "share", "employment"),
    ("food_job_share", "pct_jobs_accommodation_food", "percent", "share", "employment"),
    ("retail_job_share", "pct_jobs_retail", "percent", "share", "employment"),
    ("high_earning_job_share", "pct_jobs_high_earning", "percent", "share", "employment"),
    ("walkability", "national_walkability_index", "walkability", "identity", "built_environment"),
    ("intersection_density", "epa_intersection_density", "nonnegative", "log1p", "built_environment"),
    ("subway_reach_activity", "subway_weekly_ridership_within_400m", "nonnegative", "log1p", "transit"),
    ("subway_complexes_within400m", "subway_complexes_within_400m", "nonnegative", "log1p", "transit"),
    ("subway_entry_distance_m", "nearest_subway_entry_distance_m", "nonnegative", "log1p", "transit"),
    ("subway_weekend_share", "subway_within_400m_weekend_share", "share", "identity", "transit"),
    ("subway_am_share", "subway_within_400m_weekday_am_share", "share", "identity", "transit"),
    ("subway_pm_share", "subway_within_400m_weekday_pm_share", "share", "identity", "transit"),
    ("subway_evening_share", "subway_within_400m_weekday_evening_share", "share", "identity", "transit"),
    ("citibike_arrival_density", "citibike_arrivals_per_sq_mile_latest_month", "nonnegative", "log1p", "mobility"),
    ("citibike_evening_share", "citibike_evening_departure_share_latest_month", "share", "identity", "mobility"),
    ("citibike_weekend_share", "citibike_weekend_departure_share_latest_month", "share", "identity", "mobility"),
    ("rideshare_allocated_density", "rideshare_dropoffs_per_sq_mile", "nonnegative", "log1p", "mobility"),
    ("rideshare_evening_share", "rideshare_evening_dropoff_share", "share", "identity", "mobility"),
    ("rideshare_late_night_share", "rideshare_late_night_dropoff_share", "share", "identity", "mobility"),
    ("pedestrian_count", "nearest_pedestrian_count_site_latest_pedestrian_count_total", "nonnegative", "log1p", "activity"),
    ("pedestrian_monitor_distance_miles", "nearest_pedestrian_count_site_distance_miles", "nonnegative", "log1p", "coverage"),
    ("retail_floor_density", "retail_area_sqft_per_sq_mile", "nonnegative", "log1p", "commercial"),
    ("office_floor_density", "office_area_sqft_per_sq_mile", "nonnegative", "log1p", "commercial"),
    ("commercial_lot_share", "commercial_mixed_lot_share_all", "share", "identity", "commercial"),
    ("vacant_land_share", "vacant_land_share_all_lots", "share", "identity", "commercial"),
    ("registered_properties_with_vacancy_share", "registered_properties_with_vacancy_share", "share", "identity", "commercial"),
    ("past_year_event_district_context", "past_year_permitted_events_district_context", "nonnegative", "log1p", "events"),
    ("past_year_event_hours_district_context", "past_year_permitted_event_hours_district_context", "nonnegative", "log1p", "events"),
    ("food_poi_density", "food_nightlife_poi_per_sq_mile", "nonnegative", "log1p", "current_supply"),
    ("cafe_density", "cafe_count_per_sq_mile", "nonnegative", "log1p", "current_supply"),
    ("bar_density", "bar_count_per_sq_mile", "nonnegative", "log1p", "current_supply"),
]


def current_context_features(master):
    if master.geoid.duplicated().any():
        raise ValueError("Duplicate master GEOIDs")
    result = pd.DataFrame({"geoid": master.geoid.astype(str)}, index=master.index)
    dictionary = []
    for name, source, domain, transform, group in SPECS:
        raw = pd.to_numeric(master[source], errors="coerce") if source in master else pd.Series(np.nan, index=master.index)
        valid = np.isfinite(raw)
        if domain in {"share", "percent", "walkability"}:
            lower, upper = {"share": (0, 1), "percent": (0, 100), "walkability": (1, 20)}[domain]
            valid &= raw.between(lower, upper)
        else:
            valid &= raw > 0 if domain == "positive" else raw >= 0
        values = raw.where(valid)
        result[name] = np.log1p(values) if transform == "log1p" else values / 100 if transform == "share" else values
        dictionary.append({"feature": name, "source_column": source, "group": group,
                           "valid_domain": domain, "transform": transform,
                           "missing_policy": "NaN; never blanket-zero fill",
                           "valid_rows": int(valid.sum()), "missing_rows": int((~valid).sum()),
                           "invalid_observed_rows": int((raw.notna() & ~valid).sum()),
                           "unique_observed_values": int(values.nunique()),
                           "role": "prospective_context_only; historical use requires separate dated provenance"})
    return result, pd.DataFrame(dictionary)


def feature_audit(master):
    matrix, dictionary = current_context_features(master)
    numeric = matrix.drop(columns="geoid")
    correlation = numeric.corr(method="spearman", min_periods=30)
    pairs = []
    for j, column in enumerate(correlation):
        for other in correlation.columns[j + 1:]:
            value = correlation.loc[column, other]
            if pd.notna(value) and abs(value) >= .95:
                pairs.append({"feature_a": column, "feature_b": other, "rank_correlation": float(value)})
    return matrix, dictionary, {"tracts": len(master), "master_columns": len(master.columns),
        "context_features": len(SPECS), "high_correlation_review_pairs": pairs,
        "source_columns_missing": [r[1] for r in SPECS if r[1] not in master],
        "constant_features": dictionary.loc[dictionary.unique_observed_values.le(1), "feature"].tolist(),
        "historical_training_features_unchanged": True,
        "correlation_policy": "Review redundancy using development data before selecting predictors; no automatic test-set selection",
        "excluded_from_survival": ["all current-only observations", "synthetic property prices/facilities",
                                  "cuisine labels", "ratings", "current DOHMH outcomes", "unverified closure status"],
        "corrected_semantics": ["Use existing area-allocated TLC density instead of dividing repeated zone totals again",
                                "Property vacancy is not inferred as 1 minus leased/registered spaces",
                                "Use historical annual district event context, not upcoming permits",
                                "Percent and share variables are explicitly distinguished",
                                "Missing Citi Bike coverage is not automatically zero activity"]}
