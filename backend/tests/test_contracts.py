import pytest
from pydantic import ValidationError

from groundwork_backend.contracts import SourceRecord


def test_source_geometry_and_unknown_sources():
    base = {
        "source": "mta",
        "source_id": "station_1",
        "vintage": "2026",
        "observed_at": "2026-10-01",
        "geometry": {"type": "Point", "coordinates": [-73.97, 40.75]},
        "properties": {"transit_inflow": 100},
    }
    assert SourceRecord.model_validate(base).source == "mta"
    with pytest.raises(ValidationError):
        SourceRecord.model_validate({**base, "source": "unknown"})
    with pytest.raises(ValidationError):
        SourceRecord.model_validate({**base, "geometry": {"type": "Point", "coordinates": [1000, 40]}})
