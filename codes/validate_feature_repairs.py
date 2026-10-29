"""Check pinned repair artifacts, historical chronology, and unchanged source data."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from customer_access import file_hash
from features import HISTORICAL_FEATURES


def validate(run):
    run = Path(run).resolve()
    manifest = json.loads((run/"manifest.json").read_text())
    if manifest["status"]!="completed":
        raise ValueError("Readiness run did not complete")
    for source,digest in manifest["sources"].items():
        if file_hash(source)!=digest:
            raise ValueError("Pinned source changed: "+source)
    for name,digest in manifest["artifact_sha256"].items():
        if file_hash(run/name)!=digest:
            raise ValueError("Repair artifact changed: "+name)
    report = json.loads((run/"readiness.json").read_text())
    provenance = pd.read_csv(run/"opening_time_feature_provenance.csv",dtype={"camis":str,"geoid":str},keep_default_na=False)
    known = provenance[provenance.status.eq("historical_observation")]
    if not ((known.observed_through<=known.available_on) & (known.available_on<=known.prediction_date)).all():
        raise ValueError("Future information entered historical features")
    matrix = pd.read_csv(run/"opening_time_core_features.csv",dtype={"camis":str,"geoid":str})
    if matrix.camis.duplicated().any() or len(matrix)!=report["cohort_rows"]:
        raise ValueError("Cohort identities changed")
    numeric = matrix[list(HISTORICAL_FEATURES)]
    if np.isinf(numeric.to_numpy()).any() or not numeric.notna().sum(axis=1).eq(matrix.available_historical_features).all():
        raise ValueError("Historical feature counts inconsistent")
    if len(provenance)!=len(matrix)*len(HISTORICAL_FEATURES):
        raise ValueError("Missing feature provenance rows")
    for feature in HISTORICAL_FEATURES:
        audit = provenance[provenance.feature.eq(feature)].set_index("camis").loc[matrix.camis]
        expected = np.log1p(pd.to_numeric(audit.raw_value,errors="coerce").to_numpy(float))
        np.testing.assert_allclose(matrix[feature],expected,rtol=1e-12,atol=1e-12,equal_nan=True)
    source = next(Path(p) for p in manifest["sources"] if p.endswith("/entities/current_restaurants.csv"))
    types = {"camis":str,"geoid":str,"zipcode":str,"building":str}
    original = pd.read_csv(source,dtype=types,float_precision="round_trip")
    candidate = pd.read_csv(run/"current_restaurants_coordinate_candidate.csv",dtype=types,float_precision="round_trip")
    if candidate.camis.tolist()!=original.camis.tolist():
        raise ValueError("Candidate inventory identities/order changed")
    unchanged = [c for c in original if c not in {"latitude","longitude","geoid"}]
    pd.testing.assert_frame_equal(original[unchanged],candidate[unchanged],check_dtype=False)
    restored = candidate.coordinate_repair_basis.ne("original_integrated_record")
    pd.testing.assert_frame_equal(original.loc[~restored,["latitude","longitude","geoid"]],
                                   candidate.loc[~restored,["latitude","longitude","geoid"]],check_dtype=False)
    if restored.sum()!=report["coordinate_records_restored_in_candidate_only"]:
        raise ValueError("Restoration count differs")
    audit = pd.read_csv(run/"coordinate_restoration_audit.csv",dtype={"camis":str,"resolved_geoid":str})
    used = audit[audit.status.eq("restored_in_candidate_overlay_not_published")].set_index("camis")
    changed = candidate[restored].set_index("camis").loc[used.index]
    np.testing.assert_allclose(changed.latitude,used.proposed_latitude,rtol=0,atol=1e-10)
    np.testing.assert_allclose(changed.longitude,used.proposed_longitude,rtol=0,atol=1e-10)
    if not changed.geoid.eq(used.resolved_geoid).all():
        raise ValueError("Repaired tract IDs differ")
    queue = pd.read_csv(run/"restaurant_repair_queue.csv",dtype={"camis":str},keep_default_na=False)
    if queue.camis.duplicated().any() or len(queue)!=report["review_queue_rows"] or queue.applied_to_master.any():
        raise ValueError("Review state invalid")
    chain = pd.read_csv(run/"capture_time_chain_review.csv",dtype={"camis":str},keep_default_na=False)
    eligible = chain[chain.observed_same_name_locations.ne("")]
    if not eligible.capture_date.le(eligible.open_date).all() or chain.training_allowlisted.any():
        raise ValueError("Chain evidence was backdated or promoted")
    plan = json.loads((run/"next_evaluation_protocol.json").read_text())
    if plan["globally_untouched_test_available"] or plan["production_deployment_allowed"]:
        raise ValueError("Evaluation disclosure changed")
    return {"status":"passed","source_files_checked":len(manifest["sources"]),
            "artifacts_checked":len(manifest["artifact_sha256"]),"cohort_rows":len(matrix),
            "dated_feature_values_checked":len(known),"coordinate_restorations_checked":int(restored.sum()),
            "master_unchanged":True,"production_ready":False}


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",required=True)
    parser.add_argument("--output",required=True)
    args = parser.parse_args()
    result = validate(args.run)
    output = Path(args.output)
    if output.exists():
        raise ValueError("Use a new validation output")
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
