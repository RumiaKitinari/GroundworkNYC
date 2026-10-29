"""Monthly scenario cash flows, not a trained sales or financing forecast."""
from economics import scenario
from menu_planning import bounded_number

PLAN_LIMITS = {"opening_cash": (0, 10000000, 100000), "startup_cost": (0, 10000000, 50000),
               "owner_draw": (0, 1000000, 0), "ramp_start_pct": (0, 100, 60),
               "ramp_months": (1, 12, 3), "months": (1, 24, 12)}
CHECKLIST_KEYS = {"property_visit", "permitted_use", "kitchen_ventilation", "permits_licenses", "funding", "cost_review"}


def planning_inputs(values):
    if not isinstance(values, dict) or set(values) - set(PLAN_LIMITS) - {"scenario_name"}:
        raise ValueError("Invalid business-plan assumptions.")
    result = {}
    for key, (low, high, default) in PLAN_LIMITS.items():
        number = bounded_number(values.get(key, default), key.replace("_", " ").title(), low, high)
        if key in {"ramp_months", "months"} and number != int(number):
            raise ValueError("Planning periods must be whole months.")
        result[key] = number
    name = values.get("scenario_name", "")
    if not isinstance(name, str) or len(name) > 60:
        raise ValueError("Invalid operating scenario name.")
    result["scenario_name"] = name
    return result


def cash_forecast(operating, assumptions):
    assessment = scenario(operating)
    inputs = assessment["inputs"]
    plan = planning_inputs(assumptions)
    opening = plan["opening_cash"] - plan["startup_cost"]
    months = int(plan["months"])
    series = []
    for label, multiplier in (("Lower Volume (-20%)", .8), ("Entered Volume", 1), ("Higher Volume (+20%)", 1.2)):
        balance = opening
        rows = [{"month": 0, "cash_balance": round(balance, 2)}]
        first_shortfall = 0 if balance < 0 else None
        minimum = balance
        capacity_capped = False
        for month in range(1, months + 1):
            ramp = 1 if plan["ramp_months"] == 1 else min(1, plan["ramp_start_pct"] / 100 +
                (1 - plan["ramp_start_pct"] / 100) * (month - 1) / (plan["ramp_months"] - 1))
            requested = inputs["daily_covers"] * multiplier * ramp
            covers = min(inputs["capacity"], requested)
            capacity_capped |= requested > inputs["capacity"]
            days = inputs["operating_days"]
            revenue = covers * inputs["price"] * days
            variable = days * (covers * inputs["unit_cost"] + inputs["congestion_cost"] * covers**2 / (2 * inputs["capacity"]))
            fixed = inputs["monthly_rent"] + inputs["monthly_fixed"]
            cash_out = variable + fixed + plan["owner_draw"]
            balance += revenue - cash_out
            minimum = min(minimum, balance)
            if balance < 0 and first_shortfall is None:
                first_shortfall = month
            rows.append({"month": month, "average_daily_covers": round(covers, 2),
                         "revenue": round(revenue, 2), "variable_cost": round(variable, 2),
                         "fixed_cost": round(fixed, 2), "owner_draw": plan["owner_draw"],
                         "cash_out": round(cash_out, 2), "net_cash_flow": round(revenue - cash_out, 2),
                         "cash_balance": round(balance, 2)})
        series.append({"label": label, "multiplier": multiplier, "rows": rows,
                       "ending_cash": round(balance, 2), "minimum_cash": round(minimum, 2),
                       "additional_cash_needed": round(max(0, -minimum), 2),
                       "first_shortfall_month": first_shortfall, "capacity_capped": capacity_capped})
    return {"inputs": inputs, "planning_inputs": plan, "opening_after_startup": round(opening, 2),
            "series": series, "break_even_covers": assessment["break_even_covers"],
            "assessment_type": "User-Assumed Monthly Cash Scenario", "demand_estimated_from_data": False,
            "assumptions": ["Cash is shown at month-end; intramonth payment timing is not modeled.",
                            "Volume changes do not imply measured demand or change guest spend.",
                            "Include debt service, taxes and later capital costs explicitly in your costs.",
                            "One-month ramp means full entered volume from month one."]}
