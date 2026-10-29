import numpy as np
import pandas as pd
import pytest

from evaluate_matched_results import matched_cohort,paired_nll_delta,within_fold_concordance
from features import HISTORICAL_FEATURES


def fixture():
    rows = pd.DataFrame({"camis":["1","2","3"],"geoid":["a","b","c"],"open_date":["2024-01-01"]*3})
    dated = rows.copy()
    for column in HISTORICAL_FEATURES:
        dated[column] = [1.,2.,np.nan]
    split = pd.DataFrame({"camis":["1","2","3"],"optimization_role":["development","reserved_assessment","development"]})
    return rows,dated,split


def test_matched_cohort_excludes_reserved_and_incomplete_rows():
    rows,dated,split = fixture()
    matched,audit = matched_cohort(rows,dated,split)
    assert matched.camis.tolist()==["1"]
    assert audit["reserved_rows_excluded"]==1
    assert audit["development_rows_without_all_four_dated_features"]==1
    assert len(rows)==3


def test_mismatched_geography_or_time_origin_is_rejected():
    rows,dated,split = fixture()
    dated.loc[0,"geoid"] = "wrong"
    with pytest.raises(ValueError,match="geography"):
        matched_cohort(rows,dated,split)
    rows,dated,split = fixture()
    dated.loc[0,"open_date"] = "2025-01-01"
    with pytest.raises(ValueError,match="time origins"):
        matched_cohort(rows,dated,split)


def test_duplicate_identities_are_rejected():
    rows,dated,split = fixture()
    with pytest.raises(ValueError,match="Duplicate"):
        matched_cohort(pd.concat([rows,rows]),dated,split)


def test_paired_likelihood_same_model_is_zero():
    result = paired_nll_delta([1.,2.,3.],[1.,2.,3.],[1.,2.,3.],[1.,2.,np.inf],["a","b","c"])
    assert result["candidate_minus_reference"]==0
    assert result["nta_bootstrap_95_ci"]==[0,0]


def test_within_fold_constant_has_half_concordance_despite_fold_offsets():
    result = within_fold_concordance([100.,100.,1.,1.],[1.,2.,1.,2.],
        [1.,2.,3.,4.],[1.,2.,3.,4.],["a","b","c","d"],[0,0,1,1])
    assert result["reference"]==.5
    assert result["candidate"]==1
    assert result["candidate_minus_reference"]==.5


def test_no_comparable_pairs_is_not_reported_as_accuracy():
    with pytest.raises(ValueError,match="comparable"):
        within_fold_concordance([1.,2.],[1.,2.],[1.,2.],[np.inf,np.inf],["a","b"],[0,0])
