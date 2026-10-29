"""Shared fallback contracts: evidence strength is not predictive confidence."""
from math import isfinite

VERSION = "evidence-policy-1.0"
THRESHOLDS = {"city_cuisine_records":30,"neighborhood_cuisine_records":5,
              "local_known_inventory":10,"label_coverage":.7,"supply_prior_strength":20,
              "minimum_screening_coverage":.35}
THRESHOLDS["minimum_model_feature_coverage"] = .75

# These are broader source categories, not inferred identities or substitutes
# for the selected cuisine. They never contribute a cuisine-specific score.
RELATED_CONTEXT = {
    "colombian":("Latin American",),"venezuelan":("Latin American",),
    "cuban":("Latin American",),"dominican":("Latin American","Caribbean"),
    "puerto_rican":("Latin American","Caribbean"),"jamaican":("Caribbean",),
    "haitian":("Caribbean",),"west_african":("African",),
    "taiwanese":("Chinese",),"indonesian_malaysian":("Southeast Asian",),
    "breakfast_brunch":("Pancakes/Waffles","Coffee/Tea"),
    "noodles":("Chinese","Japanese","Thai","Vietnamese"),
}

CASES = {
    "sparse_cuisine":"Pool observed neighborhood supply toward the city share; cap cuisine influence by support. Preserve general concept suitability.",
    "unclassified_cuisine":"Use format, price, trading period, access and area suitability. Related source categories are context only.",
    "no_recorded_supply":"Do not equate zero observed competitors with proven demand or a profitable gap.",
    "unknown_inventory":"Keep unknown labels in the coverage denominator; never count them as confirmed absent competition.",
    "dietary_combination":"Retain dietary identity separately. Cuisine totals do not measure dietary-specific demand or verify certification.",
    "affluent_low_supply":"Show affordability and supply separately; wealth plus absence does not establish demand.",
    "missing_income":"Withhold affordability-dependent conclusions; retain available worker, access and resident context without invented income.",
    "missing_access":"Withhold network access/Huff output. A separately labeled general accessibility index may remain available.",
    "unknown_competitor_routes":"Withhold affected Huff scenarios instead of treating unknown routes as zero competition.",
    "unverified_survival":"Use a labeled screening index, never rename archive proxy output as verified survival probability.",
    "partial_historical_features":"Expose feature coverage and require the model's validated feature contract before using its estimates.",
    "unsupported_concept":"Preserve the entered concept and expose unresolved classification rather than silently substituting another restaurant.",
    "insufficient_general_data":"Defer recommendation; retain diagnostics. A neutral shrinkage anchor is not an evidence-backed score.",
    "missing_property_price":"Keep price unavailable; do not treat zero as free or claim budget eligibility.",
    "synthetic_property":"Use for scenario demonstration only, never claim verified availability, broker identity or financial return.",
    "hard_constraints":"Never silently relax budget, transaction, geography or required facilities. Return no match and explicit review options.",
    "stale_or_mixed_vintages":"Retain source observation and availability dates; do not backdate current measurements or label old observations real-time.",
    "conflicting_identity":"Withhold transfer of labels and outcomes until business/location identity is reconciled.",
    "out_of_scope":"Reject unsupported coordinates/inputs rather than extrapolate outside the supported domain.",
    "ranking_instability":"Expose scenario sensitivity; do not select attractive weights without observed validation outcomes.",
}


