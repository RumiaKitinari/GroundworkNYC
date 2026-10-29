"""Local account and CSRF checks for the entry screen."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as module


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.accounts = patch.object(module, "ACCOUNTS_PATH", Path(self.directory.name) / "accounts.sqlite3")
        self.accounts.start()
        self.client = module.app.test_client()
        self.client.get("/")

    def tearDown(self):
        self.accounts.stop()
        self.directory.cleanup()

    def token(self):
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def test_signup_login_logout_and_wrong_password(self):
        details = {"email": "chef@example.com", "password": "correct-password"}
        response = self.client.post("/auth/signup", data={**details, "confirmation": details["password"], "csrf_token": self.token()})
        self.assertEqual(response.status_code, 302)
        signed_in = self.client.get("/").data
        self.assertIn(b"chef@example.com", signed_in)
        self.assertIn(b"data-logout", signed_in)
        self.assertNotIn(b'data-auth-open="signup"', signed_in)
        self.client.post("/auth/logout", data={"csrf_token": self.token()})
        self.client.get("/")
        wrong = self.client.post("/auth/login", data={**details, "password": "wrong-password", "csrf_token": self.token()})
        self.assertEqual(wrong.status_code, 400)
        self.assertIn(b"Email or password is incorrect", wrong.data)
        right = self.client.post("/auth/login", data={**details, "csrf_token": self.token()})
        self.assertEqual(right.status_code, 302)

    def test_csrf_required_and_guest_entry(self):
        fresh = module.app.test_client()
        self.assertEqual(fresh.post("/auth/guest").status_code, 400)
        self.assertEqual(self.client.post("/auth/guest", data={"csrf_token": self.token()}).status_code, 302)
        with self.client.session_transaction() as session:
            self.assertEqual(session["access"], "guest")
        guest_page = self.client.get("/").data
        self.assertIn(b'data-auth-open="login"', guest_page)
        self.assertIn(b'data-auth-open="signup"', guest_page)
        self.assertNotIn(b"data-logout", guest_page)

    def test_account_workspace_is_private_validated_and_versioned(self):
        self.assertEqual(self.client.get("/api/workspace").status_code, 401)
        details = {"email": "chef@example.com", "password": "correct-password"}
        self.client.post("/auth/signup", data={**details, "confirmation": details["password"], "csrf_token": self.token()})
        self.client.get("/")
        initial = self.client.get("/api/workspace").json
        self.assertEqual(initial, {"workspace": None, "revision": 0})
        workspace = {
            "active_brief": {"conceptName": "Korean Cafe", "profile": "coffee"},
            "briefs": [{"conceptName": "Korean Cafe", "profile": "coffee"}],
            "shortlists": {"groundwork-shortlist:test": ["36061000100"]},
            "menus": {"groundwork-menu-v2:test": [{"id": "tea", "name": "Tea", "section": "Drinks"}]},
        }
        self.assertEqual(self.client.put("/api/workspace", json={"revision": 0, "workspace": workspace}).status_code, 403)
        headers = {"X-CSRF-Token": self.token()}
        self.assertEqual(self.client.put("/api/workspace", json={"revision": 0, "workspace": {"menus": {}}}, headers=headers).status_code, 400)
        malformed = dict(workspace, menus={"bad": [{"id": "x", "name": "Dish", "section": ["Mains"]}]})
        self.assertEqual(self.client.put("/api/workspace", json={"revision": 0, "workspace": malformed}, headers=headers).status_code, 400)
        saved = self.client.put("/api/workspace", json={"revision": 0, "workspace": workspace}, headers=headers)
        self.assertEqual(saved.json["revision"], 1)
        self.assertEqual(self.client.get("/api/workspace").json["workspace"], workspace)
        self.assertEqual(self.client.put("/api/workspace", json={"revision": 0, "workspace": workspace}, headers=headers).status_code, 409)
        self.client.post("/auth/logout", data={"csrf_token": self.token()})
        self.client.get("/")
        self.assertEqual(self.client.get("/api/workspace").status_code, 401)
        self.client.post("/auth/login", data={**details, "csrf_token": self.token()})
        self.assertEqual(self.client.get("/api/workspace").json["workspace"], workspace)


if __name__ == "__main__":
    unittest.main()
