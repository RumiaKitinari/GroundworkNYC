"""Frozen full-inventory stage-two diagnostics, separate from accuracy claims."""
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"demo"))
from app import PROFILE_WEIGHTS
from scoring import Concept, ScreeningModel
from audit_access_optimization import comparison
from customer_access import AccessConcept, access_features, file_hash, load_access_bundle
from evaluate_matched_results import PARENT, verify_manifest


def run(output):
    output = Path(output).resolve()
    if output.exists() or not output.is_relative_to(ROOT/"data/output"):
        raise ValueError("Use a new private data/output directory")
    repair = ROOT/"data/output/access_optimization/20261027_v3"
    verify_manifest(repair,key="artifacts")
    verify_manifest(PARENT,"run_manifest.json")
    origins,properties,routes,manifest = load_access_bundle(ROOT/"data/output/feature_engineering/20261027_v3","2026-10-28")
    frozen = PARENT/"frozen_root/data"
    if file_hash(frozen/"master_tract_features.csv")!=manifest["sources"]["master"]["sha256"]:
        raise ValueError("Stage-one and stage-two master releases differ")
    master = pd.read_csv(frozen/"master_tract_features.csv",dtype={"geoid":str},keep_default_na=False)
    restaurants = pd.read_csv(frozen/"current_restaurants.csv",dtype=str,keep_default_na=False)
    if file_hash(frozen/"current_restaurants.csv")!=json.loads((repair/"results.json").read_text())["sources"]["restaurants"]:
        raise ValueError("Competition inventory differs from pinned scenario audit")
    model = ScreeningModel(master.to_dict("records"),restaurants.to_dict("records"))
    lookup = master.set_index("geoid").to_dict("index")
    profiles = {"neighborhood_cafe":("coffee_tea","coffee",AccessConcept("quick_service",18,"residents","morning")),
                "office_lunch":("sandwiches_deli","counter_service",AccessConcept("quick_service",18,"workers","lunch")),
                "casual_dinner":("italian","restaurant",AccessConcept("casual",35,"residents","evening")),
                "premium_dinner":("steakhouse","fine_dining",AccessConcept("fine_dining",110,"destination","evening"))}
    output.mkdir(parents=True)
    summaries,rankings,responses,examples = [],[],[],[]
    for name,(cuisine,profile,access_concept) in profiles.items():
        print("Scenario comparison: "+name,flush=True)
        weights = PROFILE_WEIGHTS[profile]
        concept = Concept(cuisine=cuisine,service_style=access_concept.service_style,average_check=access_concept.average_check,
                          audience=access_concept.audience,daypart=access_concept.daypart)
        general_weights = {key:weight for key,weight in weights.items() if key!="market_gap"}
        general,cuisine_values,modes,coverages = [],[],[],[]
        for row in properties.itertuples():
            tract = {"geoid":row.geoid,**lookup[row.geoid]}
            full = model.evaluate(tract,concept,weights,profile)
            base = model.evaluate(tract,concept,general_weights,profile)
            general.append(base["opportunity"] if base["assessment_policy"]["recommendation_eligible"] else np.nan)
            cuisine_values.append(full["opportunity"] if full["assessment_policy"]["recommendation_eligible"] else np.nan)
            modes.append(full["concept_evidence"]["support"]["mode"])
            coverages.append(full["confidence_score"])
        access = access_features(origins,properties,routes,access_concept,manifest["config"])
        prior = pd.read_csv(repair/(name+".csv"),dtype={"property_id":str})
        if prior.property_id.tolist()!=properties.property_id.tolist():
            raise ValueError("Scenario inventory order differs")
        frame = properties[["property_id","geoid","borough","inventory_type"]].copy()
        frame["general_fit_no_cuisine"] = general
        frame["cuisine_screening"] = cuisine_values
        frame["cuisine_support_mode"] = modes
        frame["screening_coverage_pct"] = coverages
        frame["customer_access_percentile"] = access.inverse_walkability_percentile
        frame["customer_access_opportunities"] = access.price_adjusted_access_opportunities
        frame["huff_opportunities"] = prior.repaired_opportunities
        frame["huff_percentile"] = frame.huff_opportunities.rank(pct=True)*100
        frame["uncertain_competition_opportunities"] = prior.uncertain_competition_opportunities
        frame.to_csv(output/(name+".csv"),index=False)
        summaries.append({"profile":name,"properties":len(frame),"general_fit_rated":int(frame.general_fit_no_cuisine.notna().sum()),
            "cuisine_screening_rated":int(frame.cuisine_screening.notna().sum()),"access_rated":int(frame.customer_access_percentile.notna().sum()),
            "huff_rated":int(frame.huff_opportunities.notna().sum()),"support_modes":pd.Series(modes).value_counts().to_dict()})
        for label,column in [("cuisine_screening","cuisine_screening"),("network_access","customer_access_percentile"),("network_huff","huff_percentile")]:
            rankings.append({"profile":name,"reference":"general_fit_no_cuisine","alternative":label,
                             **comparison(frame.general_fit_no_cuisine,frame[column])})
        for kind,column in [("general_fit","general_fit_no_cuisine"),("customer_access","customer_access_percentile"),("huff","huff_opportunities")]:
            if frame[column].notna().any():
                index = frame[column].idxmax()
                item = frame.loc[index]
                examples.append({"profile":name,"selection_basis":kind,"property_id":item.property_id,"geoid":item.geoid,
                    "borough":item.borough,"inventory_type":"synthetic_scenario_not_real_listing",
                    "general_fit":float(item.general_fit_no_cuisine),"cuisine_screening":float(item.cuisine_screening),
                    "customer_access_percentile":None if pd.isna(item.customer_access_percentile) else float(item.customer_access_percentile),
                    "huff_percentile":None if pd.isna(item.huff_percentile) else float(item.huff_percentile),
                    "cuisine_support_mode":item.cuisine_support_mode,"scope":"Illustrative maximum under each component, not evidence of the best real property"})
        alternatives = {"price_plus_20pct":replace(access_concept,average_check=access_concept.average_check*1.2),
            "format_only":replace(access_concept,service_style="casual" if access_concept.service_style=="quick_service" else "fine_dining" if access_concept.service_style=="casual" else "quick_service"),
            "audience_only":replace(access_concept,audience="workers" if access_concept.audience!="workers" else "residents"),
            "daypart_only":replace(access_concept,daypart="evening" if access_concept.daypart!="evening" else "morning")}
        for change,alternative in alternatives.items():
            varied = access_features(origins,properties,routes,alternative,manifest["config"])
            before,after = access.price_adjusted_access_opportunities,varied.price_adjusted_access_opportunities
            common = before.notna() & after.notna()
            differences = after[common]-before[common]
            if change=="price_plus_20pct" and (differences>1e-7).any():
                raise ValueError("Higher price increased affordability-adjusted opportunity mass")
            if not varied.visit_forecast.isna().all():
                raise ValueError("Scenario manufactured observed visit forecasts")
            responses.append({"profile":name,"changed_factor":change,"common_properties":int(common.sum()),
                "properties_with_changed_raw_opportunities":int((differences.abs()>1e-7).sum()),
                "median_raw_change":float(differences.median()),
                **comparison(access.inverse_walkability_percentile,varied.inverse_walkability_percentile)})
    pd.DataFrame(rankings).to_csv(output/"ranking_comparisons.csv",index=False)
    pd.DataFrame(responses).to_csv(output/"concept_response_checks.csv",index=False)
    pd.DataFrame([{k:v for k,v in r.items() if k!="support_modes"} for r in summaries]).to_csv(output/"coverage.csv",index=False)
    (output/"illustrative_scenarios.json").write_text(json.dumps(examples,indent=2,allow_nan=False)+"\n")
    report = {"status":"completed_full_inventory_scenario_diagnostics","summaries":summaries,"ranking_comparisons":rankings,
        "response_checks":responses,"source_as_of":manifest["as_of"],"properties":len(properties),"origin_tracts":len(origins),
        "cuisine_support_definition":"Source supply coverage, not observed consumer demand",
        "predictive_accuracy_evaluated":False,"survival_blend_evaluated":False,
        "limitations":["All properties are synthetic scenarios, not verified listings.",
          "General and cuisine screening are uncalibrated indices, not independent ground truth.",
          "Ranking comparisons use common assessable candidates; missing candidates are reported separately.",
          "No observed visits, sales, or consumer-choice outcomes are available for predictive validation.",
          "Huff utilities and tract-origin approximations remain assumptions; no best weights are selected.",
          "The repaired competitor-anchor scenario is offline, not automatically the live access surface.",
          "Stage-two use of current context is prospective and must not be backdated into stage-one cohorts."]}
    (output/"results.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    for name,path in [("evaluate_results_scenarios.py",Path(__file__)),("scoring.py",ROOT/"demo/scoring.py"),
                      ("evidence_policy.py",ROOT/"demo/evidence_policy.py"),("customer_access.py",Path(__file__).with_name("customer_access.py"))]:
        shutil.copy2(path,output/name)
    (output/"manifest.json").write_text(json.dumps({"status":"completed","created_at":datetime.now(timezone.utc).isoformat(),
        "sources":{str(PARENT/"run_manifest.json"):file_hash(PARENT/"run_manifest.json"),str(repair/"manifest.json"):file_hash(repair/"manifest.json"),
                   str(ROOT/"data/output/feature_engineering/20261027_v3/manifest.json"):file_hash(ROOT/"data/output/feature_engineering/20261027_v3/manifest.json")},
        "artifact_sha256":{p.name:file_hash(p) for p in output.iterdir() if p.is_file()}},indent=2)+"\n")
    print(json.dumps(summaries,indent=2))


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True)
    run(parser.parse_args().output)
