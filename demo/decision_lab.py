"""Tie-aware comparisons of existing dashboard ranks across explicit scenarios."""

from collections import Counter
from itertools import combinations, product
from math import isfinite


_DAYPARTS = ("all_day", "morning", "lunch", "evening")
_TOP = 3
_RANKING_LABELS = {"opportunity": "Dashboard location score", "inverse_walkability": "Customer access"}


def scenario_grid(baseline_check, baseline_daypart, payload):
    """Validate alternatives and keep the current dashboard scenario first."""
    if not isinstance(payload, dict) or payload.keys() - {"average_checks", "dayparts"}:
        raise ValueError("Choose guest spends or trading periods to test.")
    checks = payload.get("average_checks", [])
    dayparts = payload.get("dayparts", [])
    if not isinstance(checks, list) or len(checks) > 2:
        raise ValueError("Choose up to two additional guest spends.")
    if not isinstance(dayparts, list) or len(dayparts) > 2:
        raise ValueError("Choose up to two additional trading periods.")
    if any(isinstance(check, bool) or not isinstance(check, (int, float)) or not 5 <= check <= 250
           for check in checks):
        raise ValueError("Guest spend must be between $5 and $250.")
    if any(daypart not in _DAYPARTS for daypart in dayparts):
        raise ValueError("Choose a supported trading period.")
    pairs = product(dict.fromkeys([baseline_check, *checks]), dict.fromkeys([baseline_daypart, *dayparts]))
    return [{"id": f"s{index}", "average_check": check, "daypart": daypart}
            for index, (check, daypart) in enumerate(pairs, start=1)]


def _score_key(snapshot):
    return (snapshot or {}).get("meta", {}).get("sort_by") or "opportunity"


def _score_is_numeric(value):
    return type(value) is int or (type(value) is float and isfinite(value))


def _rank_bounds(scores):
    bounds = {}
    start = 1
    for score, count in sorted(Counter(scores.values()).items(), reverse=True):
        bounds[score] = (start, start + count - 1)
        start += count
    return bounds


def _scenario(scenario, snapshot):
    rows = {row["id"]: row for row in ((snapshot or {}).get("locations") or ())}
    key = _score_key(snapshot)
    scores = {identifier: row[key] for identifier, row in rows.items() if _score_is_numeric(row.get(key))}
    bounds = _rank_bounds(scores)
    displayed = list(scores)[:_TOP]
    status = "comparable" if scores else "insufficient"
    if snapshot is None:
        status = "unavailable"
    return {
        "details": {
            **scenario, "status": status, "eligible_count": len(scores),
            "displayed_top_three": [{"id": identifier, "name": rows[identifier].get("name"),
                                     "score": scores[identifier]} for identifier in displayed],
            "cutoff_tied": any(low <= _TOP < high for low, high in bounds.values()) if scores else None,
        },
        "names": {identifier: row.get("name") for identifier, row in rows.items()},
        "scores": scores,
        "bounds": bounds,
        "leader_score": max(bounds, default=None),
        "displayed": displayed,
        "possible": [identifier for identifier, score in scores.items() if bounds[score][0] <= _TOP],
    }


def _provenance(snapshot):
    meta = snapshot.get("meta", {})
    scoring = snapshot.get("scoring", {})
    key = _score_key(snapshot)
    mode = scoring.get("ranking_mode") if key == "opportunity" else key
    return meta.get("release_id") or meta.get("data_release"), key, scoring.get("basis_id") or mode


def _candidate_result(identifier, run):
    details = run["details"]
    score = run["scores"].get(identifier)
    result = {"scenario_id": details["id"], "score": score}
    if score is None:
        status = "scenario_" + details["status"]
        if details["status"] == "comparable":
            status = "missing_score" if identifier in run["names"] else "not_ranked"
        return {**result, "status": status, "rank_min": None, "rank_max": None,
                "gap_to_leader": None, "displayed": None, "clear": None, "possible": None}
    low, high = run["bounds"][score]
    return {**result, "status": "ranked", "rank_min": low, "rank_max": high,
            "gap_to_leader": round(run["leader_score"] - score, 2),
            "displayed": identifier in run["displayed"], "clear": high <= _TOP, "possible": low <= _TOP}


