"""Bounded neighborhood Huff allocation; demand and capacity use comparable units."""

from __future__ import annotations

from collections import defaultdict
from math import isfinite

import h3

DEFAULT_WEIGHTS = {"residents": 1.0, "workers": 0.5, "transit_inflow": 0.1}


def compute_huff(cells, weights=None, radius=3, beta=2.0, outside_attractiveness=1.0):
    weights = DEFAULT_WEIGHTS if weights is None else weights
    if set(weights) != set(DEFAULT_WEIGHTS) or any(not isfinite(v) or v < 0 for v in weights.values()):
        raise ValueError("Provide finite nonnegative weights for residents, workers and transit_inflow.")
    if not isinstance(radius, int) or not 1 <= radius <= 10 or not isfinite(beta) or not 0 < beta <= 5:
        raise ValueError("Huff radius must be 1-10; distance decay must be in (0,5].")
    if not isfinite(outside_attractiveness) or outside_attractiveness <= 0:
        raise ValueError("Outside attractiveness must be positive.")
    by_id = {row["id"]: row for row in cells}
    if len(by_id) != len(cells) or not cells:
        raise ValueError("Provide nonempty unique H3 cells.")
    resolutions = {h3.get_resolution(cell) for cell in by_id}
    if len(resolutions) != 1:
        raise ValueError("Compute each H3 resolution separately.")
    resolution = resolutions.pop()
    edge_km = h3.average_hexagon_edge_length(resolution, unit="km")
    for row in cells:
        for name in (*weights, "capacity", "attractiveness"):
            value = row.get(name, 0)
            if not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
                raise ValueError(f"Invalid nonnegative metric: {name}")
        if row.get("capacity", 0) > 0 and row.get("attractiveness", 0) <= 0:
            raise ValueError("Supply with positive capacity requires positive attractiveness.")
    captured = defaultdict(float)
    results = {}
    for origin, row in by_id.items():
        demand = sum(row.get(key, 0) * value for key, value in weights.items())
        attractiveness = {}
        # H3 disk bounds the candidate lookup instead of a city-wide all-pairs matrix.
        for target in h3.grid_disk(origin, radius):
            supply = by_id.get(target)
            if not supply or supply.get("capacity", 0) <= 0:
                continue
            distance = max(
                edge_km / 2,
                h3.great_circle_distance(h3.cell_to_latlng(origin), h3.cell_to_latlng(target), unit="km"),
            )
            attractiveness[target] = supply.get("attractiveness", 0) / distance**beta
        total = outside_attractiveness + sum(attractiveness.values())
        outside_share = outside_attractiveness / total
        for target, value in attractiveness.items():
            captured[target] += demand * value / total
        results[origin] = {
            **row,
            "demand": demand,
            "outside_share": outside_share,
            "unserved_demand": demand * outside_share,
        }
    for target, row in results.items():
        assigned = captured[target]
        capacity = row.get("capacity", 0)
        row.update(
            captured_demand=assigned,
            capacity_pressure=assigned / capacity if capacity else None,
            excess_demand=max(0, assigned - capacity),
            score=round(100 * row["outside_share"], 2),
        )
    return list(results.values())
