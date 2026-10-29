"""Main-branch improvements cannot weaken research or storage contracts."""
import csv
import json
import warnings

import app as module
import pandas as pd
from features import build_tract_features
from survival_inference import attach_model


def test_external_data_directory_is_shared_by_package_loader(tmp_path, monkeypatch):
    monkeypatch.setenv("GROUNDWORK_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(module, "_load_integrated_package", lambda path: {"resolved": path})
    assert module.integrated_directory() == tmp_path.resolve()
    assert module.integrated_package()["resolved"] == tmp_path.resolve()


def test_missing_neighbor_income_does_not_break_feature_builder():
    master = pd.read_csv(module.integrated_directory() / "master_tract_features.csv").head(2)
    master = master.drop(columns=["neighbor_income_2024_estimate"], errors="ignore")
    master.loc[master.index[0], "median_household_income_2024"] = float("nan")
    # This two-row fixture intentionally omits most neighboring tracts.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Mean of empty slice", category=RuntimeWarning)
        features = build_tract_features(master)
    assert pd.isna(features.iloc[0]["median_household_income"])


def test_proxy_export_cannot_replace_screening_rank(tmp_path, monkeypatch):
    monkeypatch.delenv("GROUNDWORK_ATHARV_SCORES", raising=False)
    path = tmp_path / "export.csv"
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["geoid", "borough", "nta_code", "survival_3yr", "survival_3yr_rank_in_borough"])
        writer.writerow(["36061000100", "Manhattan", "MN01", .1, .1])
        writer.writerow(["36061000200", "Manhattan", "MN01", .9, .9])
    config = tmp_path / "pointer.json"
    config.write_text(json.dumps({"tract_scores": str(path)}))
    rows = [{"geoid": "36061000100", "opportunity": 90}, {"geoid": "36061000200", "opportunity": 50}]
    result, status = attach_model(rows, rows, "any", config)
    assert [row["opportunity"] for row in result] == [90, 50]
    assert status["ranking_mode"] == "screening"
    assert status["source_type"] == "atharv_tract_export"
    assert [row["survival"]["probability"] for row in result] == [.1, .9]
    assert not any("ranking_components" in row for row in result)


def test_invalid_numeric_source_values_stay_unavailable():
    for value in ("", "nan", "inf", "not-a-number"):
        assert module.source_number({"value": value}, "value") is None
    assert module.source_number({"value": "0"}, "value") == 0
