from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PointRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    latitude: float = Field(ge=40.45, le=40.95)
    longitude: float = Field(ge=-74.30, le=-73.65)
    resolution: Literal[7, 8, 9] = 8
    snapshot: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,80}$")


class PredictionRequest(PointRequest):
    model_version: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    source: Literal["dohmh", "acs", "lodes", "mta", "walkability"]
    source_id: str = Field(min_length=1, max_length=200)
    vintage: str = Field(min_length=1, max_length=80)
    observed_at: str = Field(min_length=1, max_length=80)
    geometry: dict
    properties: dict

    @field_validator("geometry")
    @classmethod
    def valid_geometry(cls, value):
        from shapely.geometry import shape

        geometry = shape(value)
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError("Geometry must be nonempty and valid.")
        if geometry.geom_type not in {"Point", "Polygon", "MultiPolygon"}:
            raise ValueError("Use Point, Polygon or MultiPolygon geometry.")
        if not all(math.isfinite(x) for x in geometry.bounds):
            raise ValueError("Geometry coordinates must be finite.")
        if not (
            -180 <= geometry.bounds[0] <= geometry.bounds[2] <= 180
            and -90 <= geometry.bounds[1] <= geometry.bounds[3] <= 90
        ):
            raise ValueError("Geometry must use WGS84 longitude/latitude.")
        return value

    @field_validator("properties")
    @classmethod
    def finite_properties(cls, value):
        import json

        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("Properties must be finite JSON values.") from exc
        return value
