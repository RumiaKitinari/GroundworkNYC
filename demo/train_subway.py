"""Train a station-hour ridership baseline using official MTA observations."""

import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "subway"
REPORT = ROOT / "data" / "evaluation" / "reports" / "subway_station_hour_2025.json"


def load_rows():
    manifest = json.loads((INPUT / "manifest.json").read_text())
    rows = []
    for week in manifest["weeks"]:
        path = INPUT / week["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != week["sha256"]:
            raise ValueError(f"MTA file changed after download: {path.name}")
        with path.open(newline="", encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                moment = datetime.fromisoformat(row["transit_timestamp"])
                rows.append((week["start"], row["station_complex_id"], moment, float(row["ridership"])))
    return rows, manifest


def features(row):
    _, station, moment, _ = row
    hour, day = moment.hour, moment.weekday()
    return {"station": station, "station_hour": f"{station}:{hour}",
            "weekday_hour": f"{day}:{hour}", "day": str(day), "hour": str(hour)}


def metrics(actual, predicted):
    return {"mae_entries_per_hour": round(float(mean_absolute_error(actual, predicted)), 2),
            "rmse_entries_per_hour": round(float(np.sqrt(mean_squared_error(actual, predicted))), 2),
            "r2": round(float(r2_score(actual, predicted)), 4)}


def main():
    rows, manifest = load_rows()
    train = [row for row in rows if row[0] != "2025-12-01"]
    test = [row for row in rows if row[0] == "2025-12-01"]
    if len(train) < 180000 or len(test) < 60000:
        raise ValueError("At least three complete training weeks and one December holdout week are required.")
    vectorizer = DictVectorizer()
    x_train = vectorizer.fit_transform(features(row) for row in train)
    x_test = vectorizer.transform(features(row) for row in test)
    y_train = np.array([row[3] for row in train])
    y_test = np.array([row[3] for row in test])
    model = Ridge(alpha=100.0, solver="lsqr")
    model.fit(x_train, np.log1p(y_train))
    prediction = np.maximum(0, np.expm1(model.predict(x_test)))
    station_means = defaultdict(list)
    for row in train:
        station_means[row[1]].append(row[3])
    means = {station: float(np.mean(values)) for station, values in station_means.items()}
    global_mean = float(np.mean(y_train))
    baseline = np.array([means.get(row[1], global_mean) for row in test])
    report = {
        "target": "subway_station_hour_entries", "created_at": datetime.now(timezone.utc).isoformat(),
        "source": manifest["source"], "train_weeks": sorted({row[0] for row in train}),
        "holdout_week": "2025-12-01", "train_rows": len(train), "test_rows": len(test),
        "stations_train": len(means), "stations_test": len({row[1] for row in test}),
        "features": ["station", "station x hour", "weekday x hour", "weekday", "hour"],
        "model": "Ridge regression on log1p station entries; alpha=100; fixed in advance",
        "station_mean_baseline": metrics(y_test, baseline), "model_metrics": metrics(y_test, prediction),
        "mean_test_entries_per_station_hour": round(float(y_test.mean()), 2),
        "limitations": [
            "Four selected weeks are not a full-year random sample.",
            "December is a temporal holdout, but station identity is shared between training and test.",
            "Subway entries are not measured sidewalk traffic, restaurant visits, sales, or business success.",
            "The model is offline research and does not alter dashboard location scores.",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
