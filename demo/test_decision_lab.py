import pytest

from decision_lab import analyze_scenarios, scenario_grid


def snapshot(scores, *, key="opportunity", release="release-a", mode="screening", **scoring):
    return {"locations": [{"id": identifier, "name": f"Area {identifier}", key: score}
                          for identifier, score in scores],
            "meta": {"data_release": release, "sort_by": key},
            "scoring": {"ranking_mode": mode, **scoring}}


def test_scenario_grid_is_bounded_unique_and_starts_with_the_baseline():
    scenarios = scenario_grid(35, "lunch", {"average_checks": [45, 25], "dayparts": ["evening", "all_day"]})
    assert len(scenarios) == 9
    assert scenarios[0] == {"id": "s1", "average_check": 35, "daypart": "lunch"}
    assert scenarios[-1] == {"id": "s9", "average_check": 25, "daypart": "all_day"}
    assert scenario_grid(35, "lunch", {}) == scenarios[:1]
    assert scenario_grid(35, "lunch", {"average_checks": [35.0, 35], "dayparts": ["lunch"]}) == scenarios[:1]


@pytest.mark.parametrize("payload", [None, [], {"rent_cap": 4000}, {"average_checks": 30},
                                    {"average_checks": [5, 25, 45]}, {"average_checks": [True]},
                                    {"average_checks": [float("nan")]}, {"average_checks": [10**400]},
                                    {"average_checks": [4]}, {"average_checks": ["35"]},
                                    {"dayparts": ["lunch", "morning", "evening"]},
                                    {"dayparts": [[]]}, {"dayparts": "lunch"}, {"dayparts": ["dinner"]}])
def test_scenario_grid_rejects_invalid_alternatives(payload):
    with pytest.raises(ValueError):
        scenario_grid(35, "all_day", payload)


def test_tie_intervals_keep_possible_candidates_and_saved_areas_beyond_the_cutoff():
    grid = scenario_grid(35, "lunch", {"average_checks": [45]})
    before = snapshot([("a", 90), ("b", 80), ("c", 80), ("d", 80), ("e", 74), ("saved", 0)])
    after = snapshot([("a", 90), ("d", 86), ("e", 84), ("b", 82), ("c", 80), ("saved", None)])
    result = analyze_scenarios(grid, [before, after], saved_ids=["saved", "unknown", "saved"])
    candidates = {row["id"]: row for row in result["candidates"]}
    assert set(candidates) == {"a", "b", "c", "d", "e", "saved", "unknown"}
    assert [row["id"] for row in result["scenarios"][0]["displayed_top_three"]] == ["a", "b", "c"]
    assert result["summary"]["tied_cutoff_count"] == 1
    d = candidates["d"]
    assert (d["clear_count"], d["possible_count"], d["displayed_count"], d["available_count"]) == (1, 2, 1, 2)
    assert d["results"][0] == {"scenario_id": "s1", "status": "ranked", "score": 80, "rank_min": 2, "rank_max": 4,
                               "gap_to_leader": 10, "displayed": False, "clear": False, "possible": True}
    assert d["score_range"] == {"min": 80, "max": 86}
    assert d["max_gap_to_leader"] == 10
    saved = candidates["saved"]
    assert saved["saved"] and saved["available_count"] == 1
    assert saved["score_range"] == {"min": 0, "max": 0}
    assert saved["results"][1]["status"] == "missing_score"
    assert candidates["unknown"]["results"][0]["status"] == "not_ranked"
    assert result["one_factor_flips"] == [{"factor": "average_check", "before_id": "s1", "after_id": "s2",
                                            "entered_ids": ["e"], "left_ids": ["b", "c"],
                                            "coverage_changed": True}]


