"""Deterministic, source-aware evidence for a small set of shortlisted areas."""

from collections import Counter, defaultdict
from math import isfinite
from urllib.parse import urlsplit

from financials import operating_scenario


def _numeric(value):
    return value if type(value) in (int, float) and isfinite(value) else None


def _source(name, vintage=None, url=None):
    if not name:
        return None
    try:
        parsed = urlsplit(url) if isinstance(url, str) else None
        safe = parsed and parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password
    except ValueError:
        safe = False
    return {"name": name, "vintage": str(vintage) if vintage is not None else None, "url": url if safe else None}


def _evidence_item(key, label, value, unit, basis, grain, *, source=None, vintage=None, status="observed", coverage=None):
    value = _numeric(value)
    item = {"id": key, "label": label, "value": value, "unit": unit,
            "status": status if value is not None else "unavailable", "basis": basis,
            "source": source, "vintage": str(vintage) if vintage is not None else (source or {}).get("vintage"),
            "grain": grain}
    if coverage is not None:
        item["coverage"] = coverage
    return item


def _site_evidence(row, dashboard, catalog, profile):
    evidence = []
    market = row.get("market_profile") or {}
    profile_values = profile.get("market_profile") or {}
    cuisine = row.get("concept_evidence") or {}
    access = row.get("customer_access") or {}
    benchmarks = dashboard.get("rent_benchmarks") or {}
    rent = (benchmarks.get("by_geoid") or {}).get(row["id"], {})
    components = {item["key"]: item for item in row.get("score_components") or []}

    def fact(key, label, value, unit, basis, grain, *, source=None, vintage=None, status="observed", coverage=None):
        if isinstance(source, str):
            source = catalog.get(source) or _source(source)
        evidence.append(_evidence_item(key, label, value, unit, basis, grain,
                                       source=source, vintage=vintage, status=status, coverage=coverage))

    for key, label, basis in (
        ("demand", "Activity and demand score", "Uses tract activity proxies under the selected concept assumptions."),
        ("customer_fit", "Customer fit score", "Screening fit from the selected audience and an income-based affordability assumption."),
        ("competition_balance", "Competition balance score", "Recorded competitor pressure relative to modeled activity."),
    ):
        component = components.get(key, {})
        coverage = _numeric(component.get("coverage"))
        fact(key, label, component.get("score") if coverage else None, "/100", basis, "Census tract",
             source="Groundwork screening model", status="modeled", coverage=coverage)

    profile_sources = profile.get("sources") or {}
    for key, label, unit, source, profile_source, basis in (
        ("population", "Residents", "people", "ACS demographics", "residents", "Area population estimate."),
        ("jobs", "Workplace jobs", "jobs", "LODES", "jobs", "Workplace jobs located within the tract."),
        ("median_household_income", "Median household income", "USD/year", "ACS income", "residents", "Area estimate of household income."),
        ("income_margin_of_error", "Household income margin of error", "USD/year", "ACS income", "residents", "Published margin of error for the area estimate."),
    ):
        profile_value = _numeric(profile_values.get(key))
        value = profile_value if profile_value is not None else _numeric(market.get(key))
        if key in {"median_household_income", "income_margin_of_error"} and value is not None and value < 0:
            value = None
        fact(key, label, value, unit, basis, "Census tract",
             source=source, vintage=profile_sources.get(profile_source) if profile_value is not None else None)

    fact("competition", "Recorded same-cuisine establishments", cuisine.get("same_cuisine_count"), "establishments",
         "Active inspection inventory with available cuisine labels. The count may omit establishments.", "Census tract",
         source="Restaurant inspections", coverage=_numeric(cuisine.get("cuisine_label_coverage")))
    fact("walkability", "EPA walkability index", cuisine.get("epa_walkability_index"), "/20",
         "EPA built-environment index aggregated to the tract.", "Census tract", source="EPA Smart Location Database", status="modeled")
    fact("customer_access", "Modeled customer access", access.get("index") if access.get("status") == "available" else None,
         "/100", "Network walking access to residential and workplace opportunities under the selected concept.",
         "Census tract centroid", source=_source(access.get("source")), vintage=access.get("as_of"), status="modeled")
    fact("subway_distance", "Nearest subway distance", market.get("subway_distance_miles"), "mi",
         "Distance from the area’s representative point to the nearest station.", "Census tract to station complex", source="MTA ridership")
    fact("subway_ridership", "Nearest subway weekly ridership", market.get("nearest_subway_weekly_ridership"), "entries/week",
         "Recorded ridership at the nearest station complex.", "Station complex", source="MTA ridership", vintage=market.get("subway_vintage"))
    daypart = ((dashboard.get("meta") or {}).get("concept") or {}).get("daypart")
    transit_window = {"morning": ("morning", "7–10 a.m."), "lunch": ("midday", "11 a.m.–2 p.m."),
                      "evening": ("evening", "5–9 p.m.")}.get(daypart)
    if transit_window:
        window, hours = transit_window
        fact("subway_daypart", "Nearest subway ridership during trading period", (market.get("subway_dayparts") or {}).get(window),
             "entries/day", f"Average daily station ridership during {hours} in the source period.", "Station complex",
             source="MTA ridership", vintage=market.get("subway_vintage"))
    fact("pedestrian_activity", "Nearest monitored pedestrian count", market.get("pedestrian_counter_latest"), "people counted",
         "Published count at a monitored site during its observation period.", "Nearby monitoring site", source="DOT pedestrian counts")
    latest_bike = _numeric(market.get("bike_departures_latest_month"))
    fact("bike_activity", "Citi Bike departures", latest_bike if latest_bike is not None else market.get("bike_departures_august_2026"),
         "trips/month", "Recorded departures from stations assigned to the tract.", "Census tract", source="Citi Bike",
         vintage=market.get("bike_activity_month") if latest_bike is not None else None)
    fact("taxi_activity", "For-hire vehicle pickups", market.get("taxi_pickups_latest_month"), "trips/month",
         "Recorded pickups for the linked taxi zone, which can span several tracts.", "Taxi zone", source="TLC HVFHV",
         vintage=market.get("taxi_activity_month"))
    rent_source = _source("NYC Storefront Rent Statistics", benchmarks.get("reporting_year"), benchmarks.get("source_url"))
    fact("rent", "Reported occupied-storefront median rent", rent.get("reported_median_monthly_rent_psf"),
         "USD/sq ft/month", "Area benchmark for occupied registered storefronts. Ask for current terms at a specific address.",
         "Census tract", source=rent_source)

    survival = row.get("survival") or {}
    survival_model = dashboard.get("survival_model") or {}
    estimate = _numeric(survival.get("probability"))
    coverage = _numeric(survival.get("feature_coverage"))
    archived = survival.get("source_type") == "atharv_tract_export"
    fact("survival", "Archive reobservation estimate" if archived else "Experimental three-year survival estimate",
         round(estimate * 100, 1) if survival.get("status") == "available" and estimate is not None and 0 <= estimate <= 1 else None,
         "%", "Historical archive appearance and disappearance under a reference opening year." if archived
         else "Experimental area-level estimate using historical establishment features.", "Census tract",
         source=_source(survival.get("model_version") or survival_model.get("model_version"), survival.get("trained_as_of")),
         vintage=survival.get("prediction_date"), status="modeled",
         coverage=round(coverage * 100, 1) if coverage is not None else None)
    evidence[-1]["detail_status"] = survival.get("status") or survival_model.get("status") or "unavailable"
    return evidence


