"""Crosswalk the full EPA SLD v3 block-group geometry to NYC 2020 tracts."""

import csv
import io
import math
import subprocess
from collections import defaultdict

from shapely import wkt
from shapely.strtree import STRtree
from shapely.validation import make_valid


EPA_FIELDS = ("geoid", "walkability_population_weight", "national_walkability_index", "smart_location_score")
NYC_COUNTIES = ("005", "047", "061", "081", "085")


def ogr_csv(source, layer=None, fields=None, where=None):
    command = ["ogr2ogr", "-f", "CSV", "/vsistdout/", str(source)]
    if layer:
        command.append(layer)
    if fields:
        command.extend(["-select", ",".join(fields)])
    if where:
        command.extend(["-where", where])
    command.extend(["-lco", "GEOMETRY=AS_WKT", "-t_srs", "EPSG:32618"])
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=300)
    except FileNotFoundError as error:
        raise ValueError("GDAL ogr2ogr is required to rebuild EPA walkability") from error
    if result.returncode:
        raise ValueError("GDAL could not read the EPA geometry: " + result.stderr[-500:])
    return list(csv.DictReader(io.StringIO(result.stdout)))


def geometry(row):
    shape = wkt.loads(row.get("WKT") or row.get("Shape"))
    return make_valid(shape) if not shape.is_valid else shape


def aggregate(tracts, block_groups):
    tract_ids = [row["geoid"] for row in tracts]
    shapes = [geometry(row) for row in tracts]
    tree = STRtree(shapes)
    sums = defaultdict(lambda: [0.0, 0.0, 0.0])
    matched = 0
    seen = set()
    for row in block_groups:
        block_id = row.get("GEOID10") or row.get("GEOID20")
        if not block_id or block_id in seen:
            raise ValueError("EPA block-group GEOID is missing or duplicated")
        seen.add(block_id)
        try:
            population = float(row["TotPop"])
            walkability = float(row["NatWalkInd"])
            smart = float(row["SLC_score"])
        except (KeyError, TypeError, ValueError):
            continue
        if not all(map(math.isfinite, (population, walkability, smart))) or population <= 0:
            continue
        polygon = geometry(row)
        if polygon.area <= 0:
            continue
        found = False
        for index in tree.query(polygon):
            overlap = polygon.intersection(shapes[index]).area
            if overlap <= 0:
                continue
            weight = population * min(1.0, overlap / polygon.area)
            totals = sums[tract_ids[index]]
            totals[0] += weight
            totals[1] += walkability * weight
            totals[2] += smart * weight
            found = True
        matched += found
    values = {}
    for geoid, (population, walkability, smart) in sums.items():
        if population:
            values[geoid] = {"walkability_population_weight": round(population, 2),
                             "national_walkability_index": round(walkability / population, 6),
                             "smart_location_score": round(smart / population, 6)}
    return values, {"block_groups": len(block_groups), "population_bearing_groups_matched": matched,
                    "tracts_with_walkability": len(values)}


def rebuild(stage, raw, master, write_csv, minimum_groups=6000, minimum_tracts=2000):
    tract_rows = ogr_csv(stage / "geography" / "nyc_2020_census_tracts.geojson", fields=["geoid"])
    counties = ",".join(f"'{county}'" for county in NYC_COUNTIES)
    source = "/vsizip/" + str(raw.resolve()) + "/SmartLocationDatabase.gdb"
    block_rows = ogr_csv(source, "EPA_SLD_Database_V3",
                         fields=["GEOID10", "GEOID20", "TotPop", "NatWalkInd", "SLC_score"],
                         where=f"STATEFP='36' AND COUNTYFP IN ({counties})")
    if len(block_rows) < minimum_groups:
        raise ValueError(f"EPA full NYC block-group coverage is incomplete: {len(block_rows)}")
    values, summary = aggregate(tract_rows, block_rows)
    if len(values) < minimum_tracts:
        raise ValueError(f"EPA 2020-tract crosswalk is incomplete: {len(values)}")
    features = []
    for row in master:
        value = values.get(row["geoid"], {})
        feature = {"geoid": row["geoid"], **{field: value.get(field, "") for field in EPA_FIELDS[1:]}}
        row.update(feature)
        features.append(feature)
    write_csv(stage / "features" / "tract_walkability.csv", features, EPA_FIELDS)
    return {**summary, "method": "EPA block-group polygons intersected with 2020 tracts in UTM 18N; "
            "2018 population allocated by intersected area then used as the index weight"}
