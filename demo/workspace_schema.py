"""Bounded, backward-compatible account planning payloads."""
from economics import scenario


def valid_plans(plans):
    if not isinstance(plans, dict) or len(plans) > 50:
        return False
    for key, plan in plans.items():
        if not isinstance(key, str) or len(key) > 500 or not isinstance(plan, dict):
            return False
        if set(plan) - {"property_ids", "selected_property_id", "draft", "scenarios", "basket", "menu_details"}:
            return False
        ids = plan.get("property_ids", [])
        if (not isinstance(ids, list) or len(ids) > 4
                or any(not isinstance(value, str) or len(value) > 120 for value in ids)):
            return False
        selected = plan.get("selected_property_id", "")
        if not isinstance(selected, str) or len(selected) > 120:
            return False
        scenarios = plan.get("scenarios", {})
        if not isinstance(scenarios, dict) or len(scenarios) > 12 or any(not isinstance(name, str) or not 1 <= len(name) <= 60 for name in scenarios):
            return False
        fields = {"monthly_rent", "monthly_fixed", "operating_days", "price", "unit_cost", "daily_covers", "capacity", "elasticity", "congestion_cost", "profit_target"}
        for draft in [plan.get("draft", {}), *scenarios.values()]:
            if not isinstance(draft, dict):
                return False
            if draft:
                if set(draft) != fields or any(not isinstance(value, (str, int, float)) or isinstance(value, bool) or len(str(value)) > 30 for value in draft.values()):
                    return False
                try:
                    scenario(draft)
                except (ValueError, TypeError, KeyError, OverflowError):
                    return False
        if any(not draft for draft in scenarios.values()):
            return False
        basket = plan.get("basket", {})
        if not isinstance(basket, dict) or len(basket) > 100:
            return False
        if any(not isinstance(item, str) or len(item) > 120 or not isinstance(qty, int) or isinstance(qty, bool) or not 0 <= qty <= 10 for item, qty in basket.items()):
            return False
        details = plan.get("menu_details", {})
        if not isinstance(details, dict) or len(details) > 100:
            return False
        for item, detail in details.items():
            if not isinstance(item, str) or len(item) > 120 or not isinstance(detail, dict) or set(detail) - {"ingredients", "complexity"}:
                return False
            if not isinstance(detail.get("ingredients", ""), str) or len(detail.get("ingredients", "")) > 300:
                return False
            if detail.get("complexity", "standard") not in {"simple", "standard", "complex"}:
                return False
    return True
