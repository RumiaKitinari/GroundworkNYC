"""Versioned, uncalibrated location screening using the integrated package only."""

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from math import isfinite
import re


MODEL_VERSION = "concept-screening-0.2"
CUISINES = {
    "any": (), "korean": ("Korean",), "chinese": ("Chinese", "Chinese/Japanese"),
    "japanese": ("Japanese", "Chinese/Japanese"), "indian": ("Indian",),
    "italian": ("Italian",), "mexican": ("Mexican", "Tex-Mex"),
    "thai": ("Thai",), "french": ("French", "New French"),
    "mediterranean": ("Mediterranean",), "middle_eastern": ("Middle Eastern",),
    "caribbean": ("Caribbean",), "american": ("American", "New American"),
    "greek": ("Greek",),
    "peruvian": ("Peruvian",), "brazilian": ("Brazilian",),
    "filipino": ("Filipino",), "vietnamese": ("Vietnamese",),
    "turkish": ("Turkish",), "ethiopian": ("Ethiopian",),
    "pakistani": ("Pakistani",), "bangladeshi": ("Bangladeshi",),
    "spanish": ("Spanish",), "eastern_european": ("Eastern European", "Russian", "Polish"),
    "pizza": ("Pizza",), "seafood": ("Seafood",),
    "steakhouse": ("Steakhouse",), "barbecue": ("Barbecue",),
    "burgers": ("Hamburgers",), "sandwiches": ("Sandwiches", "Sandwiches/Salads/Mixed Buffet"),
    "bakery": ("Bakery Products/Desserts",), "coffee_tea": ("Coffee/Tea",),
    "desserts": ("Frozen Desserts", "Bakery Products/Desserts"),
    "salads": ("Salads", "Sandwiches/Salads/Mixed Buffet"),
    "vegan": ("Vegan",), "vegetarian": ("Vegetarian",),
    "southern_soul": ("Soul Food",), "cajun_creole": ("Creole", "Creole/Cajun"),
    "portuguese": ("Portuguese",), "german_central": ("German",),
    "colombian": (), "venezuelan": (), "cuban": (), "dominican": (),
    "puerto_rican": (), "jamaican": (), "haitian": (), "west_african": (),
    "pakistani_bangladeshi": ("Pakistani", "Bangladeshi"), "taiwanese": (),
    "indonesian_malaysian": (), "persian_iranian": ("Iranian",),
    "sandwiches_deli": ("Sandwiches",), "bakery_pastries": ("Bakery Products/Desserts",),
    "desserts_ice_cream": ("Frozen Desserts", "Bakery Products/Desserts"),
    "salads_bowls": ("Salads",), "breakfast_brunch": (), "noodles": (),
    "vegetarian_vegan": ("Vegetarian", "Vegan"), "health_focused": (),
    "fusion": ("Fusion",), "custom": (),
}
PRICE_TIERS = {"$": 18, "$$": 35, "$$$": 65, "$$$$": 110}
DIETARY_LABELS = {"vegan": ("Vegan",), "vegetarian": ("Vegan", "Vegetarian")}
CUISINE_ALIASES = {
    "southern_soul": ("southern", "soul food"),
    "cajun_creole": ("cajun", "creole"),
    "german_central": ("german", "central european"),
    "pakistani_bangladeshi": ("pakistani", "bangladeshi"),
    "persian_iranian": ("persian", "iranian"),
    "sandwiches_deli": ("sandwich", "sandwiches", "deli"),
    "bakery_pastries": ("bakery", "pastry", "pastries"),
    "desserts_ice_cream": ("dessert", "desserts", "ice cream"),
    "salads_bowls": ("salad", "salads", "grain bowl", "bowls"),
    "breakfast_brunch": ("breakfast", "brunch"),
    "vegetarian_vegan": ("vegan", "vegetarian", "plant based", "plant-based"),
    "health_focused": ("health focused", "healthy"),
    "coffee_tea": ("coffee", "tea"),
    "indonesian_malaysian": ("indonesian", "malaysian"),
}