def _profile_detail(profile, catalog):
    if not profile:
        return []
    values = profile.get("market_profile") or {}
    sources = profile.get("sources") or {}
    groups = (
        ("resident_age", "Resident ages", "people", "ACS demographics", "residents", (
            ("population_under_18_2024", "Residents under 18"), ("population_65_plus_2024", "Residents age 65 and older"),
        )),
        ("job_age", "Worker ages", "jobs", "LODES", "jobs", (
            ("jobs_age_29_or_younger", "Age 29 or younger"), ("jobs_age_30_to_54", "Age 30 to 54"),
            ("jobs_age_55_or_older", "Age 55 and older"),
        )),
        ("job_earnings", "Workplace earnings", "jobs", "LODES", "jobs", (
            ("jobs_earn_1250_or_less_monthly", "Jobs earning up to $1,250 per month"),
            ("jobs_earn_1251_to_3333_monthly", "Jobs earning $1,251 to $3,333 per month"),
            ("jobs_earn_more_than_3333_monthly", "Jobs earning over $3,333 per month"),
        )),
        ("job_industry", "Selected workplace industries", "jobs", "LODES", "jobs", (
            ("jobs_retail_trade", "Retail trade"), ("jobs_arts_entertainment_recreation", "Arts, entertainment and recreation"),
            ("jobs_accommodation_food_services", "Accommodation and food services"),
            ("jobs_professional_scientific_technical", "Professional, scientific and technical services"),
        )),
    )
    return [{"id": group, "label": title, "evidence": [
        _evidence_item(key, label, (values.get(group) or {}).get(key), unit,
                       "ACS population estimate." if profile_source == "residents" else "Recorded workplace jobs grouped by this characteristic.",
                       "Census tract", source=catalog.get(source) or _source(source), vintage=sources.get(profile_source))
        for key, label in fields
    ]} for group, title, unit, source, profile_source, fields in groups]


