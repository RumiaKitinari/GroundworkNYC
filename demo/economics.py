"""Deterministic operating scenarios; demand is assumed, never inferred."""
from math import ceil, isfinite, sqrt


def scenario(args):
    limits = {"monthly_rent": (0, 1000000), "monthly_fixed": (0, 2000000),
              "operating_days": (1, 31), "price": (1, 1000), "unit_cost": (0, 1000),
              "daily_covers": (1, 5000), "capacity": (1, 5000),
              "elasticity": (.1, 10), "congestion_cost": (0, 1000), "profit_target": (0, 100000)}
    values = {}
    for name, (low, high) in limits.items():
        raw = args.get(name)
        try:
            if isinstance(raw, bool):
                raise ValueError
            value = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"Enter a valid {name.replace('_', ' ')}.") from None
        if not isfinite(value) or not low <= value <= high:
            raise ValueError(f"{name.replace('_', ' ').title()} must be between {low} and {high}.")
        values[name] = value
    v = values
    for name in ("operating_days", "capacity", "daily_covers"):
        if v[name] != int(v[name]):
            raise ValueError(f"{name.replace('_', ' ').title()} must be a whole number.")
    if v["daily_covers"] > v["capacity"]:
        raise ValueError("Expected daily covers cannot exceed daily capacity.")
    p, q0, capacity = v["price"], v["daily_covers"], v["capacity"]
    fixed = (v["monthly_rent"] + v["monthly_fixed"]) / v["operating_days"]
    unit, curvature = v["unit_cost"], v["congestion_cost"] / (2 * capacity)
    intercept = p * (1 + 1 / v["elasticity"])
    slope = p / (v["elasticity"] * q0)

    def cost(q):
        return fixed + unit * q + curvature * q * q

    def target_volume(target):
        margin = p - unit
        if margin <= 0:
            return None
        if curvature == 0:
            root = (fixed + target) / margin
        else:
            discriminant = margin * margin - 4 * curvature * (fixed + target)
            if discriminant < 0:
                return None
            root = 2 * (fixed + target) / (margin + sqrt(discriminant))
        covers = max(0, ceil(root - 1e-10))
        if covers > capacity or p * covers - cost(covers) < target - 1e-7:
            return None
        return covers

    # Concave revenue and convex costs give a bounded global scenario optimum.
    q_star = max(0, min(capacity, (intercept - unit) / (2 * (slope + curvature))))
    p_star = max(0, intercept - slope * q_star)
    current_profit = p * q0 - cost(q0)
    curves = []
    for index in range(101):
        q = capacity * index / 100
        price = max(0, intercept - slope * q)
        curves.append({"covers": round(q, 4), "revenue": round(p * q, 2),
                       "total_cost": round(cost(q), 2), "profit": round(p * q - cost(q), 2),
                       "demand_price": round(price, 2), "marginal_revenue": round(intercept - 2 * slope * q, 2),
                       "marginal_cost": round(unit + 2 * curvature * q, 2)})
    price_curve = []
    for index in range(101):
        price = intercept * index / 100
        covers = max(0, min(capacity, (intercept - price) / slope))
        price_curve.append({"price": round(price, 4), "covers": round(covers, 4),
                            "profit": round(price * covers - cost(covers), 2)})
    return {"inputs": values, "assessment_type": "User-Assumed Operating Scenario",
            "demand_estimated_from_data": False, "fixed_cost_per_day": round(fixed, 2),
            "current_daily_profit": round(current_profit, 2), "current_daily_sales": round(p * q0, 2),
            "break_even_covers": target_volume(0), "target_profit_covers": target_volume(v["profit_target"]),
            "capacity_utilization": round(q0 / capacity, 4),
            "modeled_optimum": {"covers": round(q_star, 2), "price": round(p_star, 2),
                                "daily_profit": round(p_star * q_star - cost(q_star), 2),
                                "capacity_binding": q_star >= capacity - 1e-8},
            "volume_curve": curves, "price_curve": price_curve,
            "assumptions": ["Linear demand anchored to entered price and daily covers; elasticity is a user assumption.",
                            "Variable cost is per cover; congestion adds a convex cost at higher volume.",
                            "Rent and fixed costs continue at zero covers; profit excludes unentered costs and financing.",
                            "The mathematical optimum is conditional on these assumptions, not a sales or profit forecast."]}