def cuisine_from_text(text):
    candidates = []
    for cuisine in CUISINES:
        if cuisine in {"any", "vegan", "vegetarian"}:
            continue
        phrases = (cuisine.replace("_", " "), *CUISINE_ALIASES.get(cuisine, ()))
        for phrase in phrases:
            if re.search(r"\b" + re.escape(phrase) + r"\b", text):
                # Specific cuisine beats a dietary-only or generic specialty match.
                priority = 0 if cuisine == "vegetarian_vegan" else 1
                candidates.append((priority, len(phrase), cuisine))
    return max(candidates)[2] if candidates else "any"


def number(value):
    try:
        result = float(value)
        return result if isfinite(result) and result >= 0 else None
    except (TypeError, ValueError):
        return None


def bounded(value):
    return round(max(0, min(100, value)))


@dataclass(frozen=True)
class Concept:
    cuisine: str = "any"
    service_style: str = "casual"
    average_check: float = 35
    audience: str = "residents"
    daypart: str = "all_day"
    price_tier: str = "$$"
    dietary: str = "none"
    description: str = ""
    price_mode: str = "exact"

    @classmethod
    def from_args(cls, args):
        cuisine = args.get("cuisine", "any")
        default_style = "fine_dining" if args.get("profile") == "fine_dining" else "quick_service" if args.get("profile") in {"fast_casual", "counter_service", "takeout_delivery", "coffee", "bakery"} else "casual"
        style = args.get("service_style", default_style)
        audience = args.get("audience", "residents")
        daypart = args.get("daypart", "all_day")
        price_tier = args.get("price_tier", "$$")
        price_mode = args.get("price_mode", "exact")
        dietary = args.get("dietary", "none")
        description = str(args.get("description", "")).strip()
        concept_text = f"{args.get('concept_name', '')} {description}".lower()
        if cuisine == "any":
            cuisine = cuisine_from_text(concept_text)
        if dietary == "none":
            for candidate in ("vegan", "vegetarian", "halal", "kosher", "gluten_free"):
                pattern = r"\bgluten[- ]free\b" if candidate == "gluten_free" else r"\b" + candidate + r"\b"
                if re.search(pattern, concept_text):
                    dietary = candidate
                    break
        check = number(PRICE_TIERS.get(price_tier) if price_mode == "tier" else args.get("average_check", 35))
        if cuisine not in CUISINES or style not in {"quick_service", "casual", "fine_dining"}:
            raise ValueError("Choose a supported cuisine and service style.")
        if audience not in {"residents", "workers", "destination"} or daypart not in {"all_day", "morning", "lunch", "evening"}:
            raise ValueError("Choose a supported customer focus and trading period.")
        if check is None or not 5 <= check <= 250:
            raise ValueError("Average spend must be between $5 and $250 per guest.")
        if price_tier not in PRICE_TIERS or price_mode not in {"tier", "exact"} or dietary not in {"none", "vegan", "vegetarian", "halal", "kosher", "gluten_free"}:
            raise ValueError("Choose a supported price tier and dietary identity.")
        if len(description) > 500:
            raise ValueError("Concept description must be 500 characters or less.")
        return cls(cuisine, style, check, audience, daypart, price_tier, dietary, description, price_mode)

    def public(self):
        return asdict(self)