_AVAILABILITY = {"code": "confirm_availability", "label": "Confirm availability and asking terms",
                 "detail": "Ask the listing source for the full address, current status, total occupancy costs, and deal terms."}
_FACILITIES = {"code": "verify_facilities", "label": "Verify restaurant use and building facilities",
               "detail": "Check permitted use, ventilation, utilities, build-out requirements, and operating restrictions for the address."}
_FIND_PREMISES = {"code": "find_premises", "label": "Find a real address and obtain a current quote",
                   "detail": "Use the area shortlist for research. Confirm actual premises, availability, and asking terms."}


def _walking_evidence(lead, catalog):
    walking = lead.get("site_evidence") or {}
    available = walking.get("status") == "available"
    source = _source(walking.get("source"))
    return {"status": "available" if available else "unavailable", "source": source,
            "reason": walking.get("reason"), "minutes": _numeric(walking.get("minutes")) if available else None,
            "evidence": [
                _evidence_item(key, label, walking.get(key), unit, "Counts reachable through the modeled pedestrian network.",
                               "Walking catchment from reported address", source=catalog.get(feed) or source, status="modeled")
                for key, label, unit, feed in (
                    ("recorded_restaurants", "Reachable recorded restaurants", "establishments", "Restaurant inspections"),
                    ("same_cuisine_restaurants", "Reachable recorded same-cuisine restaurants", "establishments", "Restaurant inspections"),
                    ("nearby_subway_stations", "Reachable subway stations", "stations", "MTA ridership"),
                )
            ] if available else []}


def _property_gates(leads, search, finance, catalog):
    counts = Counter(item.get("lead_type") for item in leads)
    listings = [item for item in leads if item.get("lead_type") == "listing"]
    verified = [item for item in listings if (item.get("assessment_policy") or {}).get("verified_live_listing") is True]
    lead = next(iter(verified or listings), None)
    if lead:
        status = "verified_listing_reported" if verified else "sourced_unverified"
        policy = lead.get("assessment_policy") or {}
        size = _numeric(lead.get("sqft"))
        lead = {"id": lead.get("id"), "title": lead.get("title"), "address": lead.get("address"),
                "transaction": lead.get("transaction"), "asking_rent": _numeric(lead.get("asking_rent")),
                "asking_price": _numeric(lead.get("asking_price")), "sqft": size if size and size > 0 else None,
                "reported_availability": lead.get("availability"), "availability_verified": bool(verified),
                "budget_evidence": policy.get("budget_evidence"), "site_evidence": _walking_evidence(lead, catalog),
                "source": _source("Listing source", lead.get("checked_at"), lead.get("source_url"))}
    elif leads:
        status = "historical_or_synthetic_only"
    elif search.get("status") in {"matches_available", "no_matching_inventory"}:
        status = "no_sourced_matches"
    else:
        status = "inventory_unavailable"
    return {"status": status, "verified_live_count": len(verified), "sourced_count": counts["listing"],
            "registry_count": counts["registry_record"], "synthetic_count": counts["synthetic"], "lead": lead,
            "rent_limit": _numeric(finance.get("rent_target")), "purchase_limit": _numeric(finance.get("purchase_budget")),
            "scope": "Records returned by the dashboard search. Historical and synthetic records are research context.",
            "checks": [dict(_AVAILABILITY if lead else _FIND_PREMISES), dict(_FACILITIES)]}


