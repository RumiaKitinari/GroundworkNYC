"""Create shareable tables, scientific figures and a concise results briefing."""
import argparse
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import shutil
import zipfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from customer_access import file_hash
from evaluate_matched_results import verify_manifest

ROOT = Path(__file__).resolve().parents[1]
NAMES = {"local_legacy_50":"Local legacy, 50 features","corrected_context_35":"Current context, 35 features",
         "current_core_4":"Current-version core, 4 features",
         "dated_core_4":"Opening-time core, 4 features","constant_aft":"Training-fitted constant"}
PROFILES = {"neighborhood_cafe":"Neighborhood cafe","office_lunch":"Office lunch",
            "casual_dinner":"Casual dinner","premium_dinner":"Premium dinner"}
COLORS = ["#596778","#19758a","#16856e","#ad6730"]
MODEL_COLORS = ["#596778","#19758a","#93605c","#16856e","#ad6730"]


def build(evaluation,scenarios,validation,output):
    evaluation,scenarios,validation,output = map(lambda p:Path(p).resolve(),(evaluation,scenarios,validation,output))
    if output.exists() or not output.is_relative_to(ROOT/"deliverables"):
        raise ValueError("Use a new deliverables directory")
    verify_manifest(evaluation)
    verify_manifest(scenarios)
    verified = json.loads(validation.read_text())
    if verified["status"]!="passed":
        raise ValueError("Completed replay validation required")
    result = json.loads((evaluation/"results.json").read_text())
    second = json.loads((scenarios/"results.json").read_text())
    access_path = ROOT/"data/output/access_optimization/20261027_v3/results.json"
    access = json.loads(access_path.read_text())
    table = pd.read_csv(evaluation/"model_comparison.csv")
    primary = table[table.rule.eq("one_later_capture")].set_index("model").loc[list(NAMES)].reset_index()
    coverage = pd.read_csv(scenarios/"coverage.csv")
    responses = pd.read_csv(scenarios/"concept_response_checks.csv")
    output.mkdir(parents=True)
    figures = output/"figures"
    figures.mkdir()
    plt.rcParams.update({"font.size":11,"axes.titlesize":14,"axes.labelsize":11,"axes.spines.top":False,
                         "axes.spines.right":False,"figure.facecolor":"white","savefig.facecolor":"white"})
    def save(fig,name):
        fig.savefig(figures/(name+".png"),dpi=180,bbox_inches="tight")
        plt.close(fig)
    cohort = result["cohort"]
    fig,ax = plt.subplots(figsize=(10,3.5),layout="constrained")
    counts = [cohort["matched_development_rows"],cohort["development_rows_without_all_four_dated_features"],cohort["reserved_rows_excluded"]]
    bars = ax.barh(["Matched development evaluated","Development missing dated core","Reserved assessment excluded"],counts,color=[COLORS[2],"#aeb7c1",COLORS[0]])
    ax.bar_label(bars,labels=[f"{v:,}" for v in counts],padding=6)
    ax.set_xlim(0,max(counts)*1.2)
    ax.invert_yaxis()
    ax.set_xlabel("Restaurants; mutually exclusive groups")
    ax.set_title(f"Matched cohort: {cohort['source_rows']:,} frozen local records")
    save(fig,"01_cohort")
    fig,axes = plt.subplots(1,2,figsize=(12,4),layout="constrained")
    y = np.arange(len(primary))
    axes[0].scatter(primary.within_fold_concordance,y,c=MODEL_COLORS,s=65)
    axes[0].set_yticks(y,[NAMES[n] for n in primary.model]);axes[0].invert_yaxis()
    axes[0].axvline(.5,color="#8a939c",ls="--",lw=1)
    axes[0].set_xlim(0,1);axes[0].set_xlabel("Within-fold concordance; higher is better")
    axes[0].set_title("Discrimination remains weak")
    for i,value in enumerate(primary.within_fold_concordance):
        axes[0].annotate(f"{value:.3f}",(value,i),xytext=(7,0),textcoords="offset points",va="center")
    axes[1].scatter(primary.interval_nll,y,c=MODEL_COLORS,s=65)
    axes[1].set_yticks(y,[]);axes[1].invert_yaxis()
    axes[1].set_xlabel("Interval NLL; lower is better (detail scale)")
    axes[1].set_title("Primary proxy-target likelihood")
    axes[1].ticklabel_format(axis="x",useOffset=False)
    axes[1].set_xlim(primary.interval_nll.min()-.001,primary.interval_nll.max()+.002)
    for i,value in enumerate(primary.interval_nll):
        axes[1].annotate(f"{value:.6f}",(value,i),xytext=(6,0),textcoords="offset points",va="center",fontsize=9)
    fig.suptitle(f"Same {cohort['matched_development_rows']:,} restaurants, same neighborhood folds, fixed 200 rounds",fontsize=14)
    save(fig,"02_matched_models")
    event_counts = [r["finite_proxy_events"] for r in result["closure_rules"]]
    fig,ax = plt.subplots(figsize=(10,3.8),layout="constrained")
    x = np.arange(3)
    ax.barh(x,event_counts,color=COLORS[1],label="Finite disappearance-proxy interval")
    ax.barh(x,np.array([cohort["matched_development_rows"]]*3)-event_counts,left=event_counts,color="#dce2e7",label="Right-censored")
    ax.set_yticks(x,["At least one later capture","At least two later captures","At least three later captures"])
    ax.invert_yaxis();ax.set_xlim(0,cohort["matched_development_rows"])
    for i,value in enumerate(event_counts):
        ax.text(value/2,i,f"{value:,}",ha="center",va="center",color="white",fontweight="bold")
    ax.set_xlabel("Restaurants; stricter rules re-censor weak events, not verify closures")
    ax.set_title("Outcome assumptions materially change the target")
    ax.legend(loc="upper center",bbox_to_anchor=(.5,-.22),ncol=2,frameon=False,fontsize=9)
    save(fig,"03_closure_rules")
    fig,ax = plt.subplots(figsize=(11,4.7),layout="constrained")
    x = np.arange(len(coverage));width=.19
    for i,(column,label) in enumerate([("general_fit_rated","General fit"),("cuisine_screening_rated","Cuisine screening"),
                                      ("access_rated","Network access"),("huff_rated","Network Huff")]):
        bars = ax.bar(x+(i-1.5)*width,coverage[column],width,label=label,color=COLORS[i])
        ax.bar_label(bars,padding=2,fontsize=8)
    ax.set_xticks(x,[PROFILES[p] for p in coverage.profile]);ax.set_ylim(0,1140)
    ax.set_ylabel("Assessable synthetic properties out of 1,000")
    ax.set_title("Full-inventory scenario coverage, not predictive accuracy")
    ax.legend(loc="upper center",bbox_to_anchor=(.5,-.12),ncol=4,frameon=False,fontsize=9)
    save(fig,"04_scenario_coverage")
    fig,ax = plt.subplots(figsize=(11,4.5),layout="constrained")
    categories = ["Walking half-life","Outside option","Price","Uncertain cuisine labels"]
    for i,(profile,record) in enumerate(access["profiles"].items()):
        grouped = [[],[],[],[]]
        for entry in record["sensitivities"]:
            index = {"walking_half_life":0,"outside_option":1,"average_check":2,"all_uncertain_labels_as_full_competitors":3}[entry["parameter"]]
            grouped[index].append(entry["top_50_common_retention"]*100)
        for j,values in enumerate(grouped):
            offset = (i-1.5)*.12
            ax.plot([j+offset]*len(values),values,"o",color=COLORS[i],label=PROFILES[profile] if j==0 else None)
    ax.set_xticks(range(4),categories);ax.set_ylim(0,105)
    ax.set_ylabel("Top-50 retention among common assessable properties (%)")
    ax.set_title("Uncertain competitor labels can dominate parameter sensitivity")
    ax.legend(loc="upper center",bbox_to_anchor=(.5,-.14),ncol=2,frameon=False,fontsize=9)
    save(fig,"05_ranking_sensitivity")
    dated = next(r for r in result["models"] if r["rule"]=="one_later_capture" and r["model"]=="dated_core_4")
    fig,axes = plt.subplots(1,2,figsize=(11,4.2),layout="constrained")
    axes[0].bar(["Resolved at 3 years","Unresolved at 3 years"],[dated["resolved_3yr_rows"],dated["unresolved_3yr_rows"]],color=[COLORS[2],"#aeb7c1"])
    axes[0].set_ylabel("Restaurants");axes[0].set_title("Most horizon outcomes remain unresolved")
    bins = dated["calibration_bins"]
    axes[1].plot([0,1],[0,1],"--",color="#9ba4ad")
    axes[1].scatter([b["mean_prediction"] for b in bins],[b["observed_survival"] for b in bins],
                    s=[35+100*b["rows"]/dated["resolved_3yr_rows"] for b in bins],color=COLORS[2])
    for b in bins:
        axes[1].annotate(f"n={b['rows']:,}",(b["mean_prediction"],b["observed_survival"]),xytext=(4,6),textcoords="offset points",fontsize=8)
    axes[1].set_xlim(0,1);axes[1].set_ylim(0,1)
    axes[1].set_xlabel("AFT-derived 3-year proxy survival probability")
    axes[1].set_ylabel("Resolved-subset observed proxy survival")
    axes[1].set_title("Conditional diagnostic, not population calibration")
    save(fig,"06_unresolved_calibration")
    for path in (evaluation/"model_comparison.csv",scenarios/"coverage.csv",scenarios/"ranking_comparisons.csv",scenarios/"concept_response_checks.csv",scenarios/"illustrative_scenarios.json"):
        shutil.copy2(path,output/path.name)
    shutil.copy2(validation,output/"validation.json")
    shutil.copy2(evaluation/"plan.json",output/"evaluation_plan.json")
    pd.DataFrame(result["closure_rank_sensitivity"]).to_csv(output/"closure_rank_sensitivity.csv",index=False)
    paired = next(p for p in result["paired_comparisons"] if p["rule"]=="one_later_capture" and p["reference"]=="local_legacy_50")
    delta = paired["within_fold_concordance"]
    nll = paired["interval_nll"]
    vintage = next(p for p in result["paired_comparisons"] if p["rule"]=="one_later_capture" and p["reference"]=="current_core_4")
    lines = ["# Groundwork NYC: Results Briefing", "", "October 28, 2026", "",
        "## Executive Finding", "",
        "Using our frozen local outputs, we completed a matched development evaluation and full-inventory second-stage scenario checks. "
        "Opening-time features improve the temporal defensibility of the inputs, but do not yet demonstrate a convincing predictive improvement over the original 50-feature local baseline. "
        "Disappearance labels remain proxy evidence, not verified permanent closures.", "",
        "## Study Design", "",
        f"The frozen cohort contains {cohort['source_rows']:,} restaurants. We excluded all {cohort['reserved_rows_excluded']:,} reserved-assessment records and "
        f"{cohort['development_rows_without_all_four_dated_features']:,} development records without all four dated core features. "
        f"The matched evaluation uses {cohort['matched_development_rows']:,} restaurants, three identical neighborhood folds, and fixed 200-round XGBoost AFT settings. "
        "No new tuning, early stopping, model selection, or independent-holdout claim was made. All source records appeared in earlier research CV. "
        f"The source context is frozen as of {second['source_as_of']}; later automatic data refreshes were deliberately not substituted during comparison.", "",
        "The dated core includes population density, median household income, job density, and EPA walkability, each selected using source availability at the inferred opening date. "
        "The current-version four-variable control uses the same conceptual variables and matching log1p transforms. It was added after initial development diagnostics to distinguish vintage from feature-count changes; "
        "this protocol refinement is exploratory and is recorded before the additional fits. Missingness can still differ between vintages.", "",
        "![Matched cohort](figures/01_cohort.png)", "", "## First-Stage Results", "",
        "| Model | Within-Fold C | Pooled OOF C | Interval NLL | Resolved-Subset Brier |",
        "| --- | ---: | ---: | ---: | ---: |"]
    for r in primary.itertuples():
        lines.append(f"| {NAMES[r.model]} | {r.within_fold_concordance:.4f} | {r.concordance:.4f} | {r.interval_nll:.6f} | {r.resolved_subset_brier:.4f} |")
    lines += ["",f"Dated-core minus local-legacy within-fold C: {delta['candidate_minus_reference']:+.4f}; paired neighborhood-bootstrap 95% interval "
        f"[{delta['nta_bootstrap_95_ci'][0]:+.4f}, {delta['nta_bootstrap_95_ci'][1]:+.4f}]. "
        f"Interval-NLL difference: {nll['candidate_minus_reference']:+.6f}; 95% interval [{nll['nta_bootstrap_95_ci'][0]:+.6f}, {nll['nta_bootstrap_95_ci'][1]:+.6f}]. "
        "Both intervals include zero. The bootstrap conditions on fitted predictions; it does not include model-refitting uncertainty.", "",
        f"Controlling feature count, dated-core minus current-core within-fold C is {vintage['within_fold_concordance']['candidate_minus_reference']:+.4f}, "
        f"with paired 95% interval [{vintage['within_fold_concordance']['nta_bootstrap_95_ci'][0]:+.4f}, {vintage['within_fold_concordance']['nta_bootstrap_95_ci'][1]:+.4f}]. "
        f"Its interval-NLL difference is {vintage['interval_nll']['candidate_minus_reference']:+.6f}, with 95% interval "
        f"[{vintage['interval_nll']['nta_bootstrap_95_ci'][0]:+.6f}, {vintage['interval_nll']['nta_bootstrap_95_ci'][1]:+.6f}]. "
        "This is a vintage/missingness diagnostic on an exposed development cohort, not an independent causal or forecasting test.", "",
        "The controlled four-variable likelihood comparison favors dated inputs in this exploratory run. Its within-fold concordance difference interval is positive, "
        "while the corresponding pooled-concordance difference interval includes zero. This distinction and the development-only protocol refinement prevent an independent-confirmation claim.", "",
        "Within-fold C compares only predictions from the same fold model. Pooled constant-baseline C can depart from 0.5 because training-fitted intercepts differ across folds; "
        "it must not be interpreted as a worse-than-chance constant predictor. Both C definitions are retained for transparency.", "",
        "![Matched model comparison](figures/02_matched_models.png)", "",
        f"Only {dated['resolved_3yr_rows']:,} of {dated['rows']:,} records have identifiable three-year proxy outcomes; {dated['unresolved_3yr_rows']:,} remain unresolved. "
        "The reported Brier score and calibration plot apply only to the resolved subset, are not IPCW/population calibration, and do not establish real-world success probability.", "",
        "![Unresolved outcomes and conditional calibration](figures/06_unresolved_calibration.png)", "",
        "## Closure-Rule Sensitivity", "",
        f"Requiring one, two, or three later archive captures leaves {event_counts[0]:,}, {event_counts[1]:,}, and {event_counts[2]:,} finite proxy-event intervals. "
        "Weak events are re-censored at the last observed lower bound, not assumed to survive until the final archive. "
        "Archive opportunities are inferred from consolidated endpoints, not per-business independent closure checks. "
        "These definitions change the target: lower loss across different rules is not evidence that a stricter rule is more accurate. "
        "See model_comparison.csv and closure_rank_sensitivity.csv for all configurations, including unfavorable results.", "",
        "![Closure-rule sensitivity](figures/03_closure_rules.png)", "",
        "## Second-Stage Results", "",
        "All four concepts were evaluated on the same complete 1,000-property synthetic inventory and 2,327 tract origins. "
        "General fit, cuisine-supported screening, network customer access, and repaired-anchor Huff scenarios were compared on common assessable candidates. "
        "Coverage and rank agreement are engineering/scenario diagnostics, not customer-demand accuracy.", "",
        "| Concept | General Fit | Cuisine Screening | Network Access | Huff |", "| --- | ---: | ---: | ---: | ---: |"]
    for r in coverage.itertuples():
        lines.append(f"| {PROFILES[r.profile]} | {r.general_fit_rated} | {r.cuisine_screening_rated} | {r.access_rated} | {r.huff_rated} |")
    lines += ["", "![Scenario coverage](figures/04_scenario_coverage.png)", "",
        "Sixteen one-factor checks varied price, format, audience, or trading period across the four concepts. "
        "A 20% price increase never increased affordability-adjusted opportunity mass. Format, audience, and trading-period changes affected opportunity values and rankings. "
        "Raw opportunity units are weighted resident/job context, not unique people or visits; magnitudes across different concept weights should not be compared as sales forecasts.", "",
        "The previous full-inventory sensitivity experiments are retained: classifying all tract-matched uncertain labels as full competitors reduced top-50 retention to 4-76%, "
        "depending on concept. This is an intentionally conservative stress scenario, not a confidence interval or an inferred classification. "
        "Competitor-label quality is a material second-stage uncertainty. No weights were chosen to maximize attractive recommendations.", "",
        "![Ranking sensitivity](figures/05_ranking_sensitivity.png)", "",
        "## Representative Scenarios", "",
        "illustrative_scenarios.json contains the leading synthetic scenario under general fit, customer access, and Huff for each concept. "
        "They demonstrate component tradeoffs, not verified listings or evidence that the selected properties are commercially best. "
        "All examples retain the same frozen inventory; no real asking rents, availability, or transaction outcomes were validated here.", "",
        "## Conclusions And Limits", "",
        "- Temporal provenance is improved by the dated core; current-context and legacy results remain retrospective diagnostics.",
        "- The primary matched comparison does not establish superiority over the local baseline, and concordance remains modest.",
        "- Closure definitions materially change labels and predicted-duration ranks; permanent-exit verification is still unresolved.",
        "- Opening dates are inferred from pre-permit history, not verified first-trading dates. Identity changes remain possible and censoring may be informative.",
        "- The four-feature complete-case cohort is more recent and is not representative of all 18,860 records; do not compare these scores directly with earlier full-cohort scores.",
        "- Neighborhood grouping does not remove all adjacent-area correlation, ownership dependence, or unmeasured temporal shifts.",
        "- Stage two is not calibrated against observed visits, revenue, or choice outcomes; no end-to-end survival/Huff accuracy is claimed.",
        "- The reserved set was not used in these fits. A genuinely independent final evaluation still requires new evidence or a protected future cohort.", "",
        "## Verification And Reproduction", "",
        f"Replay validation checked {verified['native_models_replayed']} native fold models, {verified['prediction_rows_checked']:,} saved prediction rows, "
        f"{verified['parent_artifacts_checked']} original frozen artifacts, and all four 1,000-property scenario inventories. "
        "No source dataset, live model, frontend, or previous research output was replaced. No collaborator model outputs or uploads were required.", "",
        "Commands, using new output names, from the project root:", "", "```sh",
        ".venv/bin/python codes/evaluate_matched_results.py --output data/output/results_evaluation/NEW_RUN",
        ".venv/bin/python codes/evaluate_results_scenarios.py --output data/output/results_scenarios/NEW_RUN",
        ".venv/bin/python codes/validate_results_evaluation.py --run data/output/results_evaluation/20261028_v2 --scenarios data/output/results_scenarios/20261028_v1 --output data/output/results_validation/NEW_VALIDATION.json",
        ".venv/bin/python -m pytest codes demo -q", "```", "",
        "This shareable package contains aggregate summaries and synthetic examples, not the restaurant training matrix or fitted model files. "
        "Those remain in the private data/output directories listed in source_index.json."]
    (output/"RESULTS.md").write_text("\n".join(lines)+"\n")
    notes = ("# Briefing Notes For Atharv\n\n"
        "We are using our frozen local outputs as the baseline; this work does not depend on obtaining anyone else's model files. "
        f"We completed matched three-fold neighborhood evaluation on {cohort['matched_development_rows']:,} restaurants with all four dated features, "
        f"excluding {cohort['reserved_rows_excluded']:,} reserved-assessment records. All models used the same rows, folds, proxy labels and fixed training settings.\n\n"
        f"The opening-time four-feature model reached within-fold concordance {dated['within_fold_concordance']:.3f} and interval NLL {dated['interval_negative_log_likelihood']:.6f}. "
        f"Its concordance difference versus the local legacy baseline was {delta['candidate_minus_reference']:+.3f}, with a paired 95% interval "
        f"[{delta['nta_bootstrap_95_ci'][0]:+.3f}, {delta['nta_bootstrap_95_ci'][1]:+.3f}]. "
        "This is better historical provenance, but not convincing evidence of a predictive improvement.\n\n"
        f"A same-four-variable current-vintage control had within-fold concordance {vintage['within_fold_concordance']['reference']:.3f}. "
        "The dated version is favored in the exploratory matched likelihood comparison, but the check was added as a development diagnostic and requires independent replication.\n\n"
        f"We tested three disappearance rules, producing {event_counts[0]:,}, {event_counts[1]:,}, and {event_counts[2]:,} proxy events. "
        "The rules materially change the target and rankings; disappearance still does not establish permanent closure.\n\n"
        "For stage two, we compared general suitability, cuisine screening, inverse walkability and Huff on all 1,000 synthetic properties. "
        "Network access covered 986-988 properties and repaired-anchor Huff covered 704-853 depending on concept. "
        "Sixteen one-factor checks confirmed responses to price, format, audience and trading hours; price increases never increased affordability-adjusted opportunity mass. "
        "Cuisine-label uncertainty remains a major source of ranking instability.\n\n"
        f"We saved and replayed all {verified['native_models_replayed']} fold models and {verified['prediction_rows_checked']:,} prediction rows. "
        "The report includes model comparisons, closure sensitivity, coverage, calibration limitations, figures and synthetic examples. "
        "These are development proxy results and scenario checks, not independent final validation or verified restaurant-success forecasts.\n")
    (output/"BRIEFING_NOTES.md").write_text(notes)
    image_html = "".join(f'<section><img src="figures/{p.name}" alt="{escape(p.stem.replace("_"," "))}"></section>' for p in sorted(figures.glob("*.png")))
    html = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Groundwork NYC Results Briefing</title><style>body{font:16px/1.55 system-ui,sans-serif;color:#182c35;margin:0;background:#fff;letter-spacing:0}'
        'main{max-width:1100px;margin:auto;padding:36px 24px}h1{font-size:30px;line-height:1.2}h2{font-size:21px;margin-top:32px}'
        'section{border-top:1px solid #d9e1e5;padding:20px 0}img{display:block;width:100%;height:auto}table{border-collapse:collapse;width:100%;font-size:13px}'
        'th,td{text-align:left;padding:8px;border-bottom:1px solid #d9e1e5}th{background:#edf4f3}.table{overflow:auto}a{color:#146b72}'
        '@media print{main{padding:0}section{break-inside:avoid}img{max-height:650px;object-fit:contain}}'
        '</style><main><h1>Groundwork NYC: Results Briefing</h1><p>October 28, 2026 | Frozen local outputs | Development analysis</p>'
        '<p><strong>Finding:</strong> Dated features improve input provenance, but the matched results do not establish a convincing predictive improvement. '
        'Closure labels remain proxies. Stage-two results are full-inventory scenario checks, not observed demand validation.</p>'
        '<p><a href="RESULTS.md">Full report and limitations</a> | <a href="BRIEFING_NOTES.md">Briefing notes</a></p>'
        '<h2>Primary Matched Comparison</h2><div class="table">'+primary[["model","rows","within_fold_concordance","concordance","interval_nll","resolved_subset_brier"]].to_html(index=False,float_format=lambda v:f"{v:.4f}",border=0)+
        '</div><p>Both the dated-versus-legacy concordance and likelihood difference intervals include zero. '
        f'Only {dated["resolved_3yr_rows"]:,} of {dated["rows"]:,} three-year proxy outcomes are resolved; calibration results apply to that subset only.</p>'+image_html+
        f'<h2>Audit</h2><p>{verified["native_models_replayed"]} saved native fold models and {verified["prediction_rows_checked"]:,} OOF predictions replayed. No reserved-assessment records were used. '
        'No production model was promoted. See validation.json and source_index.json.</p></main></html>')
    (output/"RESULTS.html").write_text(html)
    index = {"evaluation_run":str(evaluation.relative_to(ROOT)),"scenario_run":str(scenarios.relative_to(ROOT)),
             "evaluation_manifest_sha256":file_hash(evaluation/"manifest.json"),"scenario_manifest_sha256":file_hash(scenarios/"manifest.json"),
        "validation_sha256":file_hash(validation),"sensitivity_source":str(access_path.relative_to(ROOT)),"sensitivity_source_sha256":file_hash(access_path),
        "report_builder_sha256":file_hash(__file__),"matplotlib_version":matplotlib.__version__}
    (output/"source_index.json").write_text(json.dumps(index,indent=2)+"\n")
    manifest = {"status":"completed_results_package","created_at":datetime.now(timezone.utc).isoformat(),
        "baseline":"user_local_frozen_outputs","private_training_data_included":False,"production_deployment_allowed":False,
        "artifacts":{str(p.relative_to(output)):file_hash(p) for p in sorted(output.rglob("*")) if p.is_file()}}
    (output/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    archive = output.with_suffix(".zip")
    if archive.exists():
        raise ValueError("Do not overwrite an earlier shareable archive")
    with zipfile.ZipFile(archive,"w",compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                bundle.write(path,str(Path(output.name)/path.relative_to(output)))
    print(json.dumps({"package":str(output),"archive":str(archive),"figures":len(list(figures.glob("*.png"))),"artifacts":len(manifest["artifacts"])},indent=2))


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation",required=True)
    parser.add_argument("--scenarios",required=True)
    parser.add_argument("--validation",required=True)
    parser.add_argument("--output",required=True)
    args = parser.parse_args()
    build(args.evaluation,args.scenarios,args.validation,args.output)
