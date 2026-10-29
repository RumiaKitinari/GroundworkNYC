r"""
Rank available locations for a restaurant concept.

Usage examples (Windows):
    python recommend.py --cuisine "Indian" --max-monthly-rent 9000 --min-sqft 1200
    python recommend.py --cuisine "Coffee / Tea" --chain --boroughs Brooklyn Queens --top 15
    python recommend.py --cuisine "Pizza" --transaction purchase --max-price 1500000
    python recommend.py --list-cuisines

Inputs (looked up in outputs\ first, then data\):
    synthetic_properties.csv     available locations (one row per listing)
    --snapshots                 dated, checksummed historical feature manifests
    hex_cuisine_scores.csv       output of make_heatmaps.py (cuisine competition)
    outputs\model\survival_model.json + model_meta.json   from train_survival.py

Scoring
    1. Hard filters remove listings that don't fit (rent, size, borough, ...).
       Rent is only a filter; it never changes the survival score.
    2. survival_3yr: the XGBoost model's chance that ANY restaurant with these
       details (chain or not) is still open after 3 years at this spot.
       It does not depend on cuisine.
    3. cuisine_gap (0-1): high when the surrounding 0.8-1.6 km is busy for the
       chosen cuisine (or related ones, via the matrix) but the listing's own
       spot is not. Empty areas and the middle of dense clusters both score low.
       Assumption: demand is where competition already is.
    4. score = w_survival * survival percentile + w_cuisine * cuisine_gap,
       plus small bonuses for features the user asked to prefer.

Output: outputs\recommendations\recommendations_<cuisine>.csv + a printed table.
"""
import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from features import (HISTORICAL_FEATURES, TEMPORAL_SCHEMA, build_historical_features,
                      load_historical_snapshots)
from paths import DATA, MODEL, RECOMMENDATIONS, ensure_dirs, find
from train_survival import survival_prob

CUISINES_50 = [
    "American", "Southern / Soul Food", "Cajun / Creole", "Italian", "French",
    "Spanish", "Portuguese", "Greek", "German / Central European", "Eastern European",
    "Mexican", "Peruvian", "Brazilian", "Colombian", "Venezuelan",
    "Cuban", "Dominican", "Puerto Rican", "Jamaican", "Haitian",
    "Ethiopian / Eritrean", "West African", "Indian", "Pakistani / Bangladeshi", "Chinese",
    "Japanese", "Korean", "Taiwanese", "Thai", "Vietnamese",
    "Filipino", "Indonesian / Malaysian", "Middle Eastern", "Mediterranean", "Turkish",
    "Persian / Iranian", "Steakhouse", "Seafood", "Barbecue", "Pizza",
    "Burgers", "Sandwiches / Deli", "Bakery / Pastries", "Coffee / Tea", "Desserts / Ice Cream",
    "Salads / Bowls", "Breakfast / Brunch", "Noodles", "Diner", "Health-Focused",
]


def match_cuisine(name):
    key = name.strip().lower()
    for c in CUISINES_50:
        if c.lower() == key or c.lower().split(" /")[0] == key:
            return c
    hits = [c for c in CUISINES_50 if key in c.lower()]
    if len(hits) == 1:
        return hits[0]
    raise SystemExit(f"Unknown cuisine '{name}'. Run with --list-cuisines to see options.")


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-dir", default=None, help="default: outputs\\model")
    ap.add_argument("--listings", default="synthetic_properties.csv")
    ap.add_argument("--snapshots", type=Path, action="append", help="Historical manifest; repeat for multiple vintages")
    ap.add_argument("--data-dir", type=Path, default=DATA)
    ap.add_argument("--prediction-date", default=date.today().isoformat())
    ap.add_argument("--cuisine-scores", default="hex_cuisine_scores.csv")
    ap.add_argument("--list-cuisines", action="store_true")
    ap.add_argument("--access-run", type=Path, help="Pinned customer-access feature bundle; optional")
    ap.add_argument("--w-access", type=float, default=0, help="Experimental access blend in [0,1]; default preserves 60/40 ranking")
    ap.add_argument("--service-style", choices=["quick_service", "casual", "fine_dining"], default="casual")
    ap.add_argument("--average-check", type=float, default=35)
    ap.add_argument("--audience", choices=["residents", "workers", "destination"], default="residents")
    ap.add_argument("--daypart", choices=["all_day", "morning", "lunch", "evening"], default="all_day")

    g = ap.add_argument_group("restaurant concept")
    g.add_argument("--cuisine", help='one of the 50 cuisines, e.g. "Indian" or "Coffee / Tea"')
    g.add_argument("--chain", action="store_true", help="concept is a chain / franchise (5+ locations)")

    g = ap.add_argument_group("filters (listings that fail are removed)")
    g.add_argument("--transaction", choices=["lease", "purchase", "any"], default="lease")
    g.add_argument("--max-monthly-rent", type=float)
    g.add_argument("--max-rent-psf", type=float, help="max annual rent per sq ft")
    g.add_argument("--max-price", type=float, help="max purchase price")
    g.add_argument("--min-sqft", type=float)
    g.add_argument("--max-sqft", type=float)
    g.add_argument("--boroughs", nargs="+", help="e.g. --boroughs Bronx Queens")
    g.add_argument("--ground-floor-only", action="store_true")
    g.add_argument("--require-food-use", action="store_true",
                   help="only spaces previously used for food (existing fit-out)")

    g = ap.add_argument_group("preferences (small score bonuses)")
    g.add_argument("--prefer-food-use", action="store_true", help="+0.05 for former food spaces")
    g.add_argument("--prefer-outdoor", action="store_true", help="+0.03 for possible sidewalk seating")
    g.add_argument("--prefer-corner", action="store_true", help="+0.03 for corner units")

    g = ap.add_argument_group("weights")
    g.add_argument("--w-survival", type=float, default=0.6)
    g.add_argument("--w-cuisine", type=float, default=0.4)
    g.add_argument("--top", type=int, default=20)
    return ap.parse_args()


