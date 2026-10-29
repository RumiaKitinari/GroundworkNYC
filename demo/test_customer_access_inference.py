"""Dashboard wiring uses identified network bundles, never fabricated visits."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1] / "codes"))
from test_customer_access import fixtures, RoutingTests
from engineer_customer_access import build
from customer_access_inference import access_engine, attach_access
from scoring import Concept
import app


class DashboardAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        origins, candidates, _ = fixtures()
        origins["borough"] = "Manhattan"
        origins["nta_name"] = "Test Area"
        master = cls.root / "master.csv"
        master.write_text(origins.to_csv(index=False))
        properties = cls.root / "properties.csv"
        properties.write_text(candidates.to_csv(index=False))
        tracts = candidates.copy()
        tracts["property_id"] = origins.geoid
        tracts["inventory_type"] = "tract_screening_point"
        tract_path = cls.root / "tracts.csv"
        tract_path.write_text(tracts.to_csv(index=False))
        network = RoutingTests().network(cls.root)
        build(master, properties, network, cls.root / "property_run")
        build(master, tract_path, network, cls.root / "tract_run")
        cls.config = cls.root / "dashboard_access.json"
        cls.config.write_text(json.dumps({"schema": "dashboard-customer-access-v1",
            "tract_run": str(cls.root / "tract_run"), "property_run": str(cls.root / "property_run")}))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_missing_config_preserves_missingness(self):
        locations, properties = [{"geoid": "36061000100"}], [{"id": "a"}]
        status = attach_access(locations, properties, Concept(), self.root / "missing.json")
        self.assertEqual(status["status"], "unavailable")
        self.assertIsNone(locations[0]["inverse_walkability"])
        self.assertIsNone(properties[0]["customer_access"]["index"])

    def test_identified_tracts_and_properties_have_distinct_scopes(self):
        locations = [{"geoid": "36061000200"}]
        properties = [{"id": "synthetic-b", "lead_type": "synthetic"},
                      {"id": "actual-listing", "lead_type": "public"}]
        status = attach_access(locations, properties, Concept(), self.config)
        self.assertEqual(status["status"], "available")
        self.assertEqual(locations[0]["customer_access"]["scope"], "tract_centroid")
        self.assertEqual(properties[0]["customer_access"]["scope"], "synthetic_property_scenario")
        self.assertIsNone(properties[1]["customer_access"]["index"])
        self.assertIsNone(locations[0]["customer_access"]["visit_forecast"])

    def test_concept_and_origins_react_without_rerouting(self):
        engine, _ = access_engine(self.config)
        residents = Concept.from_args({"audience": "residents", "average_check": "20", "price_mode": "exact"})
        workers = Concept.from_args({"audience": "workers", "average_check": "100", "price_mode": "exact"})
        a = engine.assessment("tract_run", "36061000200", residents)
        b = engine.assessment("tract_run", "36061000200", workers)
        self.assertNotEqual(a["weighted_opportunities"], b["weighted_opportunities"])
        self.assertTrue(engine.origins("36061000200", residents))
        self.assertEqual(engine.assessment("tract_run", "not-a-tract", residents)["status"], "not_in_snapshot")

    def test_endpoint_validation_and_unavailable_snapshot(self):
        with patch.dict(app.app.config, {"CUSTOMER_ACCESS_CONFIG": str(self.config)}), app.app.test_client() as client:
            self.assertEqual(client.get("/api/customer-access?geoid=bad").status_code, 400)
            self.assertEqual(client.get("/api/customer-access?geoid=36061099999").status_code, 404)
            result = client.get("/api/customer-access?geoid=36061000200")
            self.assertEqual(result.status_code, 200)
            self.assertTrue(result.json["origins"])
        with patch.dict(app.app.config, {"CUSTOMER_ACCESS_CONFIG": str(self.root / "missing.json")}), app.app.test_client() as client:
            self.assertEqual(client.get("/api/customer-access?geoid=36061000200").status_code, 503)


if __name__ == "__main__":
    unittest.main()