def resolve_concept(args):
    name = str(args.get("concept_name", "")).strip()
    description = str(args.get("description", "")).strip()
    text = f"{name} {description}".lower()
    profile = str(args.get("profile", "")).strip()
    profiles = {
        "bar": ("gastropub", "cocktail bar", "wine bar", "with bar"),
        "restaurant": ("restaurant", "bistro", "sit down", "sit-down"),
        "coffee": ("cafe", "café", "coffee shop"),
        "fast_casual": ("fast casual",),
        "counter_service": ("counter service",),
        "bakery": ("bakery", "pastry shop"),
        "fine_dining": ("fine dining",),
        "takeout_delivery": ("takeout", "take-out", "delivery only"),
    }
    if not profile:
        profile = next((key for key, terms in profiles.items() if any(term in text for term in terms)), "restaurant")
    if profile not in profiles:
        raise ValueError("Choose a supported restaurant format.")
    values = dict(args)
    values["profile"] = profile
    concept = Concept.from_args(values)
    return {
        "name": name or "Restaurant Concept",
        "profile": profile,
        "concept": concept.public(),
        "field_sources": {
            "cuisine": "entered" if args.get("cuisine", "any") != "any" else "inferred" if concept.cuisine != "any" else "unspecified",
            "dietary": "entered" if args.get("dietary", "none") != "none" else "inferred" if concept.dietary != "none" else "unspecified",
            "profile": "entered" if args.get("profile") else "inferred" if profile != "restaurant" else "default",
            "price": "entered" if concept.price_mode == "exact" and args.get("average_check") else "tier_assumption" if concept.price_mode == "tier" else "default",
        },
        "cuisine_evidence": "unspecified" if concept.cuisine == "any" else "separately_classified" if CUISINES[concept.cuisine] else "not_separately_classified",
    }


