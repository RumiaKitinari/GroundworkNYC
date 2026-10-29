import numpy as np
import pandas as pd
from shapely.geometry import Polygon, mapping

from prepare_feature_repairs import (coordinate_overlay, historical_chain_candidates,
                                     evidence_chronology, identity_agrees, review_queue, snapshot_inventory)


def test_archived_identity_requires_all_fields_and_same_location():
    row = dict(dba="A Cafe",boro="Queens",building="12",street="Main St",zipcode="11355")
    assert identity_agrees(row,row)
    assert not identity_agrees(row,{**row,"building":"13"})
    assert not identity_agrees(row,{**row,"dba":""})


def test_chain_inventory_deduplicates_locations_and_rejects_identity_drift(tmp_path):
    path = tmp_path/"wayback_20240101000000.csv"
    pd.DataFrame({"CAMIS":["1","1","2","3","3"],"DBA":["Cafe"]*5,"BORO":["Queens"]*5,
        "BUILDING":["10","10","10","20","21"],"STREET":["Main"]*5,"ZIPCODE":["11355"]*5}).to_csv(path,index=False)
    stable,counts,conflicts = snapshot_inventory(path)
    assert set(stable)=={"1","2"}
    assert counts["CAFE"]==1
    assert conflicts==1
    cohort = pd.DataFrame({"camis":["1","1","9"],"open_date":["2023-12-31","2024-01-02","2024-01-02"]})
    result,_ = historical_chain_candidates(cohort,[path])
    assert np.isnan(result.observed_same_name_locations.iloc[0])
    assert result.observed_same_name_locations.iloc[1]==1
    assert np.isnan(result.observed_same_name_locations.iloc[2])
    assert not result.historical_chain_verified.any()
    assert not result.training_allowlisted.any()


def test_coordinate_overlay_does_not_use_nearest_tract_fallback():
    restaurants = pd.DataFrame({"camis":["1","2"],"latitude":[np.nan,np.nan],"longitude":[np.nan,np.nan],"geoid":["",""]})
    queue = pd.DataFrame({"camis":["1","2"],"geoid":["",""],"proposed_latitude":[40.7,40.9],
                          "proposed_longitude":[-74.,-74.],"archive_identity_agrees":[True,True]})
    geography = {"features":[{"properties":{"geoid":"36061000100"},"geometry":mapping(Polygon([
        (-74.01,40.69),(-73.99,40.69),(-73.99,40.71),(-74.01,40.71)]))}]}
    overlay,audit = coordinate_overlay(restaurants,queue,geography,{"36061000100"})
    assert overlay.geoid.iloc[0]=="36061000100"
    assert np.isnan(overlay.latitude.iloc[1])
    assert audit.status.iloc[1]=="withheld_no_unique_tract"
    assert restaurants.latitude.isna().all()


def test_review_proposals_do_not_assert_cuisine_or_operation():
    current = pd.DataFrame({"camis":["1"],"active_establishment":[True],"dba":["Place"],"boro":["Queens"],
        "building":["12"],"street":["Main"],"zipcode":["11355"],"cuisine_description":["Other"],
        "latitude":[np.nan],"longitude":[np.nan],"geoid":[""]})
    raw = pd.DataFrame({"camis":["1"],"dba":["Place"],"boro":["Queens"],"building":["12"],
                       "street":["Main"],"zipcode":["11355"],"cuisine":["Italian"],"lat":[40.7],"lon":[-74.]})
    queue,_ = review_queue(current,raw,{"36061000100"},pd.DataFrame())
    assert queue.proposed_cuisine_50.iloc[0]=="Italian"
    assert queue.approved_cuisine_50.iloc[0]==""
    assert not queue.applied_to_master.any()
    assert current.cuisine_description.iloc[0]=="Other"


def test_operation_chronology_flags_conflicts_without_relabelling():
    evidence = pd.DataFrame({"open_date":["2024-01-01"]*3,"y_upper":[1.,np.inf,1.],
        "earliest_operating_inspection":["2023-01-01","2024-03-01",None],
        "latest_operating_inspection":["2026-01-01","2026-01-01",None],
        "identity_conflict_seen":[False]*3,"temporary_health_closure_seen":[False,True,False]})
    result = evidence_chronology(evidence)
    assert result.opening_after_operation_lead.tolist()==[True,False,False]
    assert result.operation_after_proxy_exit_upper_bound.tolist()==[True,False,False]
    assert result.label_review_priority.iloc[1]=="health_closure_is_not_permanent_exit"
    np.testing.assert_array_equal(result.y_upper,evidence.y_upper)
