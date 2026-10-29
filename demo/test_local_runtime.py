import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("local_runtime", ROOT / "run_local.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class LocalRuntimeTests(unittest.TestCase):
    def test_loads_private_configuration_and_escapes_database_password(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("POSTGRES_PASSWORD='test@with:/symbols'\nGROUNDWORK_SECRET_KEY=test-only\n")
            environment = runtime.configure_environment(path, {})
        self.assertIn("test%40with%3A%2Fsymbols@127.0.0.1:15432", environment["DATABASE_URL"])
        self.assertEqual(environment["REDIS_URL"], "redis://127.0.0.1:16379/0")

    def test_explicit_service_configuration_takes_precedence(self):
        environment = {"DATABASE_URL": "postgresql://explicit", "REDIS_URL": "redis://explicit"}
        runtime.configure_environment(ROOT / "not-present.env", environment)
        self.assertEqual(environment["DATABASE_URL"], "postgresql://explicit")
        self.assertEqual(environment["REDIS_URL"], "redis://explicit")

    def test_missing_configuration_does_not_start_an_unconnected_demo(self):
        with self.assertRaises(ValueError):
            runtime.configure_environment(ROOT / "not-present.env", {})


if __name__ == "__main__":
    unittest.main()
