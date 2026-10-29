from collections import Counter
from copy import deepcopy

import pytest

from evidence_policy import catalog, cuisine_support, location_policy, property_policy, attach_runtime_policy
from scoring import CUISINES, Concept, ScreeningModel
from survival_inference import general_model_ranking
from test_scoring import WEIGHTS, restaurants, tract


def test_all_cuisine_categories_have_a_defined_fallback():
    for cuisine,labels in CUISINES.items():
        result = cuisine_support(cuisine,labels,Counter(),Counter(),Counter())
        assert result["mode"]=="general_concept_suitability"
        assert result["score_evidence_cap"]==0
        assert not result["demand_verified"]


def test_sparse_support_is_bounded_and_unknown_inventory_reduces_influence():
    city = Counter(Italian=10,American=90)
    support = cuisine_support("italian",("Italian",),Counter(Italian=1,American=9),Counter(Italian=1,American=9),city)
    unknown = cuisine_support("italian",("Italian",),Counter(Italian=1,American=9,unknown=90),Counter(Italian=1,American=9),city)
    assert support["mode"]=="pooled_cuisine_supply"
    assert 0<support["score_evidence_cap"]<1
    assert unknown["score_evidence_cap"]<support["score_evidence_cap"]
    assert support["pooled_neighborhood_supply_share"]==pytest.approx(.1)


def test_related_category_is_context_not_cuisine_demand():
    support = cuisine_support("haitian",(),Counter(Caribbean=10),Counter(Caribbean=50),Counter(Caribbean=100))
    assert support["mode"]=="related_supply_context_only"
    assert support["related_city_records"]==100
    assert support["score_evidence_cap"]==0
    assert support["expected_local_supply"] is None
    assert not support["related_context_changes_score"]


def test_supported_inventory_does_not_verify_demand():
    support = cuisine_support("italian",("Italian",),Counter(Italian=10,American=10),Counter(Italian=20,American=40),Counter(Italian=100,American=200))
    assert support["mode"]=="cuisine_supply_supported"
    assert not support["demand_verified"]
    policy = location_policy(.8,support,"vegan",False)
    assert policy["recommendation_eligible"]
    assert "verify_dietary_customer_fit_and_site_requirements" in policy["required_actions"]
    assert "obtain_affordability_evidence" in policy["required_actions"]


def test_no_general_data_defers_recommendations():
    support = cuisine_support("any",(),Counter(),Counter(),Counter())
    assert not location_policy(0,support)["recommendation_eligible"]
    row = {"geoid":"a"}
    result = ScreeningModel([row],[]).evaluate(row,Concept(cuisine="haitian"),WEIGHTS,"restaurant")
    assert result["opportunity"]==50
    assert result["assessment_policy"]["status"]=="insufficient_general_data"
    assert not result["assessment_policy"]["recommendation_eligible"]


def test_unsupported_cuisine_still_responds_to_price_and_format():
    row = tract()
    model = ScreeningModel([row],restaurants("a","American",20))
    cheap = model.evaluate(row,Concept(cuisine="haitian",average_check=15),WEIGHTS,"restaurant")
    premium = model.evaluate(row,Concept(cuisine="haitian",average_check=180,service_style="fine_dining"),WEIGHTS,"restaurant")
    assert cheap["opportunity"]!=premium["opportunity"]
    assert cheap["concept_evidence"]["support"]["score_evidence_cap"]==0


@pytest.mark.parametrize("price",[None,0,-1,float("nan"),float("inf"),"",True])
def test_missing_prices_never_pass_budget_filter(price):
    result = property_policy({"asking_rent":price,"lead_type":"synthetic","transaction":"lease"},"lease",10000,2000000)
    assert not result["budget_eligible"]
    assert result["budget_evidence"]=="unavailable"
    assert not result["verified_live_listing"]
    assert result["financial_return_estimate"] is None


def test_transaction_modes_keep_distinct_prices():
    property_row = {"asking_price":1500000,"transaction":"purchase","lead_type":"synthetic"}
    assert not property_policy(property_row,"lease",10000,2000000)["budget_eligible"]
    assert property_policy(property_row,"purchase",10000,2000000)["budget_eligible"]
    assert property_policy(property_row,"either",10000,2000000)["budget_eligible"]


def test_general_survival_fallback_is_one_explicit_batch_basis():
    rows = [{"opportunity":40,"survival":{"status":"available","probability":.6,"feature_coverage":1},
             "assessment_policy":{"recommendation_eligible":True}},
            {"opportunity":80,"survival":{"status":"available","probability":.8,"feature_coverage":1},
             "assessment_policy":{"recommendation_eligible":True}}]
    ranked,status = general_model_ranking(deepcopy(rows),{"ranking_mode":"screening"},"test-model")
    assert status["ranking_mode"]=="survival_general_fit"
    assert ranked[0]["opportunity"]==92
    assert ranked[0]["ranking_components"]["cuisine_gap"] is None
    rows[0]["survival"]["feature_coverage"] = .25
    unchanged,status = general_model_ranking(deepcopy(rows),{"ranking_mode":"screening"},"test-model")
    assert status["ranking_mode"]=="screening"
    assert [r["opportunity"] for r in unchanged]==[40,80]


def test_policy_catalog_covers_explicit_failure_classes():
    policy = catalog()
    assert len(policy["cases"])>=20
    assert not policy["thresholds_calibrated"]
    assert not policy["related_categories_are_demand_substitutes"]


def test_runtime_missing_model_and_routes_do_not_turn_into_predictions():
    support = cuisine_support("haitian",(),Counter(),Counter(),Counter())
    row = {"assessment_policy":location_policy(.8,support),"customer_access":{"index":None,"status":"unavailable"},
           "survival":{"probability":None,"status":"awaiting_artifact"}}
    policy = attach_runtime_policy(row)
    assert policy["survival_basis"]=="unavailable_general_screening_only"
    assert "verify_network_access" in policy["required_actions"]
    assert not policy["cuisine_demand_verified"]


def test_api_policy_catalog_and_outside_nyc_site():
    from app import app
    with app.test_client() as client:
        response = client.get("/api/assessment-policy")
        assert response.status_code==200
        assert len(response.json["cases"])==20
        # Inside the broad NYC bounding box, but on the New Jersey side.
        response = client.post("/api/sites/analyze",json={"latitude":40.745,"longitude":-74.04})
        assert response.status_code==400
        assert response.json["status"]=="outside_supported_geography"


@pytest.mark.parametrize("coverage",[None,float("nan"),float("inf"),True,-1,2])
def test_invalid_model_coverage_never_enables_a_model_ranking(coverage):
    rows = [{"opportunity":50,"survival":{"status":"available","probability":.7,"feature_coverage":coverage},
             "assessment_policy":{"recommendation_eligible":True}}]
    result,status = general_model_ranking(rows,{"ranking_mode":"screening"},"test")
    assert status["ranking_mode"]=="screening"
    assert result[0]["opportunity"]==50
