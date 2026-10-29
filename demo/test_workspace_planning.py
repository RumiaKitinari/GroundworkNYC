"""Private, durable planning workspaces and strict scenario validation."""
from copy import deepcopy

from test_auth import AuthTests
from workspace_schema import valid_plans

INPUTS = {"monthly_rent": 6000, "monthly_fixed": 12000, "operating_days": 26,
          "price": 35, "unit_cost": 12, "daily_covers": 100, "capacity": 200,
          "elasticity": 1.5, "congestion_cost": 5, "profit_target": 500}


class PlanningWorkspaceTests(AuthTests):
    def signup(self, client, email):
        client.get("/")
        with client.session_transaction() as session:
            token = session["csrf_token"]
        self.assertEqual(client.post("/auth/signup", data={"email": email, "password": "correct-password", "confirmation": "correct-password", "csrf_token": token}).status_code, 302)
        client.get("/")
        with client.session_transaction() as session:
            return session["csrf_token"]

    def test_plans_survive_new_login_and_are_isolated(self):
        import app as module
        token = self.signup(self.client, "first@example.com")
        workspace = {"active_brief": None, "briefs": [], "shortlists": {}, "menus": {},
                     "profile": {"display_name": "Chef One", "company": "Cafe"},
                     "plans": {"concept": {"property_ids": ["synthetic-1"], "selected_property_id": "synthetic-1",
                         "draft": INPUTS, "scenarios": {"Expected": INPUTS}, "basket": {"tea": 2},
                         "menu_details": {"tea": {"ingredients": "Tea, water", "complexity": "simple",
                             "recipe": {"portions": 1, "waste_pct": 0, "lines": [{"name": "Tea", "quantity": 1, "unit": "bag", "unit_cost": 1}]}}},
                         "planning_inputs": {"opening_cash": 150000, "scenario_name": "Expected"},
                         "checklist": {"property_visit": True, "funding": False}}}}
        response = self.client.put("/api/workspace", json={"revision": 0, "workspace": workspace}, headers={"X-CSRF-Token": token})
        self.assertEqual(response.status_code, 200, response.json)
        other = module.app.test_client()
        self.signup(other, "second@example.com")
        self.assertIsNone(other.get("/api/workspace").json["workspace"])
        fresh = module.app.test_client()
        fresh.get("/")
        with fresh.session_transaction() as session:
            token = session["csrf_token"]
        fresh.post("/auth/login", data={"email": "first@example.com", "password": "correct-password", "csrf_token": token})
        self.assertEqual(fresh.get("/api/workspace").json["workspace"], workspace)
        self.assertEqual(fresh.get("/api/workspace").headers["Cache-Control"], "no-store")

    def test_invalid_plans_rejected(self):
        valid = {"concept": {"draft": INPUTS}}
        self.assertTrue(valid_plans(valid))
        for field,value in [("price", float("nan")), ("daily_covers", 300), ("capacity", True), ("monthly_rent", -10)]:
            invalid = deepcopy(valid); invalid["concept"]["draft"][field] = value
            self.assertFalse(valid_plans(invalid), field)
        self.assertFalse(valid_plans({"x": {"basket": {"tea": True}}}))
        self.assertFalse(valid_plans({"x": {"property_ids": ["a"] * 5}}))
        self.assertFalse(valid_plans({"x": {"scenarios": []}}))
        self.assertFalse(valid_plans({"x": {"draft": {**INPUTS, "owner_id": 1}}}))
        self.assertFalse(valid_plans({"x": {"menu_details": {"tea": {"complexity": "unknown"}}}}))
        self.assertFalse(valid_plans({"x": {"checklist": {"funding": "yes"}}}))
        self.assertFalse(valid_plans({"x": {"checklist": {"arbitrary": True}}}))
        self.assertFalse(valid_plans({"x": {"planning_inputs": {"months": 0}}}))
        self.assertFalse(valid_plans({"x": {"menu_details": {"tea": {"recipe": {}}}}}))
