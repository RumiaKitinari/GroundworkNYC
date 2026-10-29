"""Leakage regressions and an actual XGBoost fit on explicitly synthetic fixtures."""
import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from features import (HISTORICAL_FEATURES, TEMPORAL_SCHEMA, build_historical_features,
                      load_historical_snapshots)
from recommend import validate_temporal_model
import recommend
from temporal_cohort import (BASELINE_FIELDS, OBSERVATION_FIELDS, outcome_intervals,
                             three_year_outcome, validate_baselines, validate_observations)
from train_survival import (build_training_rows, fingerprint, fold_for_nta, run,
                            temporal_folds)


class TemporalSurvivalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest = self.root / "snapshots.json"
        self.entries = []
        self.add_snapshot("old", "2021-12-01", 10)

    def add_snapshot(self, name, available, value):
        path = self.root / (name + ".csv")
        pd.DataFrame([{"geoid": "36061000100", **dict.fromkeys(HISTORICAL_FEATURES, value)}]).to_csv(path, index=False)
        self.entries += [{"feature": f, "path": path.name, "observed_through": "2020-12-31",
                          "available_on": available, "sha256": fingerprint(path),
                          "source_url": "https://example.org/test-fixture/" + name,
                          "historical_reconstruction_verified": True} for f in HISTORICAL_FEATURES]
        self.manifest.write_text(json.dumps({"snapshots": self.entries}))

    def baseline(self, **changes):
        return dict({"camis": "1", "open_date": "2022-01-01", "baseline_available_on": "2022-01-01",
                     "baseline_source_reference": "test-only dated baseline", "verification_status": "independently_verified",
                     "geoid": "36061000100", "nta_code": "MN01", "borough": "Manhattan"}, **changes)

    def observation(self, **changes):
        return dict({"camis": "1", "status": "operating", "observed_on": "2022-07-01",
                     "available_on": "2022-07-02", "source_reference": "test-only operation",
                     "verification_status": "independently_verified"}, **changes)

    def snapshots(self):
        return load_historical_snapshots([self.manifest], self.root, "2026-01-01")

    def test_release_date_not_observation_year_controls_selection(self):
        self.add_snapshot("future", "2022-02-01", 99999)
        rows, audit = build_historical_features(pd.DataFrame([self.baseline()]), self.snapshots())
        np.testing.assert_allclose(rows.values, np.log1p(10))
        self.assertEqual({r["available_on"] for r in audit}, {"2021-12-01"})

    def test_same_day_release_allowed(self):
        self.add_snapshot("same_day", "2022-01-01", 15)
        rows, _ = build_historical_features(pd.DataFrame([self.baseline()]), self.snapshots())
        np.testing.assert_allclose(rows.values, np.log1p(15))

    def test_missing_stays_missing_and_current_values_are_ignored(self):
        frame = pd.DataFrame([self.baseline(open_date="2020-01-01", population_density_per_sq_mile=500,
                                           is_chain=1, competitors_400m_at_open=100)])
        rows, audit = build_historical_features(frame, self.snapshots())
        self.assertTrue(rows.isna().all().all())
        self.assertEqual(set(rows), set(HISTORICAL_FEATURES))
        self.assertTrue(all(r["status"] == "unavailable" for r in audit))

    def test_observed_zero_preserved(self):
        self.add_snapshot("zero", "2022-01-01", 0)
        rows, _ = build_historical_features(pd.DataFrame([self.baseline()]), self.snapshots())
        self.assertTrue((rows == 0).all().all())

    def test_snapshot_checksum_and_conflicting_vintages_rejected(self):
        (self.root / "old.csv").write_text("changed")
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            self.snapshots()
        self.entries = []
        self.add_snapshot("old", "2021-12-01", 10)
        self.add_snapshot("conflict", "2021-12-01", 20)
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            self.snapshots()

    def test_legacy_baseline_rejected(self):
        with self.assertRaisesRegex(ValueError, "Legacy lifespan"):
            validate_baselines(pd.DataFrame([{"camis": "1", "open_date": "2022-01-01"}]), "2026-01-01")

    def test_frozen_evaluation_plan_rejects_changed_rounds(self):
        plan = self.root / "evaluation_plan.json"
        plan.write_text(json.dumps({"schema": "groundwork-evaluation-plan-v1", "cutoff": "2024-01-01",
            "as_of": "2026-01-01", "rounds": 200, "folds": 5, "horizon_years": 3.0,
            "predictors": list(HISTORICAL_FEATURES), "version": "fixture"}))
        with self.assertRaisesRegex(ValueError, "frozen evaluation plan"):
            run(self.root / "missing.csv", self.root / "missing_events.csv", [], self.root,
                self.root / "unpublished", "2026-01-01", "2024-01-01", rounds=4, evaluation_plan=plan)
        self.assertFalse((self.root / "unpublished").exists())

    def test_late_baseline_excluded_not_backdated(self):
        rows, exclusions = validate_baselines(pd.DataFrame([
            self.baseline(baseline_available_on="2022-01-02")]), "2026-01-01")
        self.assertEqual(len(rows), 0)
        self.assertEqual(exclusions, {"baseline_not_known_at_opening": 1})

    def test_duplicate_baseline_rejected(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_baselines(pd.DataFrame([self.baseline(), self.baseline()]), "2026-01-01")

    def test_future_closure_is_censored_at_last_known_operation(self):
        baseline = pd.DataFrame([self.baseline()])
        events = validate_observations(pd.DataFrame([
            self.observation(), self.observation(status="permanent_closure", observed_on="2022-09-01",
                available_on="2024-05-01", source_reference="test-only delayed closure")]), baseline)
        before, _ = outcome_intervals(baseline, events, "2024-01-01", True)
        after, _ = outcome_intervals(baseline, events, "2026-01-01")
        self.assertTrue(np.isinf(before.iloc[0].y_upper))
        self.assertEqual(before.iloc[0].y_lower, 181 / 365.25)
        self.assertEqual(after.iloc[0].y_upper, 243 / 365.25)

    def test_cutoff_day_label_not_available_for_training(self):
        baseline = pd.DataFrame([self.baseline()])
        events = validate_observations(pd.DataFrame([self.observation(available_on="2024-01-01")]), baseline)
        rows, _ = outcome_intervals(baseline, events, "2024-01-01", True)
        self.assertEqual(len(rows), 0)

    def test_absence_and_unverified_evidence_do_not_become_closures(self):
        baseline = pd.DataFrame([self.baseline()])
        events = validate_observations(pd.DataFrame([self.observation(status="snapshot_disappearance",
                            verification_status="unverified")]), baseline)
        rows, excluded = outcome_intervals(baseline, events, "2026-01-01")
        self.assertEqual(len(rows), 0)
        self.assertEqual(excluded["no_verified_followup_operation"], 1)
        with self.assertRaisesRegex(ValueError, "Only verified"):
            validate_observations(pd.DataFrame([self.observation(status="snapshot_disappearance")]), baseline)

    def test_impossible_chronology_and_identity_conflict_rejected(self):
        baseline = pd.DataFrame([self.baseline()])
        with self.assertRaisesRegex(ValueError, "chronology"):
            validate_observations(pd.DataFrame([self.observation(available_on="2022-06-01")]), baseline)
        events = validate_observations(pd.DataFrame([self.observation(), self.observation(
            status="permanent_closure", observed_on="2022-06-01", available_on="2022-06-02",
            source_reference="different")]), baseline)
        with self.assertRaisesRegex(ValueError, "conflicts"):
            outcome_intervals(baseline, events, "2026-01-01")

    def test_no_epsilon_or_midpoint_invented(self):
        baseline = pd.DataFrame([self.baseline()])
        events = validate_observations(pd.DataFrame([self.observation(observed_on="2022-01-01",
                                                                    available_on="2022-01-01")]), baseline)
        rows, excluded = outcome_intervals(baseline, events, "2026-01-01")
        self.assertEqual(len(rows), 0)
        self.assertEqual(excluded["no_positive_followup"], 1)

    def test_three_year_straddling_and_early_censoring_remain_unknown(self):
        got = three_year_outcome([1, 1, 2, 3, 3.2], [2, np.inf, 4, np.inf, 4])
        np.testing.assert_allclose(got, [0, np.nan, np.nan, 1, 1], equal_nan=True)

    def make_population(self):
        baselines, observations = [], []
        for index in range(30):
            nta = "NTA" + str(index % 10)
            for prefix, opening, follow, closure in (
                ("train", "2022-01-01", "2022-07-01", "2023-01-01"),
                ("test", "2024-02-01", "2024-08-01", "2025-02-01")):
                camis = prefix + str(index)
                baselines.append(self.baseline(camis=camis, nta_code=nta, open_date=opening,
                                                baseline_available_on=opening))
                observations.append(self.observation(camis=camis, observed_on=follow, available_on=follow))
                if index % 2 == 0:
                    observations.append(self.observation(camis=camis, status="permanent_closure",
                        observed_on=closure, available_on=closure, source_reference="closure " + camis))
        return pd.DataFrame(baselines), pd.DataFrame(observations)

    def test_temporal_and_spatial_partitions_and_no_future_label_clipping(self):
        baselines, ledger = self.make_population()
        observations = validate_observations(ledger, baselines)
        tested = set()
        for fold, tr, te, _ in temporal_folds(baselines, observations, self.snapshots(),
                                             "2024-01-01", "2026-01-01"):
            self.assertTrue((tr.open_date < "2024-01-01").all())
            self.assertTrue((tr.label_available_on < "2024-01-01").all())
            self.assertTrue((te.open_date >= "2024-01-01").all())
            self.assertFalse(set(tr.nta_code) & set(te.nta_code))
            self.assertFalse(tested & set(te.camis))
            tested.update(te.camis)
        self.assertEqual(len(tested), 30)

    def test_actual_xgboost_fit_reproducibility_and_heldout_label_perturbation(self):
        baselines, ledger = self.make_population()
        bp, op = self.root / "baselines.csv", self.root / "observations.csv"
        baselines.to_csv(bp, index=False)
        ledger.to_csv(op, index=False)
        one, two = self.root / "run_one", self.root / "run_two"
        a = run(bp, op, [self.manifest], self.root, one, "2026-01-01", "2024-01-01", rounds=4)
        b = run(bp, op, [self.manifest], self.root, two, "2026-01-01", "2024-01-01", rounds=4)
        self.assertTrue(a["training_performed"])
        self.assertEqual(a["artifact_sha256"], b["artifact_sha256"])
        predictions = pd.read_csv(one / "heldout_predictions.csv")
        self.assertTrue(predictions.survival_3yr.between(0, 1).all())
        self.assertTrue((one / "fold_assignments.csv").exists())
        self.assertTrue((one / "feature_provenance.csv").exists())
        evaluation = json.loads((one / "evaluation.json").read_text())
        self.assertEqual(evaluation["overall"]["rows"], 30)
        self.assertTrue(all(len(fold["feature_ablations"]) == len(HISTORICAL_FEATURES)
                            for fold in evaluation["folds"] if fold["status"] == "evaluated"))
        self.assertEqual(a["features"], list(HISTORICAL_FEATURES))
        # Exercise the preserved property filtering/ranking path with a model
        # trained by the new pipeline, without touching repository outputs.
        listing = {"property_id": "fixture", "borough": "Manhattan", "neighborhood": "Fixture",
                   "transaction": "lease", "available_sqft": 1200, "monthly_rent": 5000,
                   "annual_rent_psf": 50, "asking_price": 0, "former_food_use": True,
                   "corner_position": False, "ground_floor": True, "latitude": 40.7,
                   "longitude": -74.0, "geoid": "36061000100"}
        listings = self.root / "listings.csv"
        pd.DataFrame([listing, dict(listing, property_id="over_budget", monthly_rent=15000)]).to_csv(listings, index=False)
        rec_dir = self.root / "recommendations"
        rec_dir.mkdir()
        argv = ["recommend.py", "--cuisine", "Indian", "--model-dir", str(one), "--listings", str(listings),
                "--snapshots", str(self.manifest), "--data-dir", str(self.root), "--prediction-date", "2026-01-01",
                "--max-monthly-rent", "9000", "--cuisine-scores", str(self.root / "absent.csv")]
        with patch("sys.argv", argv), patch.object(recommend, "RECOMMENDATIONS", rec_dir), \
                patch.object(recommend, "ensure_dirs"), redirect_stdout(io.StringIO()):
            recommend.main()
        recommendation = pd.read_csv(rec_dir / "recommendations_indian.csv")
        self.assertEqual(recommendation.property_id.tolist(), ["fixture"])
        self.assertAlmostEqual(recommendation.iloc[0].score, .6)
        self.assertTrue(recommendation.restaurants_within_400m.isna().all())
        # Alter only future-cohort labels. Test labels must never tune trees.
        mask = ledger.camis.str.startswith("test") & ledger.status.eq("permanent_closure")
        ledger.loc[mask, ["observed_on", "available_on"]] = "2025-10-01"
        ledger.to_csv(op, index=False)
        three = self.root / "run_three"
        c = run(bp, op, [self.manifest], self.root, three, "2026-01-01", "2024-01-01", rounds=4)
        later_predictions = pd.read_csv(three / "heldout_predictions.csv")
        np.testing.assert_allclose(predictions.baseline_median_years, later_predictions.baseline_median_years)
        for name in a["artifact_sha256"]:
            if name.startswith("fold_") and name.endswith(".json"):
                self.assertEqual(a["artifact_sha256"][name], c["artifact_sha256"][name])
        with self.assertRaises(FileExistsError):
            run(bp, op, [self.manifest], self.root, one, "2026-01-01", "2024-01-01", rounds=4)

    def test_all_censored_evidence_cannot_publish_survival_model(self):
        baselines, ledger = self.make_population()
        ledger = ledger[ledger.status.eq("operating")]
        bp, op = self.root / "baselines.csv", self.root / "observations.csv"
        baselines.to_csv(bp, index=False)
        ledger.to_csv(op, index=False)
        output = self.root / "censored"
        result = run(bp, op, [self.manifest], self.root, output, "2026-01-01", "2024-01-01", rounds=2)
        self.assertFalse(result["training_performed"])
        self.assertFalse((output / "survival_model.json").exists())

    def test_legacy_audit_is_explicit_and_does_not_publish_model(self):
        bp = self.root / "legacy.csv"
        pd.DataFrame([{"camis": "1", "open_date": "2022-01-01", "closed": True}]).to_csv(bp, index=False)
        output = self.root / "audit"
        result = run(bp, None, [self.manifest], self.root, output, "2026-01-01", audit_only=True)
        self.assertEqual(result["status"], "needs_dated_baseline_evidence")
        self.assertFalse((output / "survival_model.json").exists())

    def test_legacy_models_and_backdated_predictions_rejected(self):
        with self.assertRaisesRegex(ValueError, "Legacy"):
            validate_temporal_model({"features": ["is_chain"]}, "2026-01-01")
        meta = {"schema": TEMPORAL_SCHEMA, "features": list(HISTORICAL_FEATURES), "trained_as_of": "2026-01-01"}
        with self.assertRaisesRegex(ValueError, "on/after"):
            validate_temporal_model(meta, "2025-12-31")
        validate_temporal_model(meta, "2026-01-01")

    def test_future_source_and_derived_columns_do_not_change_prior_features(self):
        baselines = pd.DataFrame([self.baseline()])
        expected, _ = build_historical_features(baselines, self.snapshots())
        self.add_snapshot("later", "2025-01-01", 1e9)
        baselines["is_chain"] = 1
        baselines["competitors_400m_at_open"] = 9000
        baselines["permitted_event_count_next_90_days"] = 700
        actual, _ = build_historical_features(baselines, self.snapshots())
        pd.testing.assert_frame_equal(expected, actual)

    def test_no_followup_for_future_cohort_means_no_final_model(self):
        baselines, ledger = self.make_population()
        ledger = ledger[ledger.camis.str.startswith("train")]
        bp, op = self.root / "baselines.csv", self.root / "observations.csv"
        baselines.to_csv(bp, index=False)
        ledger.to_csv(op, index=False)
        output = self.root / "no_holdout"
        result = run(bp, op, [self.manifest], self.root, output, "2026-01-01", "2024-01-01", rounds=2)
        self.assertEqual(result["status"], "insufficient_temporal_validation_evidence")
        self.assertFalse((output / "survival_model.json").exists())


if __name__ == "__main__":
    unittest.main()