def _candidate(identifier, runs, saved):
    results = [_candidate_result(identifier, run) for run in runs]
    ranked = [result for result in results if result["status"] == "ranked"]
    scores = [result["score"] for result in ranked]
    return {
        "id": identifier,
        "name": next((run["names"][identifier] for run in runs if run["names"].get(identifier)), None),
        "saved": saved,
        "clear_count": sum(result["clear"] for result in ranked),
        "possible_count": sum(result["possible"] for result in ranked),
        "displayed_count": sum(result["displayed"] for result in ranked),
        "available_count": len(ranked),
        "score_range": {"min": min(scores), "max": max(scores)} if scores else None,
        "max_gap_to_leader": max((result["gap_to_leader"] for result in ranked), default=None),
        "results": results,
    }


def _one_factor_flips(runs):
    flips = []
    matched_count = coverage_changed_count = 0
    comparable = [run for run in runs if run["details"]["status"] == "comparable"]
    for before, after in combinations(comparable, 2):
        left, right = before["details"], after["details"]
        changed = [key for key in ("average_check", "daypart") if left[key] != right[key]]
        if len(changed) != 1:
            continue
        matched_count += 1
        coverage_changed = before["scores"].keys() != after["scores"].keys()
        coverage_changed_count += coverage_changed
        old_possible, new_possible = set(before["possible"]), set(after["possible"])
        entered = [identifier for identifier in after["possible"]
                   if identifier not in old_possible and identifier in before["scores"]]
        left_ids = [identifier for identifier in before["possible"]
                    if identifier not in new_possible and identifier in after["scores"]]
        if entered or left_ids:
            flips.append({"factor": changed[0], "before_id": left["id"], "after_id": right["id"],
                          "entered_ids": entered, "left_ids": left_ids, "coverage_changed": coverage_changed})
    return flips, matched_count, coverage_changed_count


def analyze_scenarios(scenarios, snapshots, saved_ids=()):
    """Read ranks from one release and basis. None denotes an unavailable run."""
    if not scenarios or len(scenarios) != len(snapshots):
        raise ValueError("Each scenario requires one ranking result.")
    runs = [_scenario(scenario, snapshot) for scenario, snapshot in zip(scenarios, snapshots)]
    comparable = [snapshot for snapshot, run in zip(snapshots, runs) if run["details"]["status"] == "comparable"]
    provenance = _provenance(comparable[0]) if comparable else None
    if any(_provenance(snapshot) != provenance for snapshot in comparable[1:]):
        raise ValueError("The data release or ranking method changed across scenarios. Refresh and try again.")
    if len(comparable) > 1 and (not provenance[0] or not provenance[2]):
        raise ValueError("The data release or ranking method could not be verified across scenarios.")
    reference = comparable[0] if comparable else next((snapshot for snapshot in snapshots if snapshot), {})
    key = _score_key(reference) if reference else None
    saved = dict.fromkeys(saved_ids)
    candidate_ids = dict.fromkeys([*saved, *(identifier for run in runs for identifier in run["possible"])])
    flips, matched_count, coverage_changed_count = _one_factor_flips(runs)
    statuses = Counter(run["details"]["status"] for run in runs)
    return {
        "scenarios": [run["details"] for run in runs],
        "candidates": [_candidate(identifier, runs, identifier in saved) for identifier in candidate_ids],
        "one_factor_flips": flips,
        "summary": {"scenario_count": len(runs), "comparable_count": statuses["comparable"],
                    "unavailable_count": statuses["unavailable"], "insufficient_count": statuses["insufficient"],
                    "baseline_id": scenarios[0]["id"], "matched_pair_count": matched_count,
                    "coverage_changed_pair_count": coverage_changed_count,
                    "tied_cutoff_count": sum(run["details"]["cutoff_tied"] is True for run in runs)},
        "ranking_basis": _RANKING_LABELS.get(key),
        "ranking_mode": reference.get("scoring", {}).get("ranking_mode") if key == "opportunity" else key,
        "release": reference.get("meta", {}).get("data_release"),
        "limitations": ("Counts describe the tested assumptions and scored areas. Scores and rank changes do not "
                        "estimate observed demand, property availability, or business outcomes."),
    }
