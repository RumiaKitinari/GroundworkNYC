"""Rebuild NYC food and nightlife POIs from a pinned local OSM PBF."""

import csv
import math
import re
from collections import Counter, defaultdict

import osmium
from shapely.geometry import LineString, Polygon


CATEGORIES = {"restaurant", "fast_food", "food_court", "cafe", "bar", "pub", "nightclub"}
ENTITY_FIELDS = ("osm_type", "osm_id", "name", "amenity", "shop", "cuisine", "brand", "operator",
                 "opening_hours", "outdoor_seating", "takeaway", "delivery", "wheelchair",
                 "address_house_number", "address_street", "address_city", "address_postcode",
                 "phone", "website", "latitude", "longitude", "borough", "location", "geoid",
                 "competitor_category", "is_restaurant", "is_bar_nightlife", "is_cafe")
COMPETITION_FIELDS = ("geoid", "land_area_sq_miles", "food_nightlife_poi_count",
                      "restaurant_competitor_count", "bar_nightlife_competitor_count",
                      "cafe_competitor_count", "cuisine_categories", "food_nightlife_poi_per_sq_mile")
MASTER_FIELDS = COMPETITION_FIELDS[2:]


def category(tags):
    amenity = tags.get("amenity", "")
    if amenity in CATEGORIES:
        return amenity
    return "bakery" if amenity == "bakery" or tags.get("shop") in {"bakery", "pastry"} else ""


def name_key(value):
    return re.sub(r"[^\w]+", "", value.casefold())


def distance_meters(a, b):
    lat1, lon1 = a
    lat2, lon2 = b
    dy = (lat1 - lat2) * 111_195
    dx = (lon1 - lon2) * 111_195 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def per_1000_residents(count, population):
    try:
        people = float(population)
    except (TypeError, ValueError):
        return ""
    return 1000 * count / people if people > 0 else ""


def coordinate(way):
    points = [(node.lon, node.lat) for node in way.nodes if node.location.valid()]
    if len(points) < 2:
        return None
    if len(points) >= 4 and points[0] == points[-1]:
        polygon = Polygon(points)
        if polygon.is_valid and polygon.area:
            point = polygon.representative_point()
            return point.y, point.x
    point = LineString(points).centroid
    return point.y, point.x


class FoodPOIs(osmium.SimpleHandler):
    def __init__(self, tract_lookup, boroughs):
        super().__init__()
        self.tract_lookup = tract_lookup
        self.boroughs = boroughs
        self.records = []
        self.seen = set()
        self.by_name = defaultdict(list)
        self.stats = Counter()

    def accept(self, object_type, osm_id, tags, point):
        kind = category(tags)
        if not kind or point is None:
            return
        self.stats["food_objects"] += 1
        latitude, longitude = point
        geoid = self.tract_lookup(longitude, latitude)
        if not geoid:
            self.stats["outside_nyc_tracts"] += 1
            return
        identity = (object_type, osm_id)
        if identity in self.seen:
            return
        self.seen.add(identity)
        name = tags.get("name", "").strip()
        key = name_key(name)
        address = tags.get("addr:housenumber", "").strip()
        if key:
            for prior_point, prior_address in self.by_name[(geoid, key, kind)]:
                if (not address or not prior_address or address == prior_address) and distance_meters(point, prior_point) < 8:
                    self.stats["near_duplicate_removed"] += 1
                    return
            self.by_name[(geoid, key, kind)].append((point, address))
        values = {"osm_type": object_type, "osm_id": osm_id, "name": name,
                  "amenity": tags.get("amenity", ""), "shop": tags.get("shop", ""),
                  "cuisine": tags.get("cuisine", ""), "brand": tags.get("brand", ""),
                  "operator": tags.get("operator", ""), "opening_hours": tags.get("opening_hours", ""),
                  "outdoor_seating": tags.get("outdoor_seating", ""), "takeaway": tags.get("takeaway", ""),
                  "delivery": tags.get("delivery", ""), "wheelchair": tags.get("wheelchair", ""),
                  "address_house_number": address, "address_street": tags.get("addr:street", ""),
                  "address_city": tags.get("addr:city", ""), "address_postcode": tags.get("addr:postcode", ""),
                  "phone": tags.get("phone", ""), "website": tags.get("website", ""),
                  "latitude": latitude, "longitude": longitude, "borough": self.boroughs[geoid],
                  "location": f"POINT ({longitude} {latitude})", "geoid": geoid,
                  "competitor_category": kind, "is_restaurant": kind in {"restaurant", "fast_food", "food_court"},
                  "is_bar_nightlife": kind in {"bar", "pub", "nightclub"}, "is_cafe": kind == "cafe"}
        self.records.append(values)
        self.stats[f"{object_type}_retained"] += 1

    def node(self, node):
        if node.location.valid():
            self.accept("node", node.id, node.tags, (node.location.lat, node.location.lon))

    def way(self, way):
        if category(way.tags):
            self.accept("way", way.id, way.tags, coordinate(way))


