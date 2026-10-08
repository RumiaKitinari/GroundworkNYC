"""Editorial menu ideas and optional rights-cleared dish-mention evidence."""

import csv
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path


CATALOG_PATH = Path(__file__).with_name("menu_catalog.csv")
REVIEW_PATH = Path(__file__).resolve().parents[1] / "data" / "menu" / "review_mentions.csv"
SECTIONS = ("Starters", "Mains", "Sides", "Desserts", "Drinks")
FORMAT_TAGS = {
    "restaurant": ("sit_down",), "bar": ("bar", "sit_down"), "coffee": ("cafe",),
    "fast_casual": ("quick",), "counter_service": ("quick",),
    "bakery": ("cafe", "quick"), "fine_dining": ("premium", "sit_down"),
    "takeout_delivery": ("quick",),
}
CUISINE_ALIASES = {"vegetarian_vegan": "vegan", "vegetarian": "vegan",
                   "bakery_pastries": "bakery", "desserts_ice_cream": "desserts",
                   "salads_bowls": "salads", "sandwiches_deli": "sandwiches"}


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


@lru_cache(maxsize=1)
def catalog():
    with CATALOG_PATH.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    items = []
    seen = set()
    for row in rows:
        item_id = f"{row['cuisine']}:{slug(row['name'])}"
        if item_id in seen or row["section"] not in SECTIONS or not row["name"].strip():
            raise ValueError(f"Invalid or duplicate menu catalog item: {item_id}")
        seen.add(item_id)
        items.append({"id": item_id, "cuisine": row["cuisine"], "name": row["name"],
                      "section": row["section"], "formats": row["formats"].split(";"),
                      "plant_based_candidate": row["plant_based_candidate"] == "yes"})
    return items


def review_signals(path=REVIEW_PATH):
    """Restaurant-review mentions, not dish ratings; never infer from restaurant stars alone."""
    path = Path(path)
    if not path.is_file():
        return {}
    required = {"review_id", "restaurant_id", "dish_id", "review_rating", "observed_on", "source_url", "rights_basis"}
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not required <= set(reader.fieldnames or ()):
            raise ValueError("Menu review evidence is missing required provenance columns")
        rows = list(reader)
    groups = defaultdict(lambda: {"reviews": set(), "restaurants": set(), "positive": 0})
    known = {item["id"] for item in catalog()}
    for row in rows:
        if not all(row.get(key, "").strip() for key in required) or row["dish_id"] not in known:
            continue
        try:
            rating = float(row["review_rating"])
        except ValueError:
            continue
        if not 1 <= rating <= 5 or not row["source_url"].startswith("https://"):
            continue
        group = groups[row["dish_id"]]
        if row["review_id"] in group["reviews"]:
            continue
        group["reviews"].add(row["review_id"])
        group["restaurants"].add(row["restaurant_id"])
        group["positive"] += rating >= 4
    return {item_id: {"mention_count": len(group["reviews"]), "positive_mention_share": round(group["positive"] / len(group["reviews"]), 2),
                      "restaurant_count": len(group["restaurants"]), "basis": "Restaurant reviews explicitly mentioning this dish; rating is for the restaurant, not the dish"}
            for item_id, group in groups.items() if len(group["reviews"]) >= 20 and len(group["restaurants"]) >= 5}


def suggestions(cuisine, profile, dietary="none", query="", average_check=35):
    matched_cuisine = CUISINE_ALIASES.get(cuisine, cuisine)
    all_items = catalog()
    supported = matched_cuisine == "any" or any(item["cuisine"] == matched_cuisine for item in all_items)
    if not supported:
        return {"status": "unavailable", "items": [], "cuisine": cuisine, "review_evidence": "unavailable",
                "message": "No cuisine-specific catalog is available yet. Add your own dishes below."}
    formats = FORMAT_TAGS.get(profile, FORMAT_TAGS["restaurant"])
    if matched_cuisine == "any":
        cuisine_keys = {"any"}
        if profile == "coffee": cuisine_keys.add("coffee_tea")
        if profile == "bakery": cuisine_keys.add("bakery")
    else:
        cuisine_keys = {matched_cuisine, "any"}
    query = query.strip().casefold()[:80]
    candidates = [item for item in all_items if item["cuisine"] in cuisine_keys
                  and ("all" in item["formats"] or any(tag in item["formats"] for tag in formats))
                  and (dietary not in {"vegan", "vegetarian"} or item["plant_based_candidate"])
                  and (not query or query in item["name"].casefold())]
    preferred = {"premium"} if average_check >= 50 else {"quick", "cafe"}
    candidates.sort(key=lambda item: (item["cuisine"] != matched_cuisine, SECTIONS.index(item["section"]),
                                      not bool(preferred.intersection(item["formats"])), item["name"]))
    evidence = review_signals()
    items = [{"id": item["id"], "name": item["name"], "section": item["section"],
              "source": "Editorial menu catalog", "review_signal": evidence.get(item["id"])} for item in candidates]
    return {"status": "available", "items": items, "cuisine": cuisine,
            "review_evidence": "available" if evidence else "unavailable",
            "message": "Plant-based dishes are candidates only; verify ingredients and preparation." if dietary in {"vegan", "vegetarian"} else ""}
