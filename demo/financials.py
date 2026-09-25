"""User-supplied operating scenario, separate from measured location evidence."""

from math import ceil
from scoring import number


def operating_scenario(args, rent_target, guest_spend, deal_type):
    base = {"rent_target": rent_target, "purchase_budget": args.get("purchase_budget"),
            "deal_type": deal_type, "guest_spend": guest_spend, "status": "incomplete",
            "required_monthly_sales": None, "required_covers_per_day": None}
    if deal_type == "purchase":
        base["status"] = "not_applicable"
        return base
    fixed_raw = args.get("other_fixed_costs", "")
    variable_raw = args.get("variable_cost_pct", "")
    days_raw = args.get("operating_days", "")
    if fixed_raw == "" or variable_raw == "" or days_raw == "":
        base["missing_inputs"] = [name for name, value in (("other_fixed_costs", fixed_raw),
                                  ("variable_cost_pct", variable_raw), ("operating_days", days_raw)) if value == ""]
        return base
    fixed, variable, days = number(fixed_raw), number(variable_raw), number(days_raw)
    if fixed is None or not 0 <= fixed <= 2_000_000:
        raise ValueError("Other monthly fixed costs must be between $0 and $2 million.")
    if variable is None or not 0 <= variable < 95:
        raise ValueError("Variable costs must be at least 0% and below 95%.")
    if days is None or not 1 <= days <= 31 or not float(days).is_integer():
        raise ValueError("Operating days must be a whole number from 1 to 31.")
    contribution = guest_spend * (1 - variable / 100)
    monthly_costs = rent_target + fixed
    base.update({"status": "ready", "other_fixed_costs": fixed,
                 "variable_cost_pct": variable, "operating_days": int(days),
                 "required_monthly_sales": ceil(monthly_costs / (1 - variable / 100)),
                 "required_covers_per_day": ceil(monthly_costs / contribution / days),
                 "basis": "User-entered costs and guest spend; excludes debt service, taxes, and unentered costs."})
    return base
