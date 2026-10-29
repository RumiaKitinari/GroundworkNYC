"""Matched development diagnostics using the user's frozen local outputs only."""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold
import xgboost as xgb

from customer_access import file_hash
from features import HISTORICAL_FEATURES
from optimize_archive_model import closure_variant, fit_model
from survival_metrics import evaluate_predictions, fit_constant_aft, interval_nll, paired_concordance_delta
from train_archive_aft import research_matrix
from train_survival import PARAMS, survival_prob

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT/"data/output/research_runs/20261027_archive_aft_v2"
OPT = ROOT/"data/output/optimization/20261027_v1"
REPAIRS = ROOT/"data/output/feature_repairs/20261028_v3"


def verify_manifest(directory, manifest_name="manifest.json", key="artifact_sha256"):
    directory = Path(directory)
    manifest = json.loads((directory/manifest_name).read_text())
    for name,digest in manifest[key].items():
        if file_hash(directory/name)!=digest:
            raise ValueError("Pinned artifact changed: "+str(directory/name))
    return manifest


def matched_cohort(rows, dated, split):
    for frame in (rows,dated,split):
        if frame.camis.duplicated().any():
            raise ValueError("Duplicate cohort identities")
    available = dated.set_index("camis")
    if set(rows.camis)!=set(available.index) or set(rows.camis)!=set(split.camis):
        raise ValueError("Pinned cohorts differ")
    aligned = available.loc[rows.camis]
    if not np.array_equal(aligned.geoid.to_numpy(str),rows.geoid.to_numpy(str)):
        raise ValueError("Historical geography differs")
    if not np.array_equal(aligned.open_date.to_numpy(str),rows.open_date.to_numpy(str)):
        raise ValueError("Historical time origins differ")
    result = rows.copy()
    for feature in HISTORICAL_FEATURES:
        result["dated_"+feature] = aligned[feature].to_numpy(float)
    roles = split.set_index("camis").loc[rows.camis].optimization_role.to_numpy(str)
    complete = aligned[list(HISTORICAL_FEATURES)].notna().all(axis=1).to_numpy()
    keep = (roles=="development") & complete
    audit = {"source_rows":len(rows),"reserved_rows_excluded":int((roles!="development").sum()),
             "development_rows_without_all_four_dated_features":int(((roles=="development") & ~complete).sum()),
             "matched_development_rows":int(keep.sum()),"all_source_rows_previously_exposed_in_research_cv":True}
    return result.loc[keep].reset_index(drop=True),audit


def paired_nll_delta(reference,candidate,lower,upper,groups,seed=440,replicates=300):
    difference = interval_nll(candidate,lower,upper)-interval_nll(reference,lower,upper)
    labels,codes = np.unique(np.asarray(groups,str),return_inverse=True)
    sums = np.bincount(codes,weights=difference)
    sizes = np.bincount(codes)
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(replicates):
        counts = np.bincount(rng.integers(0,len(labels),len(labels)),minlength=len(labels))
        draws.append(float(counts@sums/(counts@sizes)))
    return {"candidate_minus_reference":float(difference.mean()),
            "nta_bootstrap_95_ci":np.quantile(draws,[.025,.975]).tolist(),
            "interpretation":"Lower is better; conditional on fitted models and proxy labels, not refitting uncertainty"}


def within_fold_concordance(reference,candidate,lower,upper,groups,folds,seed=440):
    reference,candidate,lower,upper = map(lambda v:np.asarray(v,float),(reference,candidate,lower,upper))
    folds = np.asarray(folds)
    rng = np.random.default_rng(seed)
    if len(lower)<=800:
        i,j = np.indices((len(lower),len(lower))).reshape(2,-1)
    else:
        i,j = rng.integers(0,len(lower),(2,900000))
    use = (i!=j) & (folds[i]==folds[j]) & np.isfinite(upper[i]) & (upper[i]<lower[j])
    i,j = i[use],j[use]
    if not len(i):
        raise ValueError("No within-fold comparable pairs")
    def credit(values):
        return (values[i]<values[j]).astype(float)+.5*(values[i]==values[j])
    a,b = credit(reference),credit(candidate)
    labels,codes = np.unique(np.asarray(groups,str),return_inverse=True)
    delta = b-a
    draws = []
    for _ in range(200):
        counts = np.bincount(rng.integers(0,len(labels),len(labels)),minlength=len(labels))
        weights = counts[codes[i]]*counts[codes[j]]
        if weights.sum():
            draws.append(float(np.average(delta,weights=weights)))
    return {"reference":float(a.mean()),"candidate":float(b.mean()),"candidate_minus_reference":float(delta.mean()),
            "nta_bootstrap_95_ci":np.quantile(draws,[.025,.975]).tolist(),"comparable_pairs":len(i),
            "scope":"Only pairs evaluated by the same fold model; conditional on fitted predictions"}


