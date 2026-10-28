"""Prepare full-inventory review queues and point-in-time feature readiness.

Never edits the master, asserts a new cuisine, verifies a closure, or promotes
a model. Review priority uses prospective candidate geography, not outcomes.
"""
import argparse
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import re
import shutil

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from customer_access import file_hash, xy
from features import HISTORICAL_FEATURES, build_historical_features, load_historical_snapshots
from label_cuisines import label_row
from model_feature_catalog import SPECS
from verify_archived_operating_pairs import capture_date, capture_url

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "data/output/research_runs/20261027_archive_aft_v2"
ACCESS = ROOT / "data/output/access_optimization/20261027_v3"
TAXONOMY_REVIEW = {"Fusion", "Polynesian", "Chilean", "Chinese/Cuban", "Chinese/Japanese",
                   "Hawaiian", "Afghan", "Bottled Beverages", "Continental"}


def normalized(value):
    return re.sub(r"[^A-Z0-9]", "", str(value).upper()) if pd.notna(value) else ""


def valid_coordinates(frame, lat="latitude", lon="longitude"):
    return (pd.to_numeric(frame[lat], errors="coerce").between(40.45,40.96)
            & pd.to_numeric(frame[lon], errors="coerce").between(-74.31,-73.64))


def identity_agrees(current, archive):
    pairs = [("dba","dba"),("boro","boro"),("building","building"),("street","street"),("zipcode","zipcode")]
    return all(normalized(current[a]) and normalized(current[a]) == normalized(archive[b]) for a,b in pairs)


def review_queue(restaurants, raw, master_geoids, prioritized):
    if restaurants.camis.duplicated().any() or raw.camis.duplicated().any():
        raise ValueError("Unique CAMIS source identities required")
    active = restaurants[restaurants.active_establishment.astype(str).str.lower().isin(["true","1"])].copy()
    labels = [label_row(r.cuisine_description if pd.notna(r.cuisine_description) else "", r.dba if pd.notna(r.dba) else "") for r in active.itertuples()]
    active["current_cuisine_50"] = [r[0] for r in labels]
    active["label_source"] = [r[1] for r in labels]
    active["coordinate_usable"] = valid_coordinates(active)
    active["tract_usable"] = active.geoid.isin(master_geoids)
    active["taxonomy_review"] = active.cuisine_description.isin(TAXONOMY_REVIEW)
    active["cuisine_review"] = ~active.label_source.isin(["direct","keyword"]) | active.taxonomy_review
    active["nearby_priority_candidates"] = 0
    active["nearest_priority_candidate_meters"] = np.nan
    located = active.coordinate_usable
    if len(prioritized) and located.any():
        tree = cKDTree(xy(prioritized.latitude, prioritized.longitude))
        points = xy(active.loc[located,"latitude"],active.loc[located,"longitude"])
        active.loc[located,"nearby_priority_candidates"] = tree.query_ball_point(points,2400,return_length=True)
        active.loc[located,"nearest_priority_candidate_meters"] = tree.query(points)[0]
    queue = active[active.cuisine_review | ~active.coordinate_usable | ~active.tract_usable].copy()
    archived = raw.set_index("camis")
    proposals = []
    for row in queue.to_dict("records"):
        proposal = {"camis":row["camis"], "archive_identity_agrees":False,
                    "proposed_cuisine_50":"", "proposed_latitude":np.nan, "proposed_longitude":np.nan,
                    "proposal_source":"", "proposal_status":"no_supported_local_candidate"}
        if row["camis"] in archived.index:
            old = archived.loc[row["camis"]]
            agrees = identity_agrees(row,old)
            proposal["archive_identity_agrees"] = bool(agrees)
            if agrees:
                old_label, old_source = label_row(old.cuisine if pd.notna(old.cuisine) else "", old.dba if pd.notna(old.dba) else "")
                if old_source in {"direct","keyword"} and old.cuisine not in TAXONOMY_REVIEW and row["cuisine_review"]:
                    proposal["proposed_cuisine_50"] = old_label
                if not row["coordinate_usable"] and 40.45 <= old.lat <= 40.96 and -74.31 <= old.lon <= -73.64:
                    proposal.update(proposed_latitude=float(old.lat),proposed_longitude=float(old.lon))
                if proposal["proposed_cuisine_50"] or np.isfinite(proposal["proposed_latitude"]):
                    proposal.update(proposal_status="review_required_not_applied",proposal_source="same_CAMIS_archive_name_and_address_match")
            else:
                proposal["proposal_status"] = "archive_identity_conflict_or_missing_identity"
        proposals.append(proposal)
    queue = queue.merge(pd.DataFrame(proposals),on="camis",validate="one_to_one")
    queue["review_priority"] = np.select([
        ~queue.coordinate_usable | ~queue.tract_usable,
        queue.nearby_priority_candidates.gt(0)], ["unlocated_cannot_rank_geographically","near_ranked_candidate"], default="remaining_inventory")
    queue["reviewer"] = ""
    queue["reviewed_on"] = ""
    queue["evidence_url"] = ""
    queue["approved_cuisine_50"] = ""
    queue["approved_latitude"] = ""
    queue["approved_longitude"] = ""
    queue["identity_resolution"] = ""
    queue["review_notes"] = ""
    queue["applied_to_master"] = False
    return queue.sort_values(["nearby_priority_candidates","camis"],ascending=[False,True]), active