def apply_filters(L, a):
    keep = pd.Series(True, index=L.index)
    if a.transaction != "any":
        keep &= L["transaction"].eq(a.transaction)
    if a.max_monthly_rent is not None:
        keep &= L["monthly_rent"].le(a.max_monthly_rent) | L["transaction"].eq("purchase")
    if a.max_rent_psf is not None:
        keep &= L["annual_rent_psf"].le(a.max_rent_psf) | L["transaction"].eq("purchase")
    if a.max_price is not None:
        keep &= L["asking_price"].le(a.max_price) | L["transaction"].eq("lease")
    if a.min_sqft is not None:
        keep &= L["available_sqft"].ge(a.min_sqft)
    if a.max_sqft is not None:
        keep &= L["available_sqft"].le(a.max_sqft)
    if a.boroughs:
        keep &= L["borough"].str.lower().isin([b.lower() for b in a.boroughs])
    if a.ground_floor_only:
        keep &= L["ground_floor"].astype(str).str.lower().eq("true")
    if a.require_food_use:
        keep &= L["former_food_use"].astype(str).str.lower().eq("true")
    return L[keep].copy()


def cuisine_gap(L, cuisine, scores_path):
    """Gap score and local competition for this cuisine in each listing's res-9 hex.
    gap_score is high where the surrounding area is busy for the cuisine (demand)
    but the listing's own spot is not (supply). See make_heatmaps.py."""
    import h3
    if not scores_path.exists():
        print(f"  ! {scores_path.name} not found; cuisine gap set to 0. "
              "Run make_heatmaps.py first.")
        return np.zeros(len(L)), np.zeros(len(L)), np.zeros(len(L))
    s = pd.read_csv(scores_path, usecols=["hex", "cuisine", "gap_score",
                                          "local_competition", "area_competition"])
    s = s[s["cuisine"] == cuisine].set_index("hex")
    hexes = [h3.latlng_to_cell(la, lo, 9) for la, lo in zip(L["latitude"], L["longitude"])]
    s = s.reindex(hexes).fillna(0.0)
    return s["gap_score"].values, s["local_competition"].values, s["area_competition"].values