def run(output,plan_path):
    output = Path(output).resolve()
    if output.exists() or not output.is_relative_to(ROOT/"data/output"):
        raise ValueError("Use a new private data/output directory")
    plan = json.loads(Path(plan_path).read_text())
    if plan["schema"]!="matched-results-plan-v1" or plan["production_deployment_allowed"] or plan["reserved_assessment_used_for_selection"]:
        raise ValueError("Nonproduction development-only plan required")
    verify_manifest(PARENT,"run_manifest.json")
    verify_manifest(OPT)
    verify_manifest(REPAIRS)
    rows = pd.read_csv(PARENT/"corrected_research/training_rows.csv",dtype={"camis":str,"geoid":str},float_precision="round_trip",low_memory=False)
    dated = pd.read_csv(REPAIRS/"opening_time_core_features.csv",dtype={"camis":str,"geoid":str},float_precision="round_trip")
    split = pd.read_csv(OPT/"split_assignments.csv",dtype={"camis":str})
    cohort,cohort_audit = matched_cohort(rows,dated,split)
    for name in ("population_density","median_household_income","job_density"):
        cohort["current_core_"+name] = cohort["context_"+name]
    cohort["current_core_national_walkability_index"] = np.log1p(cohort.context_walkability)
    legacy = json.loads((PARENT/"corrected_research/legacy_50/model_meta.json").read_text())["features"]
    context = json.loads((OPT/"selection_lock.json").read_text())["features"]
    columns = {"local_legacy_50":legacy,"corrected_context_35":context,
               "current_core_4":["current_core_population_density","current_core_median_household_income","current_core_job_density","current_core_national_walkability_index"],
               "dated_core_4":["dated_"+f for f in HISTORICAL_FEATURES]}
    if [len(columns[k]) for k in columns]!=[50,35,4,4]:
        raise ValueError("Unexpected pinned feature schemas")
    folds = list(GroupKFold(n_splits=plan["folds"]).split(cohort,groups=cohort.nta_code))
    assignments = np.full(len(cohort),-1)
    for fold,(training,testing) in enumerate(folds):
        if set(cohort.iloc[training].nta_code) & set(cohort.iloc[testing].nta_code):
            raise ValueError("Neighborhood leakage")
        assignments[testing] = fold
    output.mkdir(parents=True)
    shutil.copy2(plan_path,output/"plan.json")
    cohort.to_csv(output/"matched_cohort.csv",index=False)
    cohort[["camis","geoid","nta_code"]].assign(fold=assignments).to_csv(output/"fold_assignments.csv",index=False)
    lock = {"plan_sha256":file_hash(output/"plan.json"),"cohort_sha256":file_hash(output/"matched_cohort.csv"),
            "folds_sha256":file_hash(output/"fold_assignments.csv"),"features":columns,"parameters":PARAMS,
            "rounds":plan["rounds"],"created_before_fitting":True,"model_selection_performed":False}
    (output/"protocol_lock.json").write_text(json.dumps(lock,indent=2)+"\n")
    lock_hash = file_hash(output/"protocol_lock.json")
    raw = pd.read_parquet(PARENT/"frozen_root/data/restaurants_raw.parquet",columns=["first_snapshot","last_snapshot"])
    captures = pd.concat([raw.first_snapshot,raw.last_snapshot]).dropna().unique()
    records,metrics,paired,closure_audit = [],[],[],[]
    for rule in plan["closure_rules"]:
        variant,audit = closure_variant(cohort,captures,rule)
        closure_audit.append(audit)
        predictions = {key:np.full(len(cohort),np.nan) for key in [*columns,"constant_aft"]}
        for fold,(tr,te) in enumerate(folds):
            training,testing = variant.iloc[tr],variant.iloc[te]
            baseline = fit_constant_aft(training.y_lower,training.y_upper)
            predictions["constant_aft"][te] = baseline
            for name,features in columns.items():
                print(f"{rule}: fold {fold+1}/{len(folds)}, {name}",flush=True)
                model = fit_model(training,features,{"rounds":plan["rounds"]})
                predictions[name][te] = model.predict(research_matrix(testing,features))
                model.save_model(output/f"{rule}__{name}__fold_{fold}.json")
        for name,pred in predictions.items():
            if not np.isfinite(pred).all() or (pred<=0).any():
                raise ValueError("Incomplete or invalid OOF predictions")
            score = evaluate_predictions(pred,variant.y_lower,variant.y_upper,variant.nta_code)
            within = within_fold_concordance(predictions["constant_aft"],pred,variant.y_lower,variant.y_upper,variant.nta_code,assignments)
            metrics.append({"rule":rule,"model":name,"feature_count":len(columns.get(name,[])),"within_fold_concordance":within["candidate"],**score})
            part = variant[["camis","geoid","nta_code","borough","open_date","y_lower","y_upper"]].copy()
            part["fold"],part["rule"],part["model"] = assignments,rule,name
            part["median_years"],part["proxy_aft_3yr"] = pred,survival_prob(pred)
            records.append(part)
        for reference,candidate in [("constant_aft","dated_core_4"),("local_legacy_50","dated_core_4"),("corrected_context_35","dated_core_4"),("current_core_4","dated_core_4")]:
            paired.append({"rule":rule,"reference":reference,"candidate":candidate,
                "concordance":paired_concordance_delta(predictions[reference],predictions[candidate],variant.y_lower,variant.y_upper,variant.nta_code),
                "within_fold_concordance":within_fold_concordance(predictions[reference],predictions[candidate],variant.y_lower,variant.y_upper,variant.nta_code,assignments),
                "interval_nll":paired_nll_delta(predictions[reference],predictions[candidate],variant.y_lower,variant.y_upper,variant.nta_code)})
    all_predictions = pd.concat(records,ignore_index=True)
    all_predictions.to_csv(output/"oof_predictions.csv",index=False)
    metrics_flat = [{"rule":r["rule"],"model":r["model"],"rows":r["rows"],"features":r["feature_count"],
        "proxy_events":r["finite_event_intervals"],"interval_nll":r["interval_negative_log_likelihood"],
        "concordance":r["concordance"]["estimate"],"c_low":r["concordance"]["nta_cluster_bootstrap_95_ci"][0],
        "within_fold_concordance":r["within_fold_concordance"],
        "c_high":r["concordance"]["nta_cluster_bootstrap_95_ci"][1],
        "resolved_3yr_rows":r["resolved_3yr_rows"],"unresolved_3yr_rows":r["unresolved_3yr_rows"],
        "resolved_subset_brier":r["resolved_subset_brier_3yr"]} for r in metrics]
    pd.DataFrame(metrics_flat).to_csv(output/"model_comparison.csv",index=False)
    sensitivity = []
    for name in predictions:
        pivot = all_predictions[all_predictions.model.eq(name)].pivot(index="camis",columns="rule",values="median_years")
        for rule in plan["closure_rules"][1:]:
            sensitivity.append({"model":name,"rule":rule,"spearman_vs_primary":float(pivot[rule].corr(pivot[plan["closure_rules"][0]],method="spearman"))})
    report = {"schema":plan["schema"],"status":"completed_development_proxy_diagnostics","cohort":cohort_audit,
              "models":metrics,"paired_comparisons":paired,"closure_rules":closure_audit,"closure_rank_sensitivity":sensitivity,
              "protocol_lock_sha256":lock_hash,"source_baseline":"User-local frozen research outputs; no collaborator artifacts required",
              "new_final_holdout_claimed":False,"model_selection_performed":False,"production_deployment_allowed":False,
              "limitations":["Disappearance labels are not verified permanent closures.",
                "Only dated_core_4 has opening-time predictor provenance; other feature sets are retrospective diagnostics.",
                "Complete-case restriction changes the evaluated population; results are not directly comparable with full-cohort scores.",
                "All cohort records appeared in earlier CV; this is development analysis, not final independent validation.",
                "Metrics across different closure rules describe different targets and cannot rank label quality.",
                "Resolved-subset Brier is not population calibration or IPCW; unresolved cases remain unresolved.",
                "Paired bootstrap intervals condition on fitted predictions and do not include refitting uncertainty."]}
    (output/"results.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    if file_hash(output/"protocol_lock.json")!=lock_hash:
        raise ValueError("Protocol changed after fitting")
    for name in ("evaluate_matched_results.py","optimize_archive_model.py","survival_metrics.py","train_survival.py","train_archive_aft.py"):
        shutil.copy2(Path(__file__).with_name(name),output/name)
    manifest = {"status":"completed","parent_run":str(PARENT),"sources":{
        str(PARENT/"run_manifest.json"):file_hash(PARENT/"run_manifest.json"),str(OPT/"manifest.json"):file_hash(OPT/"manifest.json"),
        str(REPAIRS/"manifest.json"):file_hash(REPAIRS/"manifest.json")},
        "software":{name:importlib.metadata.version(name) for name in ("numpy","pandas","scipy","xgboost","scikit-learn")},
        "artifact_sha256":{p.name:file_hash(p) for p in output.iterdir() if p.is_file()}}
    (output/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print(json.dumps(cohort_audit,indent=2))


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True)
    parser.add_argument("--plan",default=Path(__file__).with_name("results_evaluation_plan.json"))
    args = parser.parse_args()
    run(args.output,args.plan)
