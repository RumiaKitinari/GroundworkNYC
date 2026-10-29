"""Recipe costing from explicit purchase quantities; no inferred ingredient prices."""
from math import fsum, isfinite


def bounded_number(value, name, low, high):
    try:
        number = float("nan") if isinstance(value, bool) else float(value)
    except (ValueError, TypeError):
        raise ValueError(f"Enter a valid {name}.") from None
    if not isfinite(number) or not low <= number <= high:
        raise ValueError(f"{name} must be between {low} and {high}.")
    return number


def recipe_cost(recipe):
    if not isinstance(recipe, dict) or set(recipe) != {"portions", "waste_pct", "lines"}:
        raise ValueError("Enter recipe portions, waste allowance and ingredients.")
    portions = bounded_number(recipe["portions"], "Portions", 1, 2000)
    waste = bounded_number(recipe["waste_pct"], "Waste Percentage", 0, 50)
    if portions != int(portions):
        raise ValueError("Portions must be a whole number.")
    lines = recipe["lines"]
    if not isinstance(lines, list) or not 1 <= len(lines) <= 30:
        raise ValueError("A recipe needs 1-30 ingredient lines.")
    costs = []
    for line in lines:
        if not isinstance(line, dict) or set(line) != {"name", "quantity", "unit", "unit_cost"}:
            raise ValueError("Invalid ingredient line.")
        for field, limit in (("name", 80), ("unit", 20)):
            if not isinstance(line[field], str) or not 1 <= len(line[field].strip()) <= limit:
                raise ValueError(f"Enter an ingredient {field}.")
        quantity = bounded_number(line["quantity"], "Quantity", .001, 1000000)
        unit_cost = bounded_number(line["unit_cost"], "Unit Cost", 0, 10000)
        costs.append(quantity * unit_cost)
    purchase_cost = fsum(costs)
    batch_cost = purchase_cost / (1 - waste / 100)
    per_portion = batch_cost / portions
    if per_portion > 1000:
        raise ValueError("Ingredient cost per portion exceeds $1,000. Check quantities and yield.")
    return {"purchase_cost": round(purchase_cost, 2), "batch_cost": round(batch_cost, 2),
            "cost_per_portion": round(per_portion, 2), "portions": int(portions),
            "waste_pct": waste, "assessment_type": "User-Entered Recipe Cost",
            "excludes": ["Labor", "Rent", "Utilities", "Packaging", "Tax"]}