def cuisine_support(cuisine, labels, local, neighborhood, city):
    total = sum(local.values())
    known = total-local.get("unknown",0)
    city_known = sum(city.values())-city.get("unknown",0)
    nearby_known = sum(neighborhood.values())-neighborhood.get("unknown",0)
    same = sum(local.get(label,0) for label in labels)
    city_same = sum(city.get(label,0) for label in labels)
    nearby_same = sum(neighborhood.get(label,0) for label in labels)
    coverage = known/total if total else 0.
    share = city_same/city_known if city_known else None
    prior = THRESHOLDS["supply_prior_strength"]
    pooled = (nearby_same+prior*share)/(nearby_known+prior) if share is not None and city_same else None
    strength = min(1.,city_same/THRESHOLDS["city_cuisine_records"])*coverage*min(1.,known/THRESHOLDS["local_known_inventory"]) if labels else 0.
    specific = bool(labels and city_same>=THRESHOLDS["city_cuisine_records"]
                    and nearby_same>=THRESHOLDS["neighborhood_cuisine_records"]
                    and known>=THRESHOLDS["local_known_inventory"] and coverage>=THRESHOLDS["label_coverage"])
    related_labels = RELATED_CONTEXT.get(cuisine,())
    related = sum(city.get(label,0) for label in related_labels)
    mode = ("cuisine_supply_supported" if specific else "pooled_cuisine_supply" if labels and city_same
            else "related_supply_context_only" if related else "general_concept_suitability")
    return {"policy_version":VERSION,"mode":mode,"city_cuisine_records":city_same,
            "neighborhood_cuisine_records":nearby_same,"local_cuisine_records":same if labels else None,
            "local_inventory_records":total,"label_coverage":coverage,"score_evidence_cap":strength,
            "city_supply_share":share if labels else None,"pooled_neighborhood_supply_share":pooled,
            "expected_local_supply":known*pooled if pooled is not None else None,
            "related_context_labels":list(related_labels),"related_city_records":related,
            "related_context_changes_score":False,"demand_verified":False,
            "supply_method":"Fixed-strength neighborhood/city supply pooling; not a fitted demand model"}


def location_policy(coverage, support, dietary="none", income_available=True):
    adequate = coverage>=THRESHOLDS["minimum_screening_coverage"]
    actions = []
    if not adequate:
        actions.append("obtain_core_location_data")
    if support["mode"]!="cuisine_supply_supported":
        actions.append("validate_concept_specific_demand")
    if dietary!="none":
        actions.append("verify_dietary_customer_fit_and_site_requirements")
    if not income_available:
        actions.append("obtain_affordability_evidence")
    return {"version":VERSION,"status":"assessable_screening" if adequate else "insufficient_general_data",
            "recommendation_eligible":adequate,"cuisine_mode":support["mode"],
            "general_fit_basis":["format","price_positioning","audience","trading_period","area_activity","access"],
            "score_coverage":round(coverage,4),"coverage_is_probability":False,
            "survival_fallback":"Only use a validated model when available; otherwise general screening, not survival",
            "dietary_demand_measured":False,"required_actions":actions}


def property_policy(row, deal_type, rent_cap, purchase_budget):
    def positive(value):
        if isinstance(value,bool):
            return None
        try:
            value = float(value)
            return value if isfinite(value) and value>0 else None
        except (ValueError,TypeError):
            return None
    rent,price = positive(row.get("asking_rent")),positive(row.get("asking_price"))
    transaction = row.get("transaction") or row.get("deal_type")
    lease = rent is not None and rent<=rent_cap and transaction!="purchase"
    purchase = price is not None and price<=purchase_budget and transaction!="lease"
    budget = lease if deal_type=="lease" else purchase if deal_type=="purchase" else lease or purchase
    synthetic = row.get("lead_type")=="synthetic"
    return {"version":VERSION,"inventory_basis":"synthetic_scenario" if synthetic else "source_listing" if row.get("lead_type")=="listing" else "registry_context",
            "verified_live_listing":False,"budget_evidence":"within_entered_limit" if budget else "unavailable" if rent is None and price is None else "not_supported_for_requested_transaction",
            "budget_eligible":budget,"price_missing_is_zero":False,"financial_return_estimate":None,
            "availability_confirmation_required":True,"facility_confirmation_required":True,
            "synthetic_is_market_validation":False}


def catalog():
    return {"version":VERSION,"thresholds":dict(THRESHOLDS),"thresholds_calibrated":False,
            "cases":dict(CASES),"related_categories_are_demand_substitutes":False}


def attach_runtime_policy(row):
    policy = row["assessment_policy"]
    access = row.get("customer_access",{})
    survival = row.get("survival",{})
    policy["network_access_status"] = access.get("status","unavailable")
    policy["survival_status"] = survival.get("status","unavailable")
    policy["cuisine_demand_verified"] = False
    actions = policy["required_actions"]
    if access.get("index") is None and "verify_network_access" not in actions:
        actions.append("verify_network_access")
    if survival.get("probability") is None:
        policy["survival_basis"] = "unavailable_general_screening_only"
    else:
        policy["survival_basis"] = "separate_experimental_model_estimate_not_cuisine_specific"
    return policy
