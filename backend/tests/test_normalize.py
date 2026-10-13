import json

import pytest

from groundwork_backend.normalize import normalize_csv


def test_normalization_preserves_geographic_counts_and_rejects_duplicate_ids(tmp_path):
    source = tmp_path / "acs.csv"
    source.write_text("geoid,population,income\n001,1000,80000\n")
    geography = tmp_path / "tracts.json"
    geography.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"geoid": "001"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[-74, 40.7], [-73.99, 40.7], [-73.99, 40.71], [-74, 40.7]]],
                        },
                    }
                ],
            }
        )
    )
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps(
            {
                "source": "acs",
                "vintage": "2024",
                "observed_at": "2026-10-08",
                "id_column": "geoid",
                "geography_column": "geoid",
                "metrics": {"residents": "population", "median_income": "income"},
            }
        )
    )
    output = tmp_path / "records.jsonl"
    assert normalize_csv(source, output, mapping, geography) == 1
    original = output.read_text()
    row = json.loads(original)
    assert row["properties"]["residents"] == 1000
    assert row["source_id"] == "001"
    source.write_text("geoid,population,income\n001,1000,80000\n001,900,70000\n")
    with pytest.raises(ValueError, match="Duplicate"):
        normalize_csv(source, output, mapping, geography)
    assert output.read_text() == original