def snapshot_inventory(path):
    """Capture-time names/addresses, never consolidated final DBA names."""
    columns = ["CAMIS","DBA","BORO","BUILDING","STREET","ZIPCODE"]
    with Path(path).open("rb") as stream:
        compressed = stream.read(2) == b"\x1f\x8b"
    opener = gzip.open if compressed else open
    identities = {}
    with opener(path,"rt",encoding="utf-8-sig",newline="") as stream:
        for chunk in pd.read_csv(stream,usecols=columns,dtype=str,keep_default_na=False,chunksize=100000):
            for row in chunk.drop_duplicates().itertuples(index=False,name=None):
                camis,name,boro,building,street,zip_code = row
                identity = tuple(normalized(v) for v in (name,boro,building,street,zip_code))
                identities.setdefault(camis,set()).add(identity)
    stable = {camis:next(iter(values)) for camis,values in identities.items() if len(values)==1 and all(next(iter(values)))}
    by_name = {}
    for identity in stable.values():
        by_name.setdefault(identity[0],set()).add(identity[1:])
    return stable, {name:len(addresses) for name,addresses in by_name.items()}, len(identities)-len(stable)


def coordinate_overlay(restaurants, queue, geography, master_geoids):
    features = geography["features"]
    polygons = [shape(feature["geometry"]) for feature in features]
    tree = STRtree(polygons)
    overlay = restaurants.copy()
    overlay["coordinate_repair_basis"] = "original_integrated_record"
    audit = []
    for row in queue[queue.proposed_latitude.notna()].itertuples():
        point = Point(row.proposed_longitude,row.proposed_latitude)
        matches = [int(i) for i in tree.query(point) if polygons[int(i)].covers(point)]
        matched_geoids = {str(features[i]["properties"]["geoid"]) for i in matches} & master_geoids
        record = {"camis":row.camis,"proposed_latitude":row.proposed_latitude,"proposed_longitude":row.proposed_longitude,
                  "original_geoid":row.geoid,"resolved_geoid":"","status":"withheld_no_unique_tract"}
        if len(matched_geoids)==1 and row.archive_identity_agrees:
            geoid = next(iter(matched_geoids))
            index = overlay.index[overlay.camis.eq(row.camis)]
            if len(index)!=1 or valid_coordinates(overlay.loc[index]).any():
                raise ValueError("Only uniquely identified missing coordinates may be restored")
            overlay.loc[index,["latitude","longitude","geoid"]] = [row.proposed_latitude,row.proposed_longitude,geoid]
            overlay.loc[index,"coordinate_repair_basis"] = "archived_same_CAMIS_name_address_and_unique_tract"
            record.update(resolved_geoid=geoid,status="restored_in_candidate_overlay_not_published")
        audit.append(record)
    return overlay,pd.DataFrame(audit)


def historical_chain_candidates(cohort, captures):
    result = cohort[["camis","open_date"]].copy()
    result["capture_date"] = ""
    result["capture_name_key"] = ""
    result["observed_same_name_locations"] = np.nan
    result["observed_name_multilocation_flag"] = np.nan
    result["status"] = "no_original_capture_available_by_opening"
    result["source_reference"] = ""
    audit = []
    captures = sorted(captures,key=capture_date)
    for i,path in enumerate(captures):
        day = capture_date(path).isoformat()
        next_day = capture_date(captures[i+1]).isoformat() if i+1<len(captures) else "9999-12-31"
        selected = cohort.open_date.ge(day) & cohort.open_date.lt(next_day)
        if not selected.any():
            continue
        print(f"Checking capture-time identity: {day}",flush=True)
        identities,counts,conflicts = snapshot_inventory(path)
        result.loc[selected,"capture_date"] = day
        result.loc[selected,"source_reference"] = capture_url(path)
        result.loc[selected,"status"] = "target_not_identity_stable_in_prior_capture"
        for index in cohort.index[selected]:
            identity = identities.get(str(cohort.loc[index,"camis"]))
            if identity:
                count = counts[identity[0]]
                result.loc[index,["capture_name_key","observed_same_name_locations","observed_name_multilocation_flag","status"]] = [identity[0],count,int(count>=5),"capture_inventory_only_opening_identity_review_required"]
        audit.append({"path":str(path),"sha256":file_hash(path),"capture_date":day,"stable_identities":len(identities),
                      "conflicting_or_incomplete_identities":conflicts,"eligible_opening_rows":int(selected.sum())})
    result["historical_chain_verified"] = False
    result["training_allowlisted"] = False
    return result,audit