def main():
    a = parse_args()
    if a.list_cuisines:
        print("\n".join(CUISINES_50))
        return
    if not a.cuisine:
        raise SystemExit("Give a cuisine with --cuisine (or --list-cuisines).")
    cuisine = match_cuisine(a.cuisine)
    if not np.isfinite(a.w_access) or not 0 <= a.w_access <= 1 or (a.w_access and not a.access_run):
        raise SystemExit("Use --w-access in [0,1], with --access-run when nonzero.")

    ensure_dirs()
    model_dir = Path(a.model_dir) if a.model_dir else MODEL
    meta = json.loads((model_dir / "model_meta.json").read_text())
    validate_temporal_model(meta, a.prediction_date)
    if not a.snapshots:
        raise SystemExit("Temporal scoring requires --snapshots; current-master fallback is disabled.")
    model = xgb.Booster()
    model.load_model(str(model_dir / "survival_model.json"))

    listings = pd.read_csv(find(a.listings))

    L = apply_filters(listings, a)
    print(f"{len(L)} of {len(listings)} listings pass the filters.")
    if L.empty:
        return

    # ---- Survival (location + concept details, no cuisine) -----------------
    snapshots = load_historical_snapshots(a.snapshots, a.data_dir, a.prediction_date)
    L["geoid"] = L["geoid"].astype(str)
    L["open_date"] = a.prediction_date
    historical, provenance = build_historical_features(L, snapshots)
    L[list(HISTORICAL_FEATURES)] = historical
    L = L[historical.notna().any(axis=1)].copy()
    if L.empty:
        raise SystemExit("No eligible listings have historically available features.")
    if a.chain:
        print("Chain status is excluded from this temporal model; --chain does not affect survival.")
    L["competitors_400m_at_open"] = np.nan  # unavailable, not a fabricated zero
    X = L[meta["features"]].astype(float).values
    pred = model.predict(xgb.DMatrix(X, feature_names=meta["features"]))
    L["survival_3yr"] = survival_prob(pred, meta["horizon_years"], meta["aft_scale"])

    # Compare each listing with the others in its borough (helps the Bronx,
    # Staten Island etc. instead of always ranking Manhattan first)
    L["survival_vs_borough"] = L["survival_3yr"] - L.groupby("borough")["survival_3yr"].transform("median")

    # ---- Cuisine gap ---------------------------------------------------------
    # Demand is assumed to be where the cuisine already competes. The best spots
    # are quiet pockets inside or between busy areas, not empty areas.
    L["cuisine_gap"], L["cuisine_here"], L["cuisine_nearby_area"] = cuisine_gap(
        L, cuisine, find(a.cuisine_scores))

    # ---- Final score -------------------------------------------------------
    score = a.w_survival * L["survival_3yr"].rank(pct=True) + a.w_cuisine * L["cuisine_gap"]
    if a.access_run:
        from customer_access import AccessConcept, score_cached_run
        concept = AccessConcept(a.service_style, a.average_check, a.audience, a.daypart)
        access = score_cached_run(a.access_run, concept, L, a.prediction_date)
        L["inverse_walkability_percentile"] = access.inverse_walkability_percentile
        L["customer_access_coverage"] = access.routing_mass_coverage
        if a.w_access:
            supported = L.inverse_walkability_percentile.notna()
            print(f"Customer-access blend: excluding {int((~supported).sum())} insufficient-coverage candidates.")
            L = L[supported].copy()
            score = (1 - a.w_access) * score[supported] + a.w_access * L.inverse_walkability_percentile / 100
            if L.empty:
                raise SystemExit("No candidates have sufficient customer-access coverage.")
    is_true = lambda c: L[c].astype(str).str.lower().eq("true")
    if a.prefer_food_use:
        score += 0.05 * is_true("former_food_use")
    if a.prefer_corner:
        score += 0.03 * is_true("corner_position")
    if a.prefer_outdoor:
        score += 0.03 * L["outdoor_space_potential"].str.startswith("Potential")
    L["score"] = score.round(4)
    L = L.sort_values("score", ascending=False)

    cols = ["property_id", "borough", "neighborhood", "transaction", "available_sqft",
            "monthly_rent", "annual_rent_psf", "asking_price", "former_food_use",
            "corner_position", "survival_3yr", "survival_vs_borough",
            "competitors_400m_at_open", "cuisine_here", "cuisine_nearby_area", "cuisine_gap", "score",
            "latitude", "longitude", "geoid"]
    if a.access_run:
        cols += ["inverse_walkability_percentile", "customer_access_coverage"]
    out = L[cols].rename(columns={"competitors_400m_at_open": "restaurants_within_400m"})
    fname = f"recommendations_{cuisine.split(' /')[0].replace(' ', '_').lower()}.csv"
    fname = RECOMMENDATIONS / fname
    out.to_csv(fname, index=False)
    pd.DataFrame(provenance).to_csv(fname.with_suffix(".feature_provenance.csv"), index=False)

    show = out.head(a.top).copy()
    show["survival_3yr"] = (show["survival_3yr"] * 100).round(1).astype(str) + "%"
    show["survival_vs_borough"] = (show["survival_vs_borough"] * 100).round(1).map("{:+.1f} pts".format)
    show["cuisine_gap"] = show["cuisine_gap"].round(2)
    show["monthly_rent"] = show["monthly_rent"].map(lambda v: "" if pd.isna(v) else f"${v:,.0f}")
    pd.set_option("display.width", 200)
    print(f"\nTop {len(show)} locations for: {cuisine}"
          f"{' (chain)' if a.chain else ' (independent)'}\n")
    print(show[["property_id", "borough", "neighborhood", "available_sqft", "monthly_rent",
                "survival_3yr", "survival_vs_borough", "cuisine_gap", "score"]].to_string(index=False))
    print(f"\nFull ranked list saved to {fname}")
    print("Note: synthetic listings are scenarios, not real availability.")
    print("Survival estimates are research-only and depend on verified outcome evidence and AFT assumptions.")


def validate_temporal_model(meta, prediction_date):
    if meta.get("schema") != TEMPORAL_SCHEMA or meta.get("features") != list(HISTORICAL_FEATURES):
        raise ValueError("Legacy/current-context survival model rejected; retrain using dated evidence.")
    day = date.fromisoformat(prediction_date)
    if not date.fromisoformat(meta["trained_as_of"]) <= day <= date.today():
        raise ValueError("Prediction date must be on/after model training as-of and not in the future")


if __name__ == "__main__":
    main()
