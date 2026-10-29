from copy import deepcopy

import pytest
from menu_planning import recipe_cost

RECIPE = {"portions": 10, "waste_pct": 20, "lines": [
    {"name": "Rice", "quantity": 2, "unit": "kg", "unit_cost": 4},
    {"name": "Vegetables", "quantity": 3, "unit": "kg", "unit_cost": 8}]}


def test_batch_yield_and_waste_accounting():
    result = recipe_cost(RECIPE)
    assert result["purchase_cost"] == 32
    assert result["batch_cost"] == 40
    assert result["cost_per_portion"] == 4
    assert "Labor" in result["excludes"]
    assert recipe_cost({**RECIPE, "waste_pct": 0})["cost_per_portion"] == 3.2


@pytest.mark.parametrize("patch", [{"portions": 0}, {"portions": 1.5}, {"waste_pct": 51},
                                  {"lines": []}, {"lines": RECIPE["lines"] * 16},
                                  {"waste_pct": True}, {"portions": float("inf")}])
def test_invalid_recipes_rejected(patch):
    with pytest.raises(ValueError):
        recipe_cost({**RECIPE, **patch})


@pytest.mark.parametrize("patch", [{"name": " "}, {"unit": ""}, {"quantity": -1},
                                  {"unit_cost": float("nan")}, {"extra": "field"}])
def test_invalid_ingredients_rejected(patch):
    recipe = deepcopy(RECIPE)
    recipe["lines"][0].update(patch)
    with pytest.raises(ValueError):
        recipe_cost(recipe)


def test_recipe_api_and_payload_limits():
    from app import app
    client = app.test_client()
    response = client.post("/api/menu/recipe-cost", json=RECIPE)
    assert response.status_code == 200
    assert response.json["cost_per_portion"] == 4
    assert client.post("/api/menu/recipe-cost", json=None).status_code == 400
    assert client.post("/api/menu/recipe-cost", json={**RECIPE, "owner": "other"}).status_code == 400
