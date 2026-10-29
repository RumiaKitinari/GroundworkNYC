"""Team master-input preparation, sourced from Otis dce1e03 master_tract_spec.py."""
"""Derive current tract context requested by the master-feature specification.

These cross-vintage fields describe current locations. They are not historical
predictors for a restaurant survival model.
"""

import json
import math
from pathlib import Path


FIELD_DEFINITIONS = {
    "pct_residents_under_18": ("2024 ACS residents under 18 divided by all 2024 ACS residents, multiplied by 100.", "percent"),
    "pct_residents_65_plus": ("2024 ACS residents 65 or older divided by all 2024 ACS residents, multiplied by 100.", "percent"),
    "jobs_per_resident": ("2023 LODES workplace jobs divided by 2024 ACS residents; cross-vintage context, not a commuter flow.", "jobs/resident"),
    "pct_jobs_retail": ("2023 LODES retail workplace jobs divided by all 2023 LODES workplace jobs, multiplied by 100.", "percent"),
    "pct_jobs_accommodation_food": ("2023 LODES accommodation and food workplace jobs divided by all workplace jobs, multiplied by 100.", "percent"),
    "pct_jobs_office_industries": ("2023 LODES information, finance, real estate, professional, management, and administrative jobs divided by all workplace jobs, multiplied by 100.", "percent"),
    "pct_jobs_high_earning": ("2023 LODES workplace jobs earning over $3,333 monthly divided by all workplace jobs, multiplied by 100.", "percent"),
    "citibike_departures_per_sq_mile_latest_month": ("Latest complete Citi Bike month departures from stations assigned to the tract divided by tract land area.", "departures/sq mi"),
    "citibike_weekend_departure_share_latest_month": ("Latest complete Citi Bike month weekend departures divided by all departures from stations assigned to the tract.", "share"),
    "citibike_evening_departure_share_latest_month": ("Latest complete Citi Bike month evening departures divided by all departures from stations assigned to the tract.", "share"),
    "retail_area_sqft_per_sq_mile": ("PLUTO retail floor area in tract divided by tract land area; floor area is not parcel area.", "sq ft/sq mi"),
    "office_area_sqft_per_sq_mile": ("PLUTO office floor area in tract divided by tract land area; floor area is not parcel area.", "sq ft/sq mi"),
    "restaurant_competitors_per_1000_residents": ("OSM tagged restaurant and fast-food POIs per 1,000 2024 ACS residents; untagged businesses are excluded.", "POIs/1,000 residents"),
    "bar_competitors_per_1000_residents": ("OSM tagged bar, pub and nightclub POIs per 1,000 2024 ACS residents; untagged businesses are excluded.", "POIs/1,000 residents"),
    "registered_storefronts_per_1000_residents": ("2024 DOF registered storefronts per 1,000 2024 ACS residents, only where DOF publishes a tract count.", "storefronts/1,000 residents"),
    "reported_median_annual_rent_psf": ("2024 DOF reported median monthly rent per square foot multiplied by 12; published values only.", "USD/sq ft/year"),
    "neighbor_geoids": ("2020 census tracts sharing a boundary segment with this tract; point contact alone excluded.", "semicolon-separated GEOIDs"),
    "neighbor_population_density_per_sq_mile": ("Total 2024 ACS residents in boundary-adjacent tracts divided by their total land area.", "residents/sq mi"),
    "neighbor_jobs_per_resident": ("Total 2023 LODES jobs in boundary-adjacent tracts divided by their 2024 ACS residents.", "jobs/resident"),
    "neighbor_income_2024_estimate": ("Population-weighted mean of published 2024 ACS median household incomes in boundary-adjacent tracts; not an observed tract median.", "USD/year"),
    "income_missing_2024": ("1 when the tract's published 2024 ACS median household income is missing, else 0; the source value is never overwritten.", "boolean"),
}


def number(row, field):
    try:
        value = float(row.get(field, ""))
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) else None


def ratio(numerator, denominator, multiplier=1):
    if numerator is None or denominator is None or denominator <= 0:
        return ""
    return round(multiplier * numerator / denominator, 6)


def adjacency(geometry_path):
    from shapely.geometry import shape
    from shapely.strtree import STRtree

    features = json.loads(Path(geometry_path).read_text())["features"]
    ids = [feature["properties"]["geoid"] for feature in features]
    shapes = [shape(feature["geometry"]) for feature in features]
    tree = STRtree(shapes)
    result = {}
    for index, polygon in enumerate(shapes):
        boundary = polygon.boundary
        result[ids[index]] = sorted(
            ids[int(other)] for other in tree.query(polygon)
            if int(other) != index and boundary.intersection(shapes[int(other)].boundary).length > 1e-9
        )
    return result


