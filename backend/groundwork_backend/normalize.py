"""Convert versioned source exports to the spatial ingestion contract."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .contracts import SourceRecord


def normalize_csv(input_path, output_path, mapping_path, geography_path=None):
    """Column mapping avoids embedding assumptions about source vintages/CSV layouts.

    Each CSV row must represent one geographic aggregate or one current entity.
    Repeated IDs are rejected (raw inspection histories must be reduced upstream).
    """
    config = json.loads(Path(mapping_path).read_text())
    geometries = {}
    if geography_path:
        document = json.loads(Path(geography_path).read_text())
        key = config.get("geometry_key", "geoid")
        geometries = {str(f["properties"][key]): f["geometry"] for f in document["features"]}
    count, seen = 0, set()
    destination = Path(output_path)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Path(input_path).open(newline="", encoding="utf-8-sig") as stream, temporary.open("w") as output:
            for raw in csv.DictReader(stream):
                entity_id = raw[config["id_column"]].strip()
                if entity_id in seen:
                    raise ValueError(
                        f"Duplicate source ID {entity_id}; aggregate or deduplicate this export first."
                    )
                seen.add(entity_id)
                if geometries:
                    geometry = geometries[raw[config["geography_column"]]]
                else:
                    geometry = {
                        "type": "Point",
                        "coordinates": [
                            float(raw[config["longitude_column"]]),
                            float(raw[config["latitude_column"]]),
                        ],
                    }
                properties = {name: float(raw[column]) for name, column in config.get("metrics", {}).items()}
                properties.update(config.get("constants", {}))
                record = SourceRecord(
                    source=config["source"],
                    source_id=entity_id,
                    vintage=config["vintage"],
                    observed_at=config["observed_at"],
                    geometry=geometry,
                    properties=properties,
                )
                output.write(record.model_dump_json() + "\n")
                count += 1
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return count