def inspection_match(pois, restaurants):
    by_name = defaultdict(list)
    for row in restaurants:
        if str(row.get("active_establishment", "")).lower() != "true":
            continue
        key = name_key(row.get("dba", ""))
        try:
            point = float(row["latitude"]), float(row["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if key and row.get("geoid"):
            by_name[(row["geoid"], key)].append(point)
    matched = sum(any(distance_meters((float(poi["latitude"]), float(poi["longitude"])), point) <= 50
                      for point in by_name.get((poi["geoid"], name_key(poi["name"])), ()))
                  for poi in pois if poi["name"])
    return {"named_pois_matched_to_active_inspections": matched,
            "named_pois_checked": sum(bool(poi["name"]) for poi in pois),
            "method": "Same normalized name and tract, within 50 meters; QA only, not merged into scores"}


def rebuild(stage, pbf, master, read_csv, write_csv, polygon_index, containing_tract):
    polygons = polygon_index(stage / "geography" / "nyc_2020_census_tracts.geojson")
    boroughs = {row["geoid"]: row["borough"] for row in master}
    handler = FoodPOIs(lambda lon, lat: containing_tract(lon, lat, polygons), boroughs)
    handler.apply_file(str(pbf), locations=True, idx="flex_mem")
    pois = sorted(handler.records, key=lambda row: (row["osm_type"], int(row["osm_id"])))
    prior = read_csv(stage / "entities" / "food_nightlife_pois.csv")
    if len(pois) < max(1000, len(prior) * .8):
        raise ValueError(f"OSM coverage fell unexpectedly: {len(pois)} vs {len(prior)} prior POIs")
    if len({(poi["osm_type"], poi["osm_id"]) for poi in pois}) != len(pois):
        raise ValueError("OSM entity identifiers are not unique")
    write_csv(stage / "entities" / "food_nightlife_pois.csv", pois, ENTITY_FIELDS)
    groups = defaultdict(list)
    for poi in pois:
        groups[poi["geoid"]].append(poi)
    features = []
    for row in master:
        geoid = row["geoid"]
        subset = groups[geoid]
        values = {"geoid": geoid, "land_area_sq_miles": row["land_area_sq_miles"]}
        if subset:
            counts = Counter(poi["competitor_category"] for poi in subset)
            cuisines = {item.strip().lower() for poi in subset for item in poi["cuisine"].split(";") if item.strip()}
            values.update({"food_nightlife_poi_count": len(subset),
                           "restaurant_competitor_count": sum(counts[k] for k in ("restaurant", "fast_food", "food_court")),
                           "bar_nightlife_competitor_count": sum(counts[k] for k in ("bar", "pub", "nightclub")),
                           "cafe_competitor_count": counts["cafe"], "cuisine_categories": len(cuisines),
                           "food_nightlife_poi_per_sq_mile": len(subset) / float(row["land_area_sq_miles"])
                           if float(row["land_area_sq_miles"]) > 0 else ""})
        else:
            values.update({key: "" for key in MASTER_FIELDS})
        features.append(values)
        for field in MASTER_FIELDS:
            row[field] = values[field]
        row["food_nightlife_pois_per_1000_residents"] = per_1000_residents(len(subset), row.get("population_2024")) if subset else ""
    write_csv(stage / "features" / "tract_competition.csv", features, COMPETITION_FIELDS)
    if sum(int(feature["food_nightlife_poi_count"] or 0) for feature in features) != len(pois):
        raise ValueError("OSM tract counts do not reconcile with entity rows")
    match = inspection_match(pois, read_csv(stage / "entities" / "current_restaurants.csv"))
    return {"prior_pois": len(prior), "pois": len(pois),
            "tracts_with_pois": sum(bool(items) for items in groups.values()),
            "named_pois": sum(bool(poi["name"]) for poi in pois),
            "cuisine_tagged_pois": sum(bool(poi["cuisine"]) for poi in pois),
            "categories": dict(sorted(Counter(poi["competitor_category"] for poi in pois).items())),
            "geometry": dict(handler.stats), "inspection_match": match}