def enrich(master, geometry_path):
    neighbors = adjacency(geometry_path)
    by_geoid = {row["geoid"]: row for row in master}
    for row in master:
        population = number(row, "population_2024")
        jobs = number(row, "total_jobs")
        area = number(row, "land_area_sq_miles")
        departures = number(row, "citibike_departures_latest_month")
        rent = number(row, "reported_median_monthly_rent_psf")
        values = {
            "pct_residents_under_18": ratio(number(row, "population_under_18_2024"), population, 100),
            "pct_residents_65_plus": ratio(number(row, "population_65_plus_2024"), population, 100),
            "jobs_per_resident": ratio(jobs, population),
            "pct_jobs_retail": ratio(number(row, "jobs_retail_trade"), jobs, 100),
            "pct_jobs_accommodation_food": ratio(number(row, "jobs_accommodation_food_services"), jobs, 100),
            "pct_jobs_high_earning": ratio(number(row, "jobs_earn_more_than_3333_monthly"), jobs, 100),
            "citibike_departures_per_sq_mile_latest_month": ratio(departures, area),
            "citibike_weekend_departure_share_latest_month": ratio(number(row, "citibike_weekend_departures_latest_month"), departures),
            "citibike_evening_departure_share_latest_month": ratio(number(row, "citibike_evening_departures_latest_month"), departures),
            "retail_area_sqft_per_sq_mile": ratio(number(row, "retail_area_sqft"), area),
            "office_area_sqft_per_sq_mile": ratio(number(row, "office_area_sqft"), area),
            "registered_storefronts_per_1000_residents": ratio(number(row, "registered_storefronts"), population, 1000),
            "reported_median_annual_rent_psf": round(rent * 12, 2) if rent is not None else "",
            "income_missing_2024": int(number(row, "median_household_income_2024") is None),
        }
        office_fields = ("jobs_information", "jobs_finance_insurance", "jobs_real_estate_rental_leasing",
                         "jobs_professional_scientific_technical", "jobs_management",
                         "jobs_admin_support_waste_management")
        office_values = [number(row, field) for field in office_fields]
        values["pct_jobs_office_industries"] = ratio(sum(office_values), jobs, 100) if all(value is not None for value in office_values) else ""
        for source, target in (("restaurant_competitor_count", "restaurant_competitors_per_1000_residents"),
                               ("bar_nightlife_competitor_count", "bar_competitors_per_1000_residents")):
            count = number(row, source)
            values[target] = ratio(count if count is not None else 0, population, 1000)

        adjacent = [by_geoid[geoid] for geoid in neighbors.get(row["geoid"], [])]
        values["neighbor_geoids"] = ";".join(neighbor["geoid"] for neighbor in adjacent)
        resident_pairs = [(number(neighbor, "population_2024"), number(neighbor, "land_area_sq_miles")) for neighbor in adjacent]
        values["neighbor_population_density_per_sq_mile"] = ratio(
            sum(pop for pop, land in resident_pairs if pop is not None and land is not None),
            sum(land for pop, land in resident_pairs if pop is not None and land is not None),
        ) if adjacent else ""
        job_pairs = [(number(neighbor, "total_jobs"), number(neighbor, "population_2024")) for neighbor in adjacent]
        values["neighbor_jobs_per_resident"] = ratio(
            sum(work for work, pop in job_pairs if work is not None and pop is not None),
            sum(pop for work, pop in job_pairs if work is not None and pop is not None),
        ) if adjacent else ""
        incomes = [(number(neighbor, "median_household_income_2024"), number(neighbor, "population_2024")) for neighbor in adjacent]
        incomes = [(income, pop) for income, pop in incomes if income is not None and pop is not None and pop > 0]
        values["neighbor_income_2024_estimate"] = ratio(
            sum(income * pop for income, pop in incomes), sum(pop for _, pop in incomes)
        ) if incomes else ""
        row.update(values)
    return {"tracts": len(master), "fields": len(FIELD_DEFINITIONS),
            "missing_income": sum(row["income_missing_2024"] for row in master),
            "income_with_neighbor_estimate": sum(row["income_missing_2024"] and row["neighbor_income_2024_estimate"] != "" for row in master),
            "tracts_with_adjacency": sum(bool(row["neighbor_geoids"]) for row in master)}
