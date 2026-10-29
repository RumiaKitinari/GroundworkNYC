"""Read-only local release gate. Never downloads, publishes, stages or trains."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "demo"))


def staged_issues(root=ROOT):
    names = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"], cwd=root
    ).decode().split("\0")
    issues = []
    for name in filter(None, names):
        path = Path(name)
        private = (name.startswith(("data/", "instance/", ".venv/")) and name != "data/.gitignore")
        private |= path.name.startswith(".env") and path.name not in {".env.example", ".env.template"}
        private |= path.suffix.lower() in {".sqlite", ".sqlite3", ".db", ".pkl", ".joblib", ".parquet", ".ubj", ".pem", ".key"}
        if private:
            issues.append({"file": name, "reason": "Private data, account store or model artifact staged"})
            continue
        size = int(subprocess.check_output(["git", "cat-file", "-s", ":" + name], cwd=root))
        if size > 5 * 1024 * 1024:
            issues.append({"file": name, "reason": "Large staged file requires explicit review"})
            continue
        blob = subprocess.check_output(["git", "show", ":" + name], cwd=root)
        if path.suffix.lower() == ".json":
            try:
                value = json.loads(blob)
            except (ValueError, UnicodeError):
                value = None
            if isinstance(value, dict) and "learner" in value:
                issues.append({"file": name, "reason": "Native trained model artifact requires exclusion"})
        if re.search(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|AKIA[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9]{30,}", blob):
            issues.append({"file": name, "reason": "Possible credential in staged content"})
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    from run_local import configure_environment, check_services
    from maintain_data import training_inventory
    from survival_inference import model_state

    failures, warnings = [], []
    try:
        services = check_services(configure_environment(ROOT / ".env"))
        if services["postgres"] != "ready":
            failures.append("PostGIS unavailable")
        if services.get("stale_screening_layers"):
            failures.append("Active screening tiles do not match current data and scoring code")
        if not services.get("active_layers"):
            failures.append("No spatial layers have been published")
        if services["redis"] != "ready":
            warnings.append("Redis unavailable; database tile fallback remains enabled")
    except (ValueError, ImportError):
        services = {"status": "configuration_unavailable"}
        failures.append("Local service configuration unavailable")
    try:
        inventory = training_inventory()
        configured_data = os.environ.get("GROUNDWORK_DATA_DIR")
        if configured_data and Path(configured_data).expanduser().resolve() != Path(inventory["active_release"]).resolve():
            failures.append("Configured dashboard dataset differs from the audited integrated release; validate and publish it before release")
        failures.extend(inventory["structural_issues"])
        data = {key: inventory[key] for key in (
            "tract_rows", "master_columns", "documented_columns", "feature_matrix_sha256",
            "feature_matrix_structurally_valid", "success_model_training_ready")}
        pending = [key for key, source in inventory["sources"].items()
                   if source["status"] in {"integration_pending", "raw_missing"}]
        if pending:
            warnings.append("Source follow-up: " + ", ".join(pending))
    except (OSError, ValueError, KeyError):
        data = {"status": "audit_failed"}
        failures.append("Integrated data audit failed")
    _, model = model_state()
    if model["status"] == "invalid_artifact":
        failures.append("Configured survival artifact failed validation")
    elif model.get("source_type") == "atharv_tract_export":
        warnings.append("Archive-proxy tract export is display-only; verified survival inference remains unavailable")
    elif model["status"] != "available":
        warnings.append("Verified survival model unavailable; release is screening-only")
    staged = staged_issues()
    if staged:
        failures.append("Unsafe staged files require review")
    print(json.dumps({"status": "blocked" if failures else "ready_for_screening_demo",
                      "services": services, "data": data, "model_status": model["status"],
                      "staged_issues": staged, "failures": failures, "warnings": warnings,
                      "scope": "Operational readiness, not scientific model validation"}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
