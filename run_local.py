"""Run the current dashboard through the PostGIS/Redis backend on one origin."""
import argparse
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent


def configure_environment(env_file, environ=None):
    from dotenv import dotenv_values
    environ = os.environ if environ is None else environ
    for key, value in dotenv_values(env_file).items():
        if value is not None:
            environ.setdefault(key, value)
    if not environ.get("DATABASE_URL"):
        password = environ.get("POSTGRES_PASSWORD")
        if not password:
            raise ValueError("Set DATABASE_URL or POSTGRES_PASSWORD in the private .env file")
        environ["DATABASE_URL"] = "postgresql://groundwork:" + quote(password, safe="") + "@127.0.0.1:15432/groundwork"
    environ.setdefault("REDIS_URL", "redis://127.0.0.1:16379/0")
    return environ


def check_services(environ):
    import psycopg
    from redis import Redis, RedisError
    result = {"postgres": "unavailable", "redis": "unavailable",
              "account_workspace_store": "instance/accounts.sqlite3",
              "access_bundle_present": (ROOT / "data/output/customer_access_dashboard/dashboard_access.json").is_file()}
    current = ROOT / "data/integrated/current"
    result["current_data_release"] = current.resolve().name if current.exists() else None
    try:
        with psycopg.connect(environ["DATABASE_URL"], connect_timeout=5,
                             options="-c statement_timeout=5000") as connection:
            result["active_layers"] = connection.execute("SELECT count(*) FROM gw_active").fetchone()[0]
            rows = connection.execute(
                "SELECT a.layer, s.metadata FROM gw_active a "
                "JOIN gw_snapshots s ON s.id=a.snapshot WHERE a.layer LIKE 'screening_%'").fetchall()
            sys.path.insert(0, str(ROOT / "backend"))
            from groundwork_backend.provenance import screening_is_current
            result["stale_screening_layers"] = [layer for layer, metadata in rows
                if not screening_is_current(metadata, result["current_data_release"])]
            result["postgres"] = "ready"
    except psycopg.Error:
        result["action"] = "Check the local PostGIS service and run its existing migrations if needed"
    try:
        with Redis.from_url(environ["REDIS_URL"], socket_timeout=1, socket_connect_timeout=1) as cache:
            if cache.ping():
                result["redis"] = "ready"
    except (RedisError, ValueError):
        result["cache_fallback"] = "PostGIS continues to serve tiles without Redis"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--check", action="store_true", help="Check service configuration without starting a server")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be in 1-65535")
    try:
        environment = configure_environment(args.env_file)
    except (ImportError, ValueError) as error:
        parser.exit(2, str(error) + "\nInstall backend/requirements-dashboard.txt and configure .env.\n")
    status = check_services(environment)
    print(json.dumps(status, indent=2), flush=True)
    if status["postgres"] != "ready":
        parser.exit(2, "Spatial backend is not ready; no standalone Flask fallback was started.\n")
    if args.check:
        return
    sys.path.insert(0, str(ROOT / "backend"))
    import uvicorn
    uvicorn.run("groundwork_backend.api:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