def test_one_factor_pairs_hold_the_other_input_constant():
    grid = scenario_grid(35, "lunch", {"average_checks": [45], "dayparts": ["evening"]})
    ordinary = snapshot([("a", 90), ("b", 85), ("c", 80), ("d", 75)])
    corner = snapshot([("a", 90), ("b", 85), ("d", 81), ("c", 80)])
    result = analyze_scenarios(grid, [ordinary, ordinary, ordinary, corner])
    assert result["summary"]["matched_pair_count"] == 4
    assert [(row["factor"], row["before_id"], row["after_id"]) for row in result["one_factor_flips"]] == [
        ("average_check", "s2", "s4"), ("daypart", "s3", "s4"),
    ]


def test_missing_scores_are_separate_from_scenarios_without_evidence():
    grid = scenario_grid(35, "lunch", {"average_checks": [45], "dayparts": ["evening"]})
    before = snapshot([("a", 90), ("b", 85), ("c", 80)])
    after = snapshot([("a", 90), ("b", 85), ("d", 81), ("c", None)])
    result = analyze_scenarios(grid, [before, after, snapshot([("c", float("nan"))]), None])
    assert result["summary"] == {"scenario_count": 4, "comparable_count": 2, "unavailable_count": 1,
                                 "insufficient_count": 1, "baseline_id": "s1", "matched_pair_count": 1,
                                 "coverage_changed_pair_count": 1, "tied_cutoff_count": 0}
    assert result["one_factor_flips"] == []
    c = next(row for row in result["candidates"] if row["id"] == "c")
    assert [row["status"] for row in c["results"]] == [
        "ranked", "missing_score", "scenario_insufficient", "scenario_unavailable",
    ]
    assert all(row["possible"] is None for row in c["results"][1:])


@pytest.mark.parametrize("change", ["release", "mode", "basis_id", "release_id", "sort_key"])
def test_mismatched_ranking_provenance_cannot_be_compared(change):
    grid = scenario_grid(35, "lunch", {"average_checks": [45]})
    before = snapshot([("a", 90)], basis_id="screening-v1")
    after = snapshot([("a", 92)], basis_id="screening-v1")
    if change == "release":
        after["meta"]["data_release"] = "release-b"
    elif change == "mode":
        before["scoring"] = {"ranking_mode": "screening"}
        after["scoring"] = {"ranking_mode": "survival_general_fit"}
    elif change == "basis_id":
        after["scoring"]["basis_id"] = "screening-v2"
    elif change == "release_id":
        before["meta"]["release_id"] = "data-hash-a"
        after["meta"]["release_id"] = "data-hash-b"
    else:
        after = snapshot([("a", 92)], key="inverse_walkability", basis_id="screening-v1")
    with pytest.raises(ValueError, match="release or ranking method"):
        analyze_scenarios(grid, [before, after])


def test_customer_access_uses_access_scores_and_ignores_survival_mode():
    grid = scenario_grid(35, "lunch", {"average_checks": [45]})
    before = snapshot([("a", 90), ("b", None)], key="inverse_walkability")
    after = snapshot([("b", 100), ("a", 92)], key="inverse_walkability", mode="survival_general_fit")
    before["locations"][1]["opportunity"] = 100
    result = analyze_scenarios(grid, [before, after])
    assert result["ranking_basis"] == "Customer access"
    assert result["scenarios"][0]["displayed_top_three"] == [{"id": "a", "name": "Area a", "score": 90}]
    assert result["scenarios"][0]["eligible_count"] == 1


def test_wholly_unavailable_scenarios_do_not_imply_a_scoring_basis():
    grid = scenario_grid(35, "lunch", {})
    result = analyze_scenarios(grid, [None], saved_ids=["saved"])
    assert result["ranking_basis"] is None
    assert result["summary"]["unavailable_count"] == 1
    assert result["candidates"][0]["score_range"] is None


def test_comparison_requires_known_provenance():
    grid = scenario_grid(35, "lunch", {"average_checks": [45]})
    result = snapshot([("a", 90)], release=None)
    with pytest.raises(ValueError, match="could not be verified"):
        analyze_scenarios(grid, [result, result])
