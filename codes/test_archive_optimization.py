import sqlite3

import numpy as np
import pandas as pd
import pytest

from audit_access_optimization import choose_anchors, comparison
from optimize_archive_model import closure_variant, development_cv, feature_policies, group_role
from customer_access import AccessConcept, load_config
from network_huff import network_scenarios
from test_customer_access import fixtures


def test_group_assignment_is_deterministic_and_explicit():
    names = [f"NTA{i}" for i in range(100)]
    roles = [group_role(n) for n in names]
    assert roles == [group_role(n) for n in names]
    assert set(roles) == {"development", "reserved_assessment"}
    with pytest.raises(ValueError):
        group_role(None)


def test_reserved_rows_cannot_enter_tuning():
    rows = pd.DataFrame({"optimization_role": ["reserved_assessment"], "nta_code": ["A"]})
    with pytest.raises(ValueError, match="Reserved"):
        development_cv(rows, [], {}, folds=3)


def test_eligible_policies_exclude_temporal_restaurant_proxies():
    columns = ["context_food_poi_density", "context_cafe_density", "context_bar_density"]
    columns += [f"context_{i}" for i in range(35)]
    policies = feature_policies(pd.DataFrame(columns=columns))
    assert len(policies["context_only"]) == 38
    assert len(policies["context_without_current_supply"]) == 35
    assert not set(policies["context_only"]) & {"is_chain", "open_year", "competitors_400m_at_open"}


def test_stricter_absence_rules_recensor_without_inventing_survival():
    rows = pd.DataFrame({"last_snapshot": ["2026-04-01", "2025-01-01", "2026-10-01"],
                         "y_lower": [1., 2., 3.], "y_upper": [1.5, 2.5, np.inf]})
    captures = ["2025-01-01", "2026-04-01", "2026-10-01"]
    result, audit = closure_variant(rows, captures, "two_later_captures")
    np.testing.assert_array_equal(result.y_lower, rows.y_lower)
    assert np.isinf(result.y_upper.iloc[0])
    assert result.y_upper.iloc[1] == 2.5
    assert np.isinf(result.y_upper.iloc[2])
    assert audit["weak_events_recensored"] == 1
    assert np.isfinite(rows.y_upper.iloc[0])
    with pytest.raises(ValueError):
        closure_variant(rows, captures, "guess_closed")


def test_anchor_repair_requires_same_tract_nearby_active_observation():
    candidates = pd.DataFrame({"property_id": ["A", "B"], "geoid": ["A", "B"],
                               "latitude": [40.7, 40.71], "longitude": [-74., -74.]})
    restaurants = pd.DataFrame({"camis": ["1", "2", "3", "4"], "geoid": ["A", "B", "A", "A"],
        "active_establishment": [True, True, True, False],
        "latitude": [40.701, 40.7, 40.72, 40.7], "longitude": [-74.]*4})
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE nodes(id INTEGER, latitude REAL, longitude REAL)")
        db.execute("CREATE VIRTUAL TABLE node_index USING rtree(id,min_lon,max_lon,min_lat,max_lat)")
        db.execute("INSERT INTO nodes VALUES(1,40.701,-74.)")
        db.execute("INSERT INTO node_index VALUES(1,-74.,-74.,40.701,40.701)")
        replacement, audit = choose_anchors(None, candidates, restaurants, np.array([True, False]), db)
        assert replacement.property_id.tolist() == ["A"]
        assert audit.camis.tolist() == ["1"]
        assert audit.shift_meters.le(500).all()
        assert audit.snap_meters.le(200).all()
        empty, audit = choose_anchors(None, candidates, restaurants, np.array([True, False]), db, max_shift=50)
        assert empty.empty
        assert audit.status.tolist() == ["no_supported_replacement"]


def test_rank_comparison_does_not_fill_missing_scores():
    result = comparison(pd.Series([1., 2., np.nan]), pd.Series([1., np.nan, 4.]))
    assert result["rated"] == 2
    assert result["common_rated"] == 1
    assert result["spearman_common"] is None


def test_unknown_competitor_check_uses_actual_target_anchor():
    origins, candidates, routes = fixtures()
    tracts = candidates.copy()
    tracts["property_id"] = origins.geoid
    incomplete = routes.copy()
    incomplete[1, 0] = np.nan
    # Destination is distant even though its population centroid is nearby.
    tracts.loc[1, "latitude"] += .1
    result, _ = network_scenarios(origins, candidates, routes, tracts, incomplete,
                                  np.array([1.,2.,1.]), AccessConcept(), load_config())
    assert result.huff_opportunities.notna().all()


def test_development_cv_reproducible_with_grouped_small_fixture():
    rows = pd.DataFrame({"nta_code":np.repeat(["A","B","C"],4),
                         "optimization_role":"development", "value":np.arange(12),
                         "y_lower":np.tile([1.,2.,3.,4.],3),
                         "y_upper":np.tile([1.5,2.5,3.5,np.inf],3)})
    parameters = {"rounds":3,"max_depth":2,"min_child_weight":1}
    pred, folds, score = development_cv(rows,["value"],parameters)
    again, again_folds, again_score = development_cv(rows,["value"],parameters)
    np.testing.assert_array_equal(pred,again)
    np.testing.assert_array_equal(folds,again_folds)
    assert score == again_score
    assert pd.DataFrame({"nta":rows.nta_code,"fold":folds}).groupby("nta").fold.nunique().eq(1).all()