def _break_even(finance, lead):
    status = finance.get("status") or "incomplete"
    if status != "ready":
        return {"status": status, "required_covers_per_day": None, "required_monthly_sales": None,
                "missing_inputs": finance.get("missing_inputs") or []}
    rent = finance.get("rent_target")
    basis = "entered_rent_target"
    assumption = finance
    if lead and lead.get("transaction") == "lease" and (lead.get("asking_rent") or 0) > 0:
        rent = lead["asking_rent"]
        basis = "source_reported_asking_rent"
        assumption = operating_scenario(finance, rent, finance["guest_spend"], "lease")
    return {"status": "ready", "required_covers_per_day": assumption["required_covers_per_day"],
            "required_monthly_sales": assumption["required_monthly_sales"], "rent_monthly": rent, "basis": basis,
            "detail": "Uses the stated rent, guest spend, costs, and operating days. Treat debt service, taxes, and additional costs separately."}


def _next_check(policy, gates, finance):
    if policy.get("recommendation_eligible") is False:
        return {"code": "obtain_core_location_data", "label": "Fill the core evidence gaps",
                "detail": "Verify local activity and access before treating this tract as a viable shortlist entry."}
    if not gates["sourced_count"]:
        return dict(_FIND_PREMISES)
    if not gates["verified_live_count"]:
        return dict(_AVAILABILITY)
    if finance["status"] == "incomplete":
        return {"code": "enter_cost_assumptions", "label": "Complete the operating cost assumptions",
                "detail": "Enter fixed costs, variable costs, and operating days to calculate the break-even threshold."}
    return dict(_FACILITIES)


def build_dossier(dashboard, candidate_ids, *, profiles=None):
    """Build cards in the requested order from server-resolved dashboard records."""
    catalog = {feed["name"]: _source(feed["name"], feed.get("vintage"), feed.get("url"))
               for feed in dashboard.get("feeds") or [] if feed.get("name")}
    rows = {row["id"]: row for key in ("property_locations", "saved_locations", "locations")
            for row in dashboard.get(key) or []}
    by_area = defaultdict(list)
    for item in dashboard.get("properties") or []:
        by_area[item.get("location_id")].append(item)
    search = dashboard.get("property_search") or {}
    finance = dashboard.get("finance") or {}
    profiles = profiles or {}

    sites = []
    for identity in dict.fromkeys(candidate_ids):
        row = rows.get(identity)
        if row is None:
            continue
        profile = profiles.get(identity) or {}
        gates = _property_gates(by_area[identity], search, finance, catalog)
        break_even = _break_even(finance, gates["lead"])
        sites.append({"id": identity, "name": row.get("name"), "borough": row.get("borough"),
                      "evidence": _site_evidence(row, dashboard, catalog, profile), "profile_detail": _profile_detail(profile, catalog),
                      "property_gates": gates, "break_even": break_even,
                      "next_check": _next_check(row.get("assessment_policy") or {}, gates, break_even)})
    coverage = {key: (dashboard.get(source) or {}).get("status") or "unavailable" for key, source in (
        ("customer_access", "customer_access_model"), ("rent_benchmarks", "rent_benchmarks"), ("survival", "survival_model"),
    )}
    return {"sites": sites, "release": (dashboard.get("meta") or {}).get("data_release"), "coverage": coverage}