class ScreeningModel:
    def __init__(self, tracts, restaurants):
        self.tracts = {row["geoid"]: row for row in tracts}
        self.distributions = {}
        for key in tracts[0] if tracts else []:
            values = [number(row.get(key)) for row in tracts]
            self.distributions[key] = sorted(value for value in values if value is not None)
        self.local = defaultdict(Counter)
        self.neighborhood = defaultdict(Counter)
        self.city = Counter()
        seen = set()
        for row in restaurants:
            identifier = row.get("camis")
            geoid = row.get("geoid")
            if not identifier or identifier in seen or geoid not in self.tracts:
                continue
            if str(row.get("active_establishment", "")).lower() != "true":
                continue
            seen.add(identifier)
            label = row.get("cuisine_description", "").strip()
            # Unknown cuisine is counted in inventory, never treated as a confirmed gap.
            label = label if label not in {"", "Other", "Not Listed/Not Applicable"} else "unknown"
            nta = self.tracts[geoid].get("nta_code")
            self.local[geoid][label] += 1
            if nta:
                self.neighborhood[nta][label] += 1
            self.city[label] += 1

    def percentile(self, row, column):
        value = number(row.get(column))
        values = self.distributions.get(column, [])
        if value is None or not values:
            return (50, 0)
        if value == 0:
            return (0, 1)
        rank = (bisect_left(values, value) + bisect_right(values, value)) / (2 * len(values))
        return (100 * rank, 1)

    @staticmethod
    def mix(parts):
        # Missing or weak measurements shrink toward neutral, not a favorable extreme.
        total = sum(weight for _, weight in parts)
        score = sum((value * coverage + 50 * (1 - coverage)) * weight for (value, coverage), weight in parts) / total
        coverage = sum(coverage * weight for (_, coverage), weight in parts) / total
        return (score, coverage)

    def evaluate(self, row, concept, weights, profile):
        p = lambda column: self.percentile(row, column)
        population = p("population_density_per_sq_mile")
        workers = p("job_density_per_sq_mile")
        transit_distance = number(row.get("nearest_subway_distance_miles"))
        subway = (100 / (1 + (transit_distance / .35) ** 2), 1) if transit_distance is not None else (50, 0)
        ridership = p("nearest_subway_weekly_ridership")
        ridership = (ridership[0], ridership[1] * subway[0] / 100 * .75)
        pedestrian_distance = number(row.get("nearest_pedestrian_count_site_distance_miles"))
        pedestrian = p("nearest_pedestrian_count_site_latest_pedestrian_count_total")
        reliability = 1 / (1 + (pedestrian_distance / .25) ** 2) if pedestrian_distance is not None else 0
        pedestrian = (pedestrian[0], pedestrian[1] * reliability)
        evening = p("citibike_evening_departures_august_2026")
        evening = (evening[0], evening[1] * .6)
        worker_weight = .4 if concept.audience == "workers" or concept.daypart in {"morning", "lunch"} else .15
        evening_weight = .25 if concept.daypart == "evening" else .08
        demand = self.mix([(population, .35), (workers, worker_weight), (ridership, .18), (pedestrian, .18), (evening, evening_weight)])

        raw_walkability = number(row.get("national_walkability_index"))
        walkability = ((raw_walkability - 1) / 19 * 100, 1) if raw_walkability is not None and 1 <= raw_walkability <= 20 else (50, 0)
        walkability = (max(0, min(100, walkability[0])), walkability[1])
        destination = concept.audience == "destination" or concept.service_style == "fine_dining"
        walking_weight = .35 if destination else .75 if concept.service_style == "quick_service" else .6
        access = self.mix([(walkability, walking_weight), (subway, 1 - walking_weight)])

        income = number(row.get("median_household_income_2024"))
        income_moe = number(row.get("median_household_income_margin_of_error_2024"))
        income_reliability = max(.2, 1 - income_moe / income) if income and income_moe is not None else .5 if income else 0
        # An explicit affordability assumption, not an estimate of willingness to pay.
        required_income = concept.average_check * 2000
        spending = (min(100, 65 * income / required_income), income_reliability) if income else (50, 0)
        audience = workers if concept.audience == "workers" else population if concept.audience == "residents" else self.mix([(ridership, .6), (workers, .4)])
        spending_weight = {"fine_dining": .65, "casual": .45, "quick_service": .3}[concept.service_style]
        customer_fit = self.mix([(spending, spending_weight), (audience, 1 - spending_weight)])

        local = self.local[row["geoid"]]
        nearby = self.neighborhood.get(row.get("nta_code"), Counter())
        total = sum(local.values())
        known = total - local["unknown"]
        catalog_coverage = known / total if total else 0
        labels = CUISINES[concept.cuisine]
        same = sum(local[label] for label in labels)
        nearby_same = sum(nearby[label] for label in labels)
        nearby_known = sum(nearby.values()) - nearby["unknown"]
        city_known = sum(self.city.values()) - self.city["unknown"]
        city_share = sum(self.city[label] for label in labels) / max(1, city_known)
        expected = known * city_share
        affinity = (nearby_same / nearby_known / city_share) if nearby_known and city_share else None
        # Shrink small inventories and incomplete cuisine labels before rewarding scarcity.
        cuisine_evidence = catalog_coverage * min(1, known / 10) if labels else 0
        scarcity = max(0, min(100, 50 + 50 * (expected - same) / (expected + 2))) if labels else 50
        feasibility = min(demand[0], customer_fit[0])
        gap_value = scarcity * feasibility / 100
        ecosystem_support = min(100, 50 * affinity) * min(1, nearby_same / 5) if affinity is not None else 0
        ecosystem_value = ecosystem_support * feasibility / 100
        ecosystem_evidence = (nearby_known / max(1, sum(nearby.values()))) * min(1, nearby_same / 5) if labels else 0
        opportunity_value, opportunity_evidence = (ecosystem_value, ecosystem_evidence) if ecosystem_value > gap_value else (gap_value, cuisine_evidence)
        market_gap = (opportunity_value, min(demand[1], customer_fit[1], opportunity_evidence)) if labels else (50, 0)
        dietary_positioning = None
        if concept.dietary in DIETARY_LABELS:
            dietary_labels = DIETARY_LABELS[concept.dietary]
            dietary_same = sum(local[label] for label in dietary_labels)
            dietary_city_share = sum(self.city[label] for label in dietary_labels) / max(1, city_known)
            dietary_expected = known * dietary_city_share
            dietary_gap = max(0, min(100, 50 + 50 * (dietary_expected - dietary_same) / (dietary_expected + 2)))
            dietary_evidence = catalog_coverage * min(1, known / 10) * .45
            dietary_score = (dietary_gap * feasibility / 100, dietary_evidence)
            market_gap = self.mix([(dietary_score, .7), (market_gap, .3)])
            dietary_positioning = f"{concept.dietary.title()} Supply: {dietary_same} Recorded In Tract"
        elif concept.dietary != "none":
            dietary_positioning = "Dietary Demand Data Unavailable"
        competitor_column = "bar_nightlife_competitor_count" if profile == "bar" else "cafe_competitor_count" if profile in {"coffee", "bakery"} else "restaurant_competitor_count"
        pressure = p(competitor_column)
        competition = (max(0, min(100, 55 + (demand[0] - pressure[0]) * .5)), min(demand[1], pressure[1]))
        commercial = self.mix([(p("retail_area_sqft"), .4), (p("mixed_use_parcel_count"), .3), (p("reported_storefront_property_count"), .3)])

        components = {"demand": demand, "customer_fit": customer_fit, "access": access, "market_gap": market_gap, "competition_balance": competition, "economics": commercial}
        overall = self.mix([(components[key], weight) for key, weight in weights.items()])
        draw = self.mix([(components[key], weight) for key, weight in weights.items() if key != "economics"])
        if not labels:
            positioning = "Cuisine Not Separately Classified" if concept.cuisine != "any" else "Cuisine Not Specified"
        elif cuisine_evidence < .5:
            positioning = "Limited Cuisine Evidence"
        elif feasibility >= 65 and same < expected:
            positioning = "Potential Cuisine Gap"
        elif nearby_same >= 3 and affinity is not None and affinity >= 1.25:
            positioning = "Established Cuisine Market"
        else:
            positioning = "Mixed Market Signals"
        risks = []
        if reliability < .3:
            risks.append("Limited Nearby Pedestrian Evidence")
        if labels and cuisine_evidence < .5:
            risks.append("Limited Cuisine Inventory")
        if income_reliability < .7:
            risks.append("Household Income Estimate Is Uncertain")
        if labels and same == 0:
            risks.append("No Recorded Same-Cuisine Restaurants; Demand Is Unverified")
        if concept.cuisine != "any" and not labels:
            risks.append("Cuisine Not Separately Classified In Restaurant Source")
        if concept.dietary != "none":
            risks.append("Dietary Customer Demand Is Not Measured")
        if feasibility < 50:
            risks.append("Demand Or Spending Fit Requires Review")
        if not risks:
            risks.append("Validate Site Visibility And Customer Demand")
        return {
            "model_version": MODEL_VERSION,
            "opportunity": bounded(overall[0]), "confidence_score": bounded(overall[1] * 100),
            "walkability": bounded(walkability[0]) if walkability[1] else None,
            "business_draw": bounded(draw[0]), "business_draw_coverage": bounded(draw[1] * 100),
            "components": {key: {"score": bounded(value), "coverage": bounded(coverage * 100)} for key, (value, coverage) in components.items()},
            "risk_flags": risks,
            "concept_evidence": {
                "positioning": positioning, "cuisine": concept.cuisine, "same_cuisine_count": same if labels else None,
                "neighborhood_same_cuisine_count": nearby_same if labels else None,
                "cuisine_inventory_count": total, "cuisine_label_coverage": bounded(catalog_coverage * 100),
                "cuisine_evidence_coverage": bounded(cuisine_evidence * 100),
                "cuisine_gap_index": bounded(gap_value) if labels else None,
                "cuisine_ecosystem_index": bounded(ecosystem_value) if labels else None,
                "expected_same_cuisine_count": round(expected, 1) if labels else None,
                "neighborhood_name": row.get("nta_name"), "population": number(row.get("population_2024")),
                "workers": number(row.get("total_jobs")), "median_household_income": income,
                "income_margin_of_error": income_moe, "average_check": concept.average_check,
                "epa_walkability_index": raw_walkability, "pedestrian_site_distance_miles": pedestrian_distance,
                "visit_forecast": None, "assessment_type": "Uncalibrated Screening Index",
                "dietary_positioning": dietary_positioning,
            },
        }
