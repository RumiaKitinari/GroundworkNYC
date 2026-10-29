r"""
Run the whole pipeline in order.

Usage (from E:\440 CAPSTONE\codes):
    python run_all.py                          build everything (steps 1-5)
    python run_all.py --cuisine "Indian" --max-monthly-rent 9000
                                               build everything, then recommend
    python run_all.py --from train             start at a later step
    python run_all.py --only heatmaps          run one step
    python run_all.py --list                   show the steps

Any option run_all.py doesn't recognise (e.g. --boroughs, --chain, --top)
is passed straight to recommend.py.

Steps:
    1. labels     label_cuisines.py   data\current_restaurants.csv -> outputs\restaurants_labeled.csv
    2. matrix     cuisine_matrix.py   -> outputs\cuisine_matrix.csv
    3. heatmaps   make_heatmaps.py    -> outputs\hex_cuisine_scores.csv, cuisine_heatmaps.html
    4. lifespans  build_lifespans.py  data\restaurants_raw.parquet -> outputs\restaurant_lifespans.csv
    5. train      train_survival.py   -> outputs\model\
    6. recommend  recommend.py        -> outputs\recommendations\  (only with --cuisine)

If restaurants_raw.parquet is missing from data\, it is downloaded from the
nyc-cuisine-atlas repo on GitHub first.
"""
import argparse
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from paths import DATA, OUTPUTS, ensure_dirs, find

CODES = Path(__file__).resolve().parent
PARQUET_URL = ("https://github.com/CharlesFainLehman/nyc-cuisine-atlas/raw/main/"
               "data/restaurants_raw.parquet")

# name, script, files it needs (looked up in outputs\ then data\)
STEPS = [
    ("labels", "label_cuisines.py", ["current_restaurants.csv"]),
    ("matrix", "cuisine_matrix.py", []),
    ("heatmaps", "make_heatmaps.py", ["restaurants_labeled.csv"]),
    ("lifespans", "build_lifespans.py", ["restaurants_raw.parquet"]),
    ("train", "train_survival.py", []),  # explicit verified evidence, not the lifespan summary
    ("recommend", "recommend.py", ["synthetic_properties.csv", "hex_cuisine_scores.csv"]),
]
NAMES = [s[0] for s in STEPS]


def get_parquet():
    target = DATA / "restaurants_raw.parquet"
    if find("restaurants_raw.parquet").exists():
        return
    print(f"restaurants_raw.parquet not found; downloading to {target} ...")
    DATA.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(".part")
    try:
        urllib.request.urlretrieve(PARQUET_URL, part)
    except Exception as e:
        part.unlink(missing_ok=True)
        sys.exit(f"\nDownload failed ({e}).\nDownload it in your browser from:\n  {PARQUET_URL}\n"
                 f"save it as {target}, then run:  python run_all.py --from lifespans")
    part.replace(target)
    print(f"  downloaded {target.stat().st_size / 1e6:.1f} MB")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start", choices=NAMES, help="start at this step")
    ap.add_argument("--only", choices=NAMES, help="run just this step")
    ap.add_argument("--list", action="store_true", help="list the steps and exit")
    ap.add_argument("--cuisine", help="also run recommend.py for this cuisine")
    ap.add_argument("--baselines", type=Path)
    ap.add_argument("--observations", type=Path)
    ap.add_argument("--snapshots", type=Path, action="append")
    ap.add_argument("--data-dir", type=Path, default=DATA)
    ap.add_argument("--as-of")
    ap.add_argument("--cutoff")
    ap.add_argument("--model-dir", type=Path)
    a, rec_args = ap.parse_known_args()

    if a.list:
        for i, (n, s, _) in enumerate(STEPS, 1):
            print(f"{i}. {n:<10} {s}")
        return

    if a.only:
        todo = [s for s in STEPS if s[0] == a.only]
    else:
        start = NAMES.index(a.start) if a.start else 0
        todo = STEPS[start:5]                       # build steps
        if a.cuisine:
            todo.append(STEPS[5])                    # + recommend
    if any(s[0] == "recommend" for s in todo) and not a.cuisine:
        sys.exit("The recommend step needs --cuisine.")
    names = {step[0] for step in todo}
    if "train" in names and not all((a.baselines, a.observations, a.snapshots,
                                     a.as_of, a.cutoff, a.model_dir)):
        sys.exit("Temporal training requires --baselines, --observations, --snapshots, "
                 "--as-of, --cutoff and a new --model-dir. See TEMPORAL_SURVIVAL.md. "
                 "Legacy lifespan summaries are not training evidence.")
    if "recommend" in names and not all((a.snapshots, a.model_dir)):
        sys.exit("Temporal recommendations require --snapshots and --model-dir.")

    ensure_dirs()
    print(f"Data:    {DATA}\nOutputs: {OUTPUTS}\n")
    total = time.time()
    for i, (name, script, needs) in enumerate(todo, 1):
        if name == "lifespans":
            get_parquet()
        # Inputs made by an earlier step in this run don't exist yet; only
        # check files that no step in this run will create.
        made_later = {"restaurants_labeled.csv": "labels", "restaurant_lifespans.csv": "lifespans",
                      "hex_cuisine_scores.csv": "heatmaps"}
        ran = {n for n, _, _ in todo[:i - 1]}
        missing = [f for f in needs if not find(f).exists() and made_later.get(f) not in ran]
        if missing:
            sys.exit(f"\nStep '{name}' can't run: missing {', '.join(missing)}.\n"
                     f"Put raw inputs in {DATA}, or run the earlier steps first.")

        cmd = [sys.executable, str(CODES / script)]
        if name in {"train", "recommend"}:
            cmd += ["--data-dir", str(a.data_dir.resolve())]
            for manifest in a.snapshots:
                cmd += ["--snapshots", str(manifest.resolve())]
        if name == "train":
            cmd += ["--baselines", str(a.baselines.resolve()), "--observations", str(a.observations.resolve()),
                    "--as-of", a.as_of, "--cutoff", a.cutoff, "--out-dir", str(a.model_dir.resolve())]
        if name == "recommend":
            cmd += ["--cuisine", a.cuisine, "--model-dir", str(a.model_dir.resolve())] + rec_args
        print(f"=== [{i}/{len(todo)}] {name}: {script} ===")
        t = time.time()
        result = subprocess.run(cmd, cwd=CODES)
        if result.returncode != 0:
            sys.exit(f"\nStopped: {script} failed (exit code {result.returncode}). "
                     f"Fix it, then resume with:  python run_all.py --from {name}")
        print(f"--- {name} done in {time.time() - t:.0f}s\n")

    print(f"All done in {time.time() - total:.0f}s. Outputs are in {OUTPUTS}")


if __name__ == "__main__":
    main()