def evidence_chronology(evidence):
    evidence = evidence.copy()
    opening = pd.to_datetime(evidence.open_date,errors="coerce")
    earliest = pd.to_datetime(evidence.earliest_operating_inspection,errors="coerce")
    latest = pd.to_datetime(evidence.latest_operating_inspection,errors="coerce")
    finite = np.isfinite(evidence.y_upper)
    upper = opening + pd.to_timedelta(evidence.y_upper.where(finite)*365.25,unit="D")
    evidence["opening_after_operation_lead"] = earliest.notna() & earliest.lt(opening)
    evidence["operation_after_proxy_exit_upper_bound"] = finite & latest.notna() & latest.gt(upper)
    evidence["label_review_priority"] = np.select([
        evidence.opening_after_operation_lead | evidence.operation_after_proxy_exit_upper_bound,
        evidence.identity_conflict_seen.astype(str).str.lower().isin(["true","1"]),
        evidence.temporary_health_closure_seen.astype(str).str.lower().isin(["true","1"])],
        ["chronology_conflict_review","identity_conflict_review","health_closure_is_not_permanent_exit"],
        default="unresolved_evidence_review")
    return evidence


def run(output):
    output = Path(output).resolve()
    if output.exists() or not output.is_relative_to(ROOT/"data/output"):
        raise ValueError("Use a new private data/output directory")
    manifest = json.loads((PARENT/"run_manifest.json").read_text())
    cohort_path = PARENT/"corrected_research/training_rows.csv"
    raw_path = PARENT/"frozen_root/data/restaurants_raw.parquet"
    for path in (cohort_path,raw_path):
        if file_hash(path) != manifest["artifact_sha256"][str(path.relative_to(PARENT))]:
            raise ValueError("Frozen parent input changed")
    master_path = (ROOT/"data/integrated/current/master_tract_features.csv").resolve()
    restaurant_path = master_path.parent/"entities/current_restaurants.csv"
    master = pd.read_csv(master_path,dtype={"geoid":str})
    restaurants = pd.read_csv(restaurant_path,dtype={"camis":str,"geoid":str,"zipcode":str,"building":str})
    raw = pd.read_parquet(raw_path)
    raw["camis"] = raw.camis.astype(str)
    raw["zipcode"] = raw.zipcode.astype(str)
    cohort = pd.read_csv(cohort_path,dtype={"camis":str,"geoid":str},float_precision="round_trip",low_memory=False)
    property_manifest = json.loads((ROOT/"data/output/feature_engineering/20261027_v3/manifest.json").read_text())
    property_path = Path(property_manifest["sources"]["listings"]["path"])
    if file_hash(property_path) != property_manifest["sources"]["listings"]["sha256"]:
        raise ValueError("Pinned property inventory changed")
    properties = pd.read_csv(property_path,dtype={"property_id":str,"geoid":str})
    access_manifest = json.loads((ACCESS/"manifest.json").read_text())
    priority_ids = set()
    for name in ("neighborhood_cafe","office_lunch","casual_dinner","premium_dinner"):
        path = ACCESS/(name+".csv")
        if file_hash(path) != access_manifest["artifacts"][path.name]:
            raise ValueError("Pinned ranking artifact changed")
        scores = pd.read_csv(path,dtype={"property_id":str})
        priority_ids.update(scores.dropna(subset=["repaired_opportunities"]).nlargest(50,"repaired_opportunities").property_id)
    prioritized = properties[properties.property_id.isin(priority_ids)]
    output.mkdir(parents=True)
    queue,active = review_queue(restaurants,raw,set(master.geoid),prioritized)
    queue.to_csv(output/"restaurant_repair_queue.csv",index=False)
    queue[~queue.coordinate_usable | ~queue.tract_usable].to_csv(output/"coordinate_review_queue.csv",index=False)
    sources = {str(p):file_hash(p) for p in (cohort_path,raw_path,master_path,restaurant_path,property_path,ACCESS/"manifest.json")}
    geography_path = master_path.parent/"geography/nyc_2020_census_tracts.geojson"
    overlay,coordinate_audit = coordinate_overlay(restaurants,queue,json.loads(geography_path.read_text()),set(master.geoid))
    overlay.to_csv(output/"current_restaurants_coordinate_candidate.csv",index=False)
    coordinate_audit.to_csv(output/"coordinate_restoration_audit.csv",index=False)
    sources[str(geography_path)] = file_hash(geography_path)
    snapshot_paths = [ROOT/"data/evaluation/snapshots/2023-04-v0/historical_core_snapshots.json"]
    snapshots = load_historical_snapshots(snapshot_paths,ROOT/"data","2026-10-28")
    historical,provenance = build_historical_features(cohort,snapshots)
    matrix = pd.concat([cohort[["camis","geoid","nta_code","open_date"]],historical],axis=1)
    matrix["available_historical_features"] = historical.notna().sum(axis=1)
    matrix["outcomes_independently_verified"] = False
    matrix.to_csv(output/"opening_time_core_features.csv",index=False)
    pd.DataFrame(provenance).to_csv(output/"opening_time_feature_provenance.csv",index=False)
    matrix.assign(opening_year=cohort.open_date.str[:4]).groupby("opening_year").agg(
        restaurants=("camis","size"),with_any_historical_features=("available_historical_features",lambda x:int(x.gt(0).sum())),
        with_all_four_historical_features=("available_historical_features",lambda x:int(x.eq(4).sum()))).to_csv(output/"historical_coverage_by_opening_year.csv")
    for path in snapshot_paths:
        sources[str(path)] = file_hash(path)
    for entries in snapshots.values():
        for item in entries:
            sources[str(ROOT/"data"/item["path"])] = item["sha256"]
    historical_mapping = {"population_density":"population_density_per_sq_mile", "median_household_income":"median_household_income",
                          "job_density":"job_density_per_sq_mile", "walkability":"national_walkability_index"}
    audit = []
    for name,source,domain,transform,group in SPECS:
        dated = historical_mapping.get(name)
        audit.append({"research_feature":"context_"+name,"current_source_column":source,"group":group,
                      "historical_replacement":dated or "", "historical_values_available":int(historical[dated].notna().sum()) if dated else 0,
                      "historical_training_status":"dated_alternative_exists_not_same_measurement_vintage" if dated else "excluded_no_dated_replacement",
                      "current_values_backdated":False})
    pd.DataFrame(audit).to_csv(output/"historical_feature_contract.csv",index=False)
    captures = list((ROOT/"data/raw_sources/nyc_cuisine_atlas").glob("*/wayback_*.csv"))
    chains,capture_audit = historical_chain_candidates(cohort,captures)
    chains.to_csv(output/"capture_time_chain_review.csv",index=False)
    for item in capture_audit:
        sources[item["path"]] = item["sha256"]
    packet_path = ROOT/"data/evaluation/lifespans/adjudication_packet_20261020_v5.csv"
    ledger_path = ROOT/"data/evaluation/closure_research/operating_ledger_20261021T154934609261Z/candidate_summary.csv"
    packet = pd.read_csv(packet_path,dtype={"business_id":str},keep_default_na=False)
    ledger = pd.read_csv(ledger_path,dtype={"business_id":str},keep_default_na=False)
    evidence = cohort[["camis","geoid","nta_code","borough","open_date","y_lower","y_upper","last_snapshot"]].copy()
    fields = ["business_id","verification_status","outcome_status","identity_review","identity_resolution","fsq_match_status","fsq_marked_closed_dates","sla_match_status"]
    evidence = evidence.merge(packet[fields],left_on="camis",right_on="business_id",how="left",validate="one_to_one").drop(columns="business_id")
    evidence = evidence.merge(ledger[["business_id","unique_dated_operating_events","earliest_operating_inspection","latest_operating_inspection","temporary_health_closure_seen","identity_conflict_seen"]],left_on="camis",right_on="business_id",how="left",validate="one_to_one").drop(columns="business_id")
    evidence["label_basis"] = np.where(np.isfinite(evidence.y_upper),"archive_disappearance_proxy_not_verified_exit","right_censored_archive_observation")
    evidence["review_status"] = evidence.verification_status.fillna("no_adjudication_record")
    evidence["verified_exit_record_present"] = evidence.verification_status.eq("independently_verified") & evidence.outcome_status.eq("verified_permanent_closure")
    evidence["permanent_exit_training_eligible"] = False
    evidence = evidence_chronology(evidence)
    evidence.to_csv(output/"cohort_evidence_crosswalk.csv",index=False)
    evidence[evidence.opening_after_operation_lead | evidence.operation_after_proxy_exit_upper_bound].to_csv(output/"chronology_conflict_review.csv",index=False)
    for path in (packet_path,ledger_path):
        sources[str(path)] = file_hash(path)
    # Prospective protocol proposal is written once; no new model is fitted or
    # selected using the reserved partition or these review queues.
    plan = {"schema":"next-evaluation-protocol-v1","status":"proposed_requires_team_agreement_before_next_fit",
            "as_of":"2026-10-28","target":"restaurant-location-spell exit; disappearance remains a separate proxy target",
            "first_stage_excludes":["cuisine","synthetic rent","current-only neighborhood measurements","unverified full-archive chain counts"],
            "historical_features":list(HISTORICAL_FEATURES),"model_parameters_reference":"data/output/optimization/20261027_v1/selection_lock.json",
            "primary_metric":"interval negative log likelihood on a fixed target and matched cohort",
            "secondary_metrics":["interval-order concordance with paired neighborhood bootstrap","resolved-subset calibration with unresolved counts"],
            "grouping":"same location spell must not cross folds; neighborhood grouping; temporal availability cutoff",
            "previously_exposed_assessment":"data/output/optimization/20261027_v1/reserved_predictions.csv",
            "globally_untouched_test_available":False,"independent_evaluation_requires":"new independent outcome evidence or a prospectively protected future cohort",
            "promotion_requires":["verified baseline and exit/censoring evidence","dated predictor provenance","identity reconciliation","frozen training/test identifiers and source hashes","no outcome-driven test-set selection"],
            "stage_two":"walking-access and Huff scenarios; no calibrated visit-forecast claim without observed visit data",
            "production_deployment_allowed":False}
    (output/"next_evaluation_protocol.json").write_text(json.dumps(plan,indent=2)+"\n")
    report = {"schema":"feature-repair-readiness-v1","created_at":datetime.now(timezone.utc).isoformat(),
              "active_restaurants":len(active),"review_queue_rows":len(queue),
              "uncertain_label_rows":int((~active.label_source.isin(["direct","keyword"])).sum()),
              "taxonomy_review_rows":int(active.taxonomy_review.sum()),"coordinate_or_tract_review_rows":int((~active.coordinate_usable | ~active.tract_usable).sum()),
              "priority_candidate_properties":len(prioritized),"queue_near_priority_candidates":int(queue.nearby_priority_candidates.gt(0).sum()),
              "local_proposals_requiring_review":int(queue.proposal_status.eq("review_required_not_applied").sum()),
              "coordinate_records_restored_in_candidate_only":int(coordinate_audit.status.eq("restored_in_candidate_overlay_not_published").sum()),
              "cohort_rows":len(cohort),"historical_feature_coverage":{c:int(historical[c].notna().sum()) for c in historical},
              "with_all_four_historical_features":int(historical.notna().all(axis=1).sum()),
              "with_no_historical_features":int(historical.isna().all(axis=1).sum()),
              "capture_time_chain_candidates":int(chains.observed_same_name_locations.notna().sum()),"capture_audit":capture_audit,
              "cohort_rows_with_operation_leads":int(pd.to_numeric(evidence.unique_dated_operating_events,errors="coerce").gt(0).sum()),
              "opening_dates_after_operation_leads":int(evidence.opening_after_operation_lead.sum()),
              "operation_leads_after_proxy_exit":int(evidence.operation_after_proxy_exit_upper_bound.sum()),
              "cohort_verified_permanent_exit_labels":int(evidence.verified_exit_record_present.sum()),
              "master_modified":False,"labels_applied":0,"new_model_trained":False,"production_ready":False}
    (output/"readiness.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    for source,expected in sources.items():
        if file_hash(source) != expected:
            raise ValueError("Source changed during preparation: "+source)
    for name in ("prepare_feature_repairs.py","features.py","label_cuisines.py"):
        shutil.copy2(Path(__file__).with_name(name),output/name)
    (output/"manifest.json").write_text(json.dumps({"status":"completed","sources":sources,
        "artifact_sha256":{p.name:file_hash(p) for p in output.iterdir() if p.is_file()}},indent=2)+"\n")
    print(json.dumps({k:v for k,v in report.items() if k!="capture_audit"},indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True)
    run(parser.parse_args().output)
