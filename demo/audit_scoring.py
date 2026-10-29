"""Compare concept-screening behavior before publishing an integrated release."""

import csv
import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from app import PROFILE_WEIGHTS
from scoring import Concept, ScreeningModel
STYLE = {"coffee": "quick_service", "fast_casual": "quick_service", "counter_service": "quick_service",
         "bakery": "quick_service", "takeout_delivery": "quick_service", "fine_dining": "fine_dining"}


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scenarios():
    result = {}
    for profile in PROFILE_WEIGHTS:
        result[f"format:{profile}"] = {"profile": profile, "price_tier": "$$"}
    for profile in ("restaurant", "coffee", "fine_dining"):
        for tier in ("$", "$$", "$$$", "$$$$"):
            result[f"price:{profile}:{tier}"] = {"profile": profile, "price_tier": tier}
    for cuisine in ("any", "korean", "italian", "mexican", "vegetarian_vegan"):
        result[f"cuisine:{cuisine}"] = {"profile": "restaurant", "price_tier": "$$", "cuisine": cuisine}
    for daypart in ("all_day", "morning", "lunch", "evening"):
        result[f"daypart:{daypart}"] = {"profile": "restaurant", "price_tier": "$$", "daypart": daypart}
    result["dietary:vegan_mexican"] = {"profile": "restaurant", "price_tier": "$$",
                                       "cuisine": "mexican", "dietary": "vegan"}
    return result


def evaluate_release(directory, briefs=None):
    directory = Path(directory)
    rows = [row for row in read_csv(directory / "master_tract_features.csv")
            if row.get("eligible_for_location_screening", "").lower() in {"true", "1"}
            and row.get("borough") != "Staten Island" and row.get("centroid_latitude") and row.get("centroid_longitude")]
    restaurants = read_csv(directory / "entities" / "current_restaurants.csv")
    model = ScreeningModel(rows, restaurants)
    briefs = briefs or scenarios()
    values = {}
    for name, brief in briefs.items():
        profile = brief["profile"]
        concept = Concept.from_args({"profile": profile, "service_style": STYLE.get(profile, "casual"),
                                     "price_mode": "tier", "price_tier": brief["price_tier"],
                                     "cuisine": brief.get("cuisine", "any"), "daypart": brief.get("daypart", "all_day"),
                                     "dietary": brief.get("dietary", "none")})
        weights = PROFILE_WEIGHTS[profile]
        values[name] = {row["geoid"]: model.evaluate(row, concept, weights, profile)["opportunity"] for row in rows}
    return values


def compare(left, right):
    common = left.keys() & right.keys()
    if not common:
        raise ValueError("No shared eligible tracts for score comparison")
    deltas = [abs(left[geoid] - right[geoid]) for geoid in common]
    size = max(1, round(len(common) * .1))
    left_top = set(sorted(common, key=lambda geoid: (-left[geoid], geoid))[:size])
    right_top = set(sorted(common, key=lambda geoid: (-right[geoid], geoid))[:size])
    largest = sorted(common, key=lambda geoid: (-abs(left[geoid] - right[geoid]), geoid))[:5]
    return {"tracts": len(common), "changed_fraction": round(sum(delta > 0 for delta in deltas) / len(deltas), 3),
            "median_absolute_change": round(statistics.median(deltas), 2),
            "p95_absolute_change": round(sorted(deltas)[int(.95 * (len(deltas) - 1))], 2),
            "top_decile_overlap": round(len(left_top & right_top) / size, 3),
            "largest_changes": [{"geoid": geoid, "before": left[geoid], "after": right[geoid]}
                                for geoid in largest]}


def sensitivity_pairs():
    pairs = []
    for profile in ("coffee", "fine_dining", "fast_casual", "bar", "bakery", "takeout_delivery", "counter_service"):
        pairs.append(("format", "format:restaurant", f"format:{profile}"))
    for profile in ("restaurant", "coffee", "fine_dining"):
        for low, high in zip(("$", "$$", "$$$"), ("$$", "$$$", "$$$$")):
            pairs.append(("price", f"price:{profile}:{low}", f"price:{profile}:{high}"))
    for cuisine in ("korean", "italian", "mexican", "vegetarian_vegan"):
        pairs.append(("cuisine", "cuisine:any", f"cuisine:{cuisine}"))
    for daypart in ("morning", "lunch", "evening"):
        pairs.append(("daypart", "daypart:all_day", f"daypart:{daypart}"))
    pairs.append(("dietary", "cuisine:mexican", "dietary:vegan_mexican"))
    return pairs


def audit_releases(before, after):
    before, after = Path(before), Path(after)
    briefs = scenarios()
    old = evaluate_release(before, briefs)
    new = evaluate_release(after, briefs)
    sensitivity = {}
    flags = []
    for dimension, first, second in sensitivity_pairs():
        result = compare(new[first], new[second])
        sensitivity[f"{first} vs {second}"] = {"dimension": dimension, **result}
        if result["changed_fraction"] < .1 or result["median_absolute_change"] == 0:
            flags.append(f"Weak {dimension} response: {first} vs {second}")
    changes = {name: compare(old[name], new[name]) for name in briefs}
    if any(result["p95_absolute_change"] > 20 for result in changes.values()):
        flags.append("Large score shift after data refresh; review largest tract changes")
    return {"created_at": datetime.now(timezone.utc).isoformat(),
            "before": str(before), "after": str(after),
            "input_sha256": {"before_master": sha256(before / "master_tract_features.csv"),
                             "after_master": sha256(after / "master_tract_features.csv"),
                             "before_restaurants": sha256(before / "entities" / "current_restaurants.csv"),
                             "after_restaurants": sha256(after / "entities" / "current_restaurants.csv")},
            "assessment": "Deterministic score behavior audit, not predictive validation",
            "refresh_changes": changes, "concept_sensitivity": sensitivity,
            "review_flags": flags}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit_releases(args.before, args.after)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
