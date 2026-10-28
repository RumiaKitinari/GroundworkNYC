import importlib.util
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from groundwork_backend.provenance import screening_provenance, screening_is_current

spec = importlib.util.spec_from_file_location("release_check", ROOT / "check_release.py")
release_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_check)


def test_screening_requires_both_release_and_code():
    metadata = {"data_release": "release", **screening_provenance()}
    assert screening_is_current(metadata, "release")
    assert not screening_is_current(metadata, "new-release")
    assert not screening_is_current({"data_release": "release"}, "release")
    assert not screening_is_current({**metadata, "screening_code_sha256": "old"}, "release")


def test_staged_gate_checks_index_not_working_tree(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path)
    git("init", "-q")
    (tmp_path / "README.md").write_text("Public documentation")
    git("add", "README.md")
    assert release_check.staged_issues(tmp_path) == []
    (tmp_path / "README.md").write_text("Unstaged sensitive change")
    (tmp_path / "data").mkdir()
    (tmp_path / "data/private.csv").write_text("private")
    git("add", "data/private.csv")
    assert release_check.staged_issues(tmp_path)[0]["file"] == "data/private.csv"


def test_staged_credentials_are_reported_without_values(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "oops.txt").write_text("-----BEGIN " + "PRIVATE KEY-----")
    subprocess.run(["git", "add", "oops.txt"], cwd=tmp_path, check=True)
    issues = release_check.staged_issues(tmp_path)
    assert issues == [{"file": "oops.txt", "reason": "Possible credential in staged content"}]
