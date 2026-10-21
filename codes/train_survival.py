r"""
Train the XGBoost restaurant survival model (location only, no cuisine).

Usage (Windows, from the folder with these scripts):
    python train_survival.py

Reads (outputs\ first, then data\):
    master_tract_features.csv    one row per census tract
    restaurant_lifespans.csv     one row per restaurant (open / close dates)

Writes to outputs\model\:
    survival_model.json          trained XGBoost model
    model_meta.json              feature list, AFT scale, reference year
    tract_survival_scores.csv    3-year survival for an independent restaurant in each tract
    cv_report.txt                spatial cross-validation results, overall and by borough
    feature_importance.csv       gain importance per feature

How it works
    1. Each row is one restaurant opened after Nov 2020 (clean cohort).
    2. Features = its tract's features + neighbour averages + restaurant
       details (chain or not, competitors within 400 m on its opening day,
       opening year).
    3. Target = survival time as an interval: open until the last snapshot
       that lists it, closed by the next snapshot (or still open = censored).
       XGBoost's survival:aft objective handles both.
    4. Rows are weighted so each tract-income quintile counts equally,
       so high-income Manhattan tracts do not dominate.
    5. 5-fold cross-validation grouped by neighbourhood (NTA), so the model
       is always tested on neighbourhoods it never saw.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from scipy.stats import norm
from sklearn.model_selection import GroupKFold

from paths import MODEL, ensure_dirs, find
from features import (CompetitionIndex, build_tract_features, chain_names,
                      model_columns, nearest_tract)

HORIZON_YEARS = 3.0
AFT_SCALE = 1.0
PARAMS = {
    "objective": "survival:aft",
    "eval_metric": "aft-nloglik",
    "aft_loss_distribution": "normal",
    "aft_loss_distribution_scale": AFT_SCALE,
    "tree_method": "hist",
    "learning_rate": 0.03,
    "max_depth": 5,
    "min_child_weight": 25,
    "subsample": 0.8,
    "colsample_bytree": 0.7,
    "lambda": 2.0,
    "seed": 440,
}
MAX_ROUNDS = 2000
EARLY_STOP = 100


# --------------------------------------------------------------------------
def survival_prob(pred_time, horizon=HORIZON_YEARS, scale=AFT_SCALE):
    """P(still open at `horizon` years) from AFT predicted median time."""
    mu = np.log(np.clip(pred_time, 1e-6, None))
    return 1 - norm.cdf((np.log(horizon) - mu) / scale)


def concordance(pred_time, lower, upper, n_pairs=300_000, seed=0):
    """Harrell's C-index estimated on random pairs.
    A pair counts when one restaurant clearly closed before the other was
    last seen open; 1.0 = perfect ranking, 0.5 = random."""
    rng = np.random.default_rng(seed)
    n = len(pred_time)
    if n < 10:
        return np.nan
    i, j = rng.integers(0, n, n_pairs), rng.integers(0, n, n_pairs)
    closed_i = np.isfinite(upper[i])
    usable = closed_i & (upper[i] <= lower[j])
    if usable.sum() == 0:
        return np.nan
    pi, pj = pred_time[i][usable], pred_time[j][usable]
    return float(((pi < pj) + 0.5 * (pi == pj)).mean())


# --------------------------------------------------------------------------
def build_training_rows(life, tract_feats, master):
    latest = pd.to_datetime(life["last_snapshot"]).max()
    life = life.copy()
    for c in ["open_date", "close_date", "last_snapshot"]:
        life[c] = pd.to_datetime(life[c], errors="coerce")

    comp = CompetitionIndex(life, latest)
    chains = chain_names(life)

    r = life[life["clean_cohort"].astype(str).str.lower().eq("true")].copy()
    r = r.dropna(subset=["lat", "lon", "open_date"])
    r = r[r["lat"].between(40.4, 41.0)]
    print(f"Training restaurants (opened after Nov 2020): {len(r):,}")

    # Target interval in years
    lower = (r["last_snapshot"] - r["open_date"]).dt.days / 365.25
    upper = lower + r["close_window_days"].fillna(0) / 365.25
    closed = r["closed"].astype(str).str.lower().eq("true")
    r["y_lower"] = lower.clip(lower=1 / 365.25)
    r["y_upper"] = np.where(closed, upper.clip(lower=2 / 365.25), np.inf)

    # Restaurant-level features
    r["is_chain"] = r["dba"].str.upper().str.strip().isin(chains).astype(int)
    print("Counting competitors within 400 m at each opening date...")
    r["competitors_400m_at_open"] = [
        comp.count(la, lo, d, exclude_camis=c)
        for la, lo, d, c in zip(r["lat"], r["lon"], r["open_date"], r["camis"])]
    r["open_year"] = r["open_date"].dt.year

    # Attach tract features
    r["geoid"] = nearest_tract(r["lat"].values, r["lon"].values, master)
    r = r.join(tract_feats, on="geoid")
    return r, latest


def income_weights(rows):
    q = pd.qcut(rows["median_household_income"].rank(method="first"), 5, labels=False)
    w = 1.0 / q.map(q.value_counts())
    return (w * len(w) / w.sum()).values


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", default=None, help="path; default data\\master_tract_features.csv")
    ap.add_argument("--lifespans", default=None, help="path; default restaurant_lifespans.csv")
    ap.add_argument("--out-dir", default=None, help="default outputs\\model")
    a = ap.parse_args()

    ensure_dirs()
    out = Path(a.out_dir) if a.out_dir else MODEL
    out.mkdir(parents=True, exist_ok=True)
    master_path = Path(a.master) if a.master else find("master_tract_features.csv")
    life_path = Path(a.lifespans) if a.lifespans else find("restaurant_lifespans.csv")
    print(f"Master:    {master_path}\nLifespans: {life_path}")

    master = pd.read_csv(master_path, low_memory=False)
    life = pd.read_csv(life_path, low_memory=False)
    tract_feats = build_tract_features(master)
    restaurant_cols = ["is_chain", "competitors_400m_at_open", "open_year"]
    feat_cols = model_columns(tract_feats) + restaurant_cols

    rows, latest = build_training_rows(life, tract_feats, master)
    X = rows[feat_cols].astype(float).values
    lo, hi = rows["y_lower"].values, rows["y_upper"].values
    w = income_weights(rows)
    groups = rows["nta_code"].fillna("NA").values

    # ---- Spatial cross-validation -----------------------------------------
    oof = np.full(len(rows), np.nan)
    best_rounds = []
    for k, (tr, te) in enumerate(GroupKFold(n_splits=5).split(X, groups=groups)):
        dtr = xgb.DMatrix(X[tr], weight=w[tr], feature_names=feat_cols)
        dtr.set_float_info("label_lower_bound", lo[tr])
        dtr.set_float_info("label_upper_bound", hi[tr])
        dte = xgb.DMatrix(X[te], weight=w[te], feature_names=feat_cols)
        dte.set_float_info("label_lower_bound", lo[te])
        dte.set_float_info("label_upper_bound", hi[te])
        bst = xgb.train(PARAMS, dtr, MAX_ROUNDS, evals=[(dte, "test")],
                        early_stopping_rounds=EARLY_STOP, verbose_eval=False)
        best_rounds.append(bst.best_iteration + 1)
        oof[te] = bst.predict(dte, iteration_range=(0, bst.best_iteration + 1))
        print(f"  fold {k + 1}: {best_rounds[-1]} rounds, "
              f"C-index {concordance(oof[te], lo[te], hi[te]):.3f}")

    # ---- Report --------------------------------------------------------------
    lines = ["Spatial CV (folds grouped by neighbourhood)", ""]
    lines.append(f"Overall C-index: {concordance(oof, lo, hi):.3f}  (0.5 = random, 1.0 = perfect)")
    p3 = survival_prob(oof)
    closed_by_3 = np.isfinite(hi) & (hi <= HORIZON_YEARS)
    known = closed_by_3 | (lo >= HORIZON_YEARS)
    lines.append(f"Restaurants with a known 3-year outcome: {known.sum():,}")
    lines.append("")
    lines.append(f"{'Borough':<15}{'n':>7}{'C-index':>9}{'pred 3yr':>10}{'actual 3yr':>12}")
    for b, idx in rows.groupby("borough").indices.items():
        kb = idx[known[idx]]
        actual = 1 - closed_by_3[kb].mean() if len(kb) else np.nan
        lines.append(f"{b:<15}{len(idx):>7}{concordance(oof[idx], lo[idx], hi[idx]):>9.3f}"
                     f"{p3[kb].mean():>10.1%}{actual:>12.1%}")
    lines.append("")
    lines.append("'actual 3yr' only counts restaurants whose 3-year outcome is known,")
    lines.append("so it is a rough calibration check, not an exact survival rate.")
    report = "\n".join(lines)
    print("\n" + report)
    (out / "cv_report.txt").write_text(report)

    # ---- Final model on all rows --------------------------------------------
    n_rounds = int(np.median(best_rounds))
    dall = xgb.DMatrix(X, weight=w, feature_names=feat_cols)
    dall.set_float_info("label_lower_bound", lo)
    dall.set_float_info("label_upper_bound", hi)
    final = xgb.train(PARAMS, dall, n_rounds)
    final.save_model(str(out / "survival_model.json"))

    imp = pd.Series(final.get_score(importance_type="gain")).sort_values(ascending=False)
    imp.rename("gain").to_csv(out / "feature_importance.csv", header=True)

    # Score new locations as if opened in the latest year that has a full
    # 3 years of follow-up (later cohorts are mostly still censored).
    ref_year = int(min(rows["open_year"].max(), latest.year - HORIZON_YEARS))
    meta = {"features": feat_cols, "aft_scale": AFT_SCALE, "horizon_years": HORIZON_YEARS,
            "reference_open_year": ref_year, "latest_snapshot": str(latest.date()),
            "n_rounds": n_rounds, "n_training_rows": int(len(rows))}
    (out / "model_meta.json").write_text(json.dumps(meta, indent=2))

    # ---- Tract map scores (independent restaurant, typical competition) ----
    comp = CompetitionIndex(life.assign(
        open_date=pd.to_datetime(life["open_date"], errors="coerce"),
        close_date=pd.to_datetime(life["close_date"], errors="coerce")), latest)
    t = tract_feats.copy()
    t["is_chain"] = 0
    t["competitors_400m_at_open"] = [
        comp.count(la, lo_, latest) for la, lo_ in
        zip(master["centroid_latitude"], master["centroid_longitude"])]
    t["open_year"] = ref_year
    pred = final.predict(xgb.DMatrix(t[feat_cols].astype(float).values, feature_names=feat_cols))
    t["survival_3yr"] = survival_prob(pred)
    t["survival_3yr_rank_in_borough"] = t.groupby("borough")["survival_3yr"].rank(pct=True)
    t[["borough", "nta_code", "survival_3yr", "survival_3yr_rank_in_borough"]].to_csv(
        out / "tract_survival_scores.csv")

    print(f"\nSaved model and outputs to {out}")
    print("Top features:", ", ".join(imp.index[:8]))


if __name__ == "__main__":
    main()
