import h3
import pytest

from groundwork_backend.huff import compute_huff


def cells():
    center = h3.latlng_to_cell(40.75, -73.97, 8)
    neighbor = next(cell for cell in h3.grid_disk(center, 1) if cell != center)
    return [
        {
            "id": center,
            "residents": 100,
            "workers": 20,
            "transit_inflow": 10,
            "capacity": 50,
            "attractiveness": 1,
        },
        {
            "id": neighbor,
            "residents": 80,
            "workers": 10,
            "transit_inflow": 0,
            "capacity": 10,
            "attractiveness": 0.2,
        },
    ]


def test_mass_conservation_and_outside_option():
    rows = compute_huff(cells())
    assert sum(row["captured_demand"] + row["unserved_demand"] for row in rows) == pytest.approx(
        sum(row["demand"] for row in rows)
    )
    assert all(0 < row["outside_share"] < 1 for row in rows)


def test_no_supply_leaves_all_demand_unserved():
    rows = [{**row, "capacity": 0, "attractiveness": 0} for row in cells()]
    for row in compute_huff(rows):
        assert row["unserved_demand"] == row["demand"]
        assert row["score"] == 100
        assert row["capacity_pressure"] is None


def test_greater_attractiveness_reduces_unserved_demand():
    before = compute_huff(cells())
    after = compute_huff([{**row, "attractiveness": row["attractiveness"] * 5} for row in cells()])
    assert sum(row["unserved_demand"] for row in after) < sum(row["unserved_demand"] for row in before)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"radius": 100},
        {"beta": 0},
        {"outside_attractiveness": 0},
        {"weights": {"residents": -1, "workers": 0, "transit_inflow": 0}},
    ],
)
def test_invalid_model_parameters(kwargs):
    with pytest.raises(ValueError):
        compute_huff(cells(), **kwargs)


def test_duplicate_or_invalid_features():
    with pytest.raises(ValueError):
        compute_huff(cells() * 2)
    with pytest.raises(ValueError):
        compute_huff([{**row, "workers": float("nan")} for row in cells()])
