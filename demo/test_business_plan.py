import pytest
from business_plan import cash_forecast, planning_inputs
from test_economics import BASE


def test_monthly_accounting_and_no_double_counted_rent():
    result = cash_forecast(BASE, {"opening_cash": 10000, "startup_cost": 2000,
                                "owner_draw": 500, "ramp_months": 1, "months": 6})
    entered = result["series"][1]
    row = entered["rows"][1]
    assert row["revenue"] == 52000
    assert row["variable_cost"] == 20800
    assert row["fixed_cost"] == 2600
    assert row["cash_out"] == 23900
    assert row["net_cash_flow"] == 28100
    assert row["cash_balance"] == 36100
    assert entered["ending_cash"] == 8000 + 6 * 28100
    assert entered["first_shortfall_month"] is None
    assert not result["demand_estimated_from_data"]


def test_ramp_and_capacity_are_explicit():
    result = cash_forecast({**BASE, "capacity": 100}, {"ramp_start_pct": 50, "ramp_months": 3, "months": 4})
    assert [row["average_daily_covers"] for row in result["series"][1]["rows"][1:]] == [50, 75, 100, 100]
    assert result["series"][2]["capacity_capped"]
    assert max(row["average_daily_covers"] for row in result["series"][2]["rows"][1:]) == 100


def test_shortfall_includes_opening_and_later_cash_losses():
    result = cash_forecast({**BASE, "unit_cost": 40}, {"opening_cash": 1000, "startup_cost": 2000, "months": 2})
    entered = result["series"][1]
    assert entered["first_shortfall_month"] == 0
    assert entered["additional_cash_needed"] == -entered["minimum_cash"]
    assert entered["additional_cash_needed"] > 1000


@pytest.mark.parametrize("values", [{"months": 0}, {"months": 2.5}, {"opening_cash": -1},
                                   {"ramp_start_pct": 101}, {"ramp_months": True},
                                   {"startup_cost": float("nan")}, {"scenario_name": []}, {"unknown": 3}])
def test_plan_inputs_reject_invalid_values(values):
    with pytest.raises(ValueError):
        planning_inputs(values)


def test_forecast_api_requires_explicit_valid_operating_assumptions():
    from app import app
    client = app.test_client()
    result = client.post("/api/planning/forecast", json={"operating": BASE, "assumptions": {}})
    assert result.status_code == 200
    assert not result.json["demand_estimated_from_data"]
    for payload in (None, {}, {"operating": {}, "assumptions": {}}, {"operating": BASE, "assumptions": []}):
        assert client.post("/api/planning/forecast", json=payload).status_code == 400
