import math
import pytest
from economics import scenario


BASE = dict(monthly_rent=2600, monthly_fixed=0, operating_days=26, price=20,
            unit_cost=8, daily_covers=100, capacity=200, elasticity=2,
            congestion_cost=0, profit_target=500)


def test_break_even_profit_and_interior_mr_mc():
    result = scenario(BASE)
    assert result["current_daily_profit"] == 1100
    assert result["break_even_covers"] == 9
    assert result["target_profit_covers"] == 50
    assert result["modeled_optimum"] == dict(covers=110., price=19., daily_profit=1110., capacity_binding=False)
    assert not result["demand_estimated_from_data"]


def test_optimum_matches_dense_bounded_search_with_capacity_costs():
    for premium in (0, 8, 40):
        result = scenario({**BASE, "congestion_cost": premium})
        best = result["modeled_optimum"]
        brute = max((30-.1*q)*q - (100+8*q+premium*q*q/400)
                    for q in (index/100 for index in range(20001)))
        assert abs(best["daily_profit"]-brute) < .02
        assert best["daily_profit"] >= result["current_daily_profit"]-.01


def test_infeasible_break_even_and_zero_output_remain_losses():
    result = scenario({**BASE, "unit_cost": 40})
    assert result["break_even_covers"] is None
    assert result["modeled_optimum"]["covers"] == 0
    assert result["modeled_optimum"]["daily_profit"] == -100
    result = scenario({**BASE, "monthly_fixed": 1000000})
    assert result["break_even_covers"] is None
    assert result["target_profit_covers"] is None


@pytest.mark.parametrize("patch", [{"price":math.nan},{"capacity":0},{"daily_covers":201},
                                  {"elasticity":0},{"operating_days":26.5},{"price":True}])
def test_invalid_inputs_rejected(patch):
    with pytest.raises(ValueError):
        scenario({**BASE, **patch})


def test_endpoint_validates_and_returns_scenario_not_forecast():
    from app import app
    client = app.test_client()
    response = client.get("/api/economics/scenario", query_string=BASE)
    assert response.status_code == 200
    assert not response.json["demand_estimated_from_data"]
    assert client.get("/api/economics/scenario").status_code == 400
