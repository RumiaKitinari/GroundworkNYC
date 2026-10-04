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
        self.assertIn(b"chef@example.com", self.client.get("/").data)
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


if __name__ == "__main__":
    unittest.main()
