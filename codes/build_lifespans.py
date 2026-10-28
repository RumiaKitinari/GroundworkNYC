r"""
Build a restaurant lifespan (survival) table from the nyc-cuisine-atlas archive.

Input : restaurants_raw.parquet  (from github.com/CharlesFainLehman/nyc-cuisine-atlas, data/)
Output: restaurant_lifespans.csv  one row per restaurant (CAMIS)

Columns
  open_date     first pre-permit inspection proxy, else first inspection seen (not verified opening)
  open_known    True if open_date comes from a pre-permit inspection
  closed        True if the restaurant is missing from the latest snapshot
  close_date    midpoint between the last snapshot listing it and the next snapshot
  close_window_days  width of that gap (how uncertain close_date is)
  years         open_date -> close_date (or -> latest snapshot if still open)
  clean_cohort  True if opened after 2020-11-06, when snapshots became frequent.
                Legacy research filter, NOT evidence of valid survival labels.

This summary is retained for archive review. It cannot establish when all
attributes were available, or whether disappearance means permanent closure.
train_survival.py requires a separate dated baseline and outcome ledger.
"""
import sys
import numpy as np
import pandas as pd

from paths import OUTPUTS, ensure_dirs, find

GAP_END = pd.Timestamp("2020-11-06")   # no snapshots Apr 2017 - Nov 2020

def main(src, dst):
    r = pd.read_parquet(src)
    snaps = sorted(set(pd.to_datetime(pd.concat([r.first_snapshot, r.last_snapshot]).dropna())))
    latest = snaps[-1]
    nxt = dict(zip(snaps[:-1], snaps[1:]))

    r["open_known"] = r.first_prepermit.notna()
    r["open_date"] = r.first_prepermit.fillna(r.first_insp)
    r["closed"] = r.last_snapshot < latest
    nxt_snap = r.last_snapshot.map(nxt)
    r["close_window_days"] = np.where(r.closed, (nxt_snap - r.last_snapshot).dt.days, np.nan)
    r["close_date"] = r.last_snapshot + (nxt_snap - r.last_snapshot) / 2
    r.loc[~r.closed, "close_date"] = pd.NaT
    r["years"] = ((r.close_date.fillna(latest) - r.open_date).dt.days / 365.25).round(3)
    r["clean_cohort"] = r.open_known & (r.open_date > GAP_END) & (r.years >= 0)

    cols = ["camis", "dba", "boro", "zipcode", "cuisine", "lat", "lon", "nta",
            "open_date", "open_known", "closed", "close_date", "close_window_days",
            "years", "clean_cohort", "first_snapshot", "last_snapshot"]
    r[cols].to_csv(dst, index=False)
    print("Archive review only: inferred starts and disappearances are not verified survival outcomes.")
    print(f"{len(r):,} restaurants, {r.closed.sum():,} absent from latest snapshot, "
          f"{r.clean_cohort.sum():,} in clean cohort (latest snapshot {latest.date()})")

if __name__ == "__main__":
    ensure_dirs()
    main(sys.argv[1] if len(sys.argv) > 1 else find("restaurants_raw.parquet"),
         sys.argv[2] if len(sys.argv) > 2 else OUTPUTS / "restaurant_lifespans.csv")
