"""Replay every saved fold model and verify frozen matched evaluation artifacts."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold
import xgboost as xgb

from customer_access import file_hash
from evaluate_matched_results import PARENT,OPT,REPAIRS,matched_cohort,verify_manifest,within_fold_concordance
from optimize_archive_model import closure_variant
from survival_metrics import evaluate_predictions,fit_constant_aft
from train_archive_aft import research_matrix
from train_survival import survival_prob


def validate(run,scenarios):
    run,scenarios = Path(run).resolve(),Path(scenarios).resolve()
    manifest = verify_manifest(run)
    scenario_manifest = verify_manifest(scenarios)
    for directory,record in ((run,manifest),(scenarios,scenario_manifest)):
        for source,expected in record["sources"].items():
            if file_hash(source)!=expected:
                raise ValueError("Pinned source manifest changed: "+source)
    parent = verify_manifest(PARENT,"run_manifest.json")
    verify_manifest(OPT)
    verify_manifest(REPAIRS)
    types = {"camis":str,"geoid":str}
    source = pd.read_csv(PARENT/"corrected_research/training_rows.csv",dtype=types,float_precision="round_trip",low_memory=False)
    dated = pd.read_csv(REPAIRS/"opening_time_core_features.csv",dtype=types,float_precision="round_trip")
    roles = pd.read_csv(OPT/"split_assignments.csv",dtype={"camis":str})
    expected,audit = matched_cohort(source,dated,roles)
    for name in ("population_density","median_household_income","job_density"):
        expected["current_core_"+name] = expected["context_"+name]
    expected["current_core_national_walkability_index"] = np.log1p(expected.context_walkability)
    cohort = pd.read_csv(run/"matched_cohort.csv",dtype=types,float_precision="round_trip",low_memory=False)
    pd.testing.assert_frame_equal(cohort,expected,check_dtype=False)
    plan = json.loads((run/"plan.json").read_text())
    lock = json.loads((run/"protocol_lock.json").read_text())
    results = json.loads((run/"results.json").read_text())
    if file_hash(run/"protocol_lock.json")!=results["protocol_lock_sha256"] or not lock["created_before_fitting"]:
        raise ValueError("Evaluation protocol lock invalid")
    for key,filename in (("plan_sha256","plan.json"),("cohort_sha256","matched_cohort.csv"),("folds_sha256","fold_assignments.csv")):
        if file_hash(run/filename)!=lock[key]:
            raise ValueError("Protocol input changed: "+filename)
    if results["production_deployment_allowed"] or results["model_selection_performed"]:
        raise ValueError("Diagnostic scope changed")
    assignments = pd.read_csv(run/"fold_assignments.csv",dtype=types)
    if assignments.camis.tolist()!=cohort.camis.tolist():
        raise ValueError("Fold identities differ")
    folds = list(GroupKFold(n_splits=plan["folds"]).split(cohort,groups=cohort.nta_code))
    predictions = pd.read_csv(run/"oof_predictions.csv",dtype=types,float_precision="round_trip")
    if predictions.duplicated(["rule","model","camis"]).any():
        raise ValueError("Duplicate OOF predictions")
    if (len(predictions)!=len(cohort)*len(plan["closure_rules"])*(len(lock["features"])+1)
            or set(predictions.model)!=set(lock["features"])|{"constant_aft"}
            or set(predictions.rule)!=set(plan["closure_rules"])
            or set(predictions.camis)!=set(cohort.camis)):
        raise ValueError("Unexpected/missing prediction cases or identities")
    raw = pd.read_parquet(PARENT/"frozen_root/data/restaurants_raw.parquet",columns=["first_snapshot","last_snapshot"])
    captures = pd.concat([raw.first_snapshot,raw.last_snapshot]).dropna().unique()
    count = 0
    metrics = {(r["rule"],r["model"]):r for r in results["models"]}
    for rule in plan["closure_rules"]:
        variant,_ = closure_variant(cohort,captures,rule)
        for name,columns in [*lock["features"].items(),("constant_aft",[])]:
            saved = predictions[predictions.rule.eq(rule)&predictions.model.eq(name)].set_index("camis").loc[cohort.camis]
            np.testing.assert_allclose(saved.y_lower,variant.y_lower,rtol=0,atol=0)
            np.testing.assert_allclose(saved.y_upper,variant.y_upper,rtol=0,atol=0)
            for fold,(tr,te) in enumerate(folds):
                if set(cohort.iloc[tr].nta_code)&set(cohort.iloc[te].nta_code):
                    raise ValueError("NTA overlap")
                if not assignments.fold.iloc[te].eq(fold).all() or not saved.fold.iloc[te].eq(fold).all():
                    raise ValueError("Model folds do not match protocol")
                if name=="constant_aft":
                    pred = np.full(len(te),fit_constant_aft(variant.iloc[tr].y_lower,variant.iloc[tr].y_upper))
                else:
                    booster = xgb.Booster()
                    booster.load_model(run/f"{rule}__{name}__fold_{fold}.json")
                    if booster.feature_names!=columns or booster.num_boosted_rounds()!=plan["rounds"]:
                        raise ValueError("Native model schema/rounds differ")
                    pred = booster.predict(research_matrix(variant.iloc[te],columns))
                    count+=1
                np.testing.assert_allclose(saved.median_years.iloc[te],pred,rtol=1e-6,atol=1e-6)
            np.testing.assert_allclose(saved.proxy_aft_3yr,survival_prob(saved.median_years),rtol=1e-12,atol=1e-12)
            evaluated = evaluate_predictions(saved.median_years,saved.y_lower,saved.y_upper)
            stored = metrics[(rule,name)]
            np.testing.assert_allclose(evaluated["interval_negative_log_likelihood"],stored["interval_negative_log_likelihood"],rtol=1e-12)
            np.testing.assert_allclose(evaluated["concordance"]["estimate"],stored["concordance"]["estimate"],rtol=1e-12)
            constant = predictions[predictions.rule.eq(rule)&predictions.model.eq("constant_aft")].set_index("camis").loc[cohort.camis]
            within = within_fold_concordance(constant.median_years,saved.median_years,variant.y_lower,variant.y_upper,variant.nta_code,assignments.fold)
            np.testing.assert_allclose(within["candidate"],stored["within_fold_concordance"],rtol=1e-12)
    scenario_result = json.loads((scenarios/"results.json").read_text())
    ids = None
    for profile in scenario_result["summaries"]:
        frame = pd.read_csv(scenarios/(profile["profile"]+".csv"),dtype={"property_id":str})
        if ids is None:
            ids = frame.property_id.tolist()
        if frame.property_id.duplicated().any() or frame.property_id.tolist()!=ids or len(frame)!=1000:
            raise ValueError("Scenario inventory changed or sampled")
        if not frame.inventory_type.isin(["synthetic","synthetic_demonstration"]).all():
            raise ValueError("Synthetic status changed")
        for column in ("general_fit_no_cuisine","cuisine_screening","customer_access_percentile","huff_percentile"):
            values = frame[column].dropna()
            if not np.isfinite(values).all() or not values.between(0,100).all():
                raise ValueError("Invalid scenario index")
        if frame.huff_opportunities.notna().sum()!=profile["huff_rated"]:
            raise ValueError("Scenario coverage report differs")
    if scenario_result["predictive_accuracy_evaluated"] or scenario_result["survival_blend_evaluated"]:
        raise ValueError("Scenario interpretation changed")
    return {"status":"passed","model_artifacts_checked":len(manifest["artifact_sha256"]),
            "scenario_artifacts_checked":len(scenario_manifest["artifact_sha256"]),"parent_artifacts_checked":len(parent["artifact_sha256"]),
            "native_models_replayed":count,"prediction_rows_checked":len(predictions),"matched_restaurants":len(cohort),
            "reserved_restaurants_used":0,"scenarios_checked":len(scenario_result["summaries"]),
            "properties_per_scenario":len(ids),"globally_untouched_test":False,"production_deployment_allowed":False}


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",required=True)
    parser.add_argument("--scenarios",required=True)
    parser.add_argument("--output",required=True)
    args = parser.parse_args()
    result = validate(args.run,args.scenarios)
    path = Path(args.output)
    if path.exists():
        raise ValueError("Use a new validation filename")
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
