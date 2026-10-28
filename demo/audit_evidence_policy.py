"""Full concept-by-location policy audit, with no model fitting or promotion."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from app import PROFILE_WEIGHTS, integrated_package
from evidence_policy import VERSION, catalog
from scoring import CUISINES, Concept

ROOT = Path(__file__).resolve().parents[1]


def run(output):
    import hashlib
    def digest(path):
        with Path(path).open("rb") as stream:
            return hashlib.file_digest(stream,"sha256").hexdigest()
    output = Path(output).resolve()
    if output.exists() or not output.is_relative_to(ROOT/"data/output"):
        raise ValueError("Choose a new private data/output directory")
    package = integrated_package()
    model = package["screening_model"]
    profiles = [("counter_service","quick_service",18),("restaurant","casual",35),("fine_dining","fine_dining",110)]
    rows = package["tracts"]
    results = []
    for cuisine in CUISINES:
        for profile,style,price in profiles:
            modes,statuses = Counter(),Counter()
            minimum,maximum = 100,0
            for row in rows:
                result = model.evaluate(row,Concept(cuisine=cuisine,service_style=style,average_check=price),PROFILE_WEIGHTS[profile],profile)
                policy,support = result["assessment_policy"],result["concept_evidence"]["support"]
                if not 0<=result["opportunity"]<=100 or not 0<=support["score_evidence_cap"]<=1:
                    raise ValueError("Invalid screening output")
                if support["city_cuisine_records"]==0 and support["score_evidence_cap"]!=0:
                    raise ValueError("Absent cuisine evidence gained score influence")
                if support["related_context_changes_score"] or support["demand_verified"]:
                    raise ValueError("Context was mislabeled demand")
                modes[support["mode"]]+=1
                statuses[policy["status"]]+=1
                minimum,maximum = min(minimum,result["opportunity"]),max(maximum,result["opportunity"])
            results.append({"cuisine":cuisine,"profile":profile,"tracts":len(rows),"modes":dict(modes),
                            "statuses":dict(statuses),"score_min":minimum,"score_max":maximum})
        print("Audited: "+cuisine,flush=True)
    output.mkdir(parents=True)
    (output/"policy.json").write_text(json.dumps(catalog(),indent=2)+"\n")
    (output/"concept_cases.json").write_text(json.dumps(results,indent=2)+"\n")
    for name in ("evidence_policy.py","scoring.py","audit_evidence_policy.py"):
        shutil.copy2(Path(__file__).with_name(name),output/name)
    master = ROOT/package["data_path"]/"master_tract_features.csv"
    result = {"status":"passed","policy_version":VERSION,"created_at":datetime.now(timezone.utc).isoformat(),
              "cuisine_categories":len(CUISINES),"profiles":len(profiles),"tracts":len(rows),
              "evaluations":len(CUISINES)*len(profiles)*len(rows),"data_release":str(master.parent.resolve()),
              "master_sha256":digest(master),"policy_cases":len(catalog()["cases"]),
              "model_trained":False,"thresholds_calibrated":False,
              "artifacts":{p.name:digest(p) for p in output.iterdir() if p.is_file()}}
    (output/"manifest.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({k:v for k,v in result.items() if k!="artifacts"},indent=2))


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True)
    run(parser.parse_args().output)
