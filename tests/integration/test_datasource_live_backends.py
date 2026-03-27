from __future__ import annotations

import importlib.util
import json
import os
import time
import unittest

from cockpit.datasources.models.datasource import DataSourceProfile
from cockpit.datasources.adapters.backends.mongodb_adapter import MongoDatasourceAdapter
from cockpit.datasources.adapters.backends.redis_adapter import RedisDatasourceAdapter
from cockpit.datasources.adapters.backends.sqlalchemy_adapter import (
    SQLAlchemyDatasourceAdapter,
)


LIVE_SERVICES_ENABLED = os.environ.get("COCKPIT_LIVE_SERVICES") == "1"
PSYCOPG_AVAILABLE = importlib.util.find_spec("psycopg") is not None
PYMYSQL_AVAILABLE = importlib.util.find_spec("pymysql") is not None
PYMONGO_AVAILABLE = importlib.util.find_spec("pymongo") is not None
REDIS_AVAILABLE = importlib.util.find_spec("redis") is not None


def _wait_until_ready(callback, *, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            callback()
            return
        except Exception as exc:  # pragma: no cover - exercised only in live CI
            last_error = exc
            time.sleep(1.0)
    if last_error is not None:
        raise last_error


@unittest.skipUnless(LIVE_SERVICES_ENABLED, "live datasource services are disabled")
class LiveDatasourceBackendTests(unittest.TestCase):
    @unittest.skipUnless(PSYCOPG_AVAILABLE, "psycopg must be installed")
    def test_postgres_round_trip(self) -> None:
        url = os.environ["COCKPIT_TEST_POSTGRES_URL"]
        adapter = SQLAlchemyDatasourceAdapter()
        profile = DataSourceProfile(
            id="pg_live",
            name="Postgres Live",
            backend="postgres",
            connection_url=url,
        )

        def _probe() -> None:
            inspection = adapter.inspect(profile)
            if not inspection.success:
                raise RuntimeError(inspection.summary)

        _wait_until_ready(_probe)
        adapter.run(
            profile,
            "CREATE TABLE IF NOT EXISTS cockpit_smoke (id INTEGER PRIMARY KEY, value VARCHAR(32));",
            operation="mutate",
        )
        adapter.run(profile, "DELETE FROM cockpit_smoke;", operation="mutate")
        adapter.run(
            profile,
            "INSERT INTO cockpit_smoke (id, value) VALUES (1, 'ok');",
            operation="mutate",
        )
        result = adapter.run(
            profile,
            "SELECT value FROM cockpit_smoke ORDER BY id ASC;",
            operation="query",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.rows, [["ok"]])

    @unittest.skipUnless(PYMYSQL_AVAILABLE, "PyMySQL must be installed")
    def test_mysql_round_trip(self) -> None:
        url = os.environ["COCKPIT_TEST_MYSQL_URL"]
        adapter = SQLAlchemyDatasourceAdapter()
        profile = DataSourceProfile(
            id="mysql_live",
            name="MySQL Live",
            backend="mysql",
            connection_url=url,
        )

        def _probe() -> None:
            inspection = adapter.inspect(profile)
            if not inspection.success:
                raise RuntimeError(inspection.summary)

        _wait_until_ready(_probe)
        adapter.run(
            profile,
            "CREATE TABLE IF NOT EXISTS cockpit_smoke (id INTEGER PRIMARY KEY, value VARCHAR(32));",
            operation="mutate",
        )
        adapter.run(profile, "DELETE FROM cockpit_smoke;", operation="mutate")
        adapter.run(
            profile,
            "INSERT INTO cockpit_smoke (id, value) VALUES (1, 'ok');",
            operation="mutate",
        )
        result = adapter.run(
            profile,
            "SELECT value FROM cockpit_smoke ORDER BY id ASC;",
            operation="query",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.rows, [["ok"]])

    @unittest.skipUnless(REDIS_AVAILABLE, "redis must be installed")
    def test_redis_round_trip(self) -> None:
        url = os.environ["COCKPIT_TEST_REDIS_URL"]
        adapter = RedisDatasourceAdapter()
        profile = DataSourceProfile(
            id="redis_live",
            name="Redis Live",
            backend="redis",
            connection_url=url,
        )

        def _probe() -> None:
            inspection = adapter.inspect(profile)
            if not inspection.success:
                raise RuntimeError(inspection.summary)

        _wait_until_ready(_probe)
        adapter.run(profile, "SET cockpit:smoke ok", operation="mutate")
        result = adapter.run(profile, "GET cockpit:smoke", operation="query")

        self.assertTrue(result.success)
        self.assertIn("ok", result.output_text or "")

    @unittest.skipUnless(PYMONGO_AVAILABLE, "pymongo must be installed")
    def test_mongodb_round_trip(self) -> None:
        url = os.environ["COCKPIT_TEST_MONGODB_URL"]
        adapter = MongoDatasourceAdapter()
        profile = DataSourceProfile(
            id="mongo_live",
            name="Mongo Live",
            backend="mongodb",
            connection_url=url,
            database_name="cockpit",
        )

        def _probe() -> None:
            inspection = adapter.inspect(profile)
            if not inspection.success:
                raise RuntimeError(inspection.summary)

        _wait_until_ready(_probe)
        adapter.run(
            profile,
            json.dumps(
                {
                    "database": "cockpit",
                    "collection": "smoke",
                    "operation": "delete_many",
                    "filter": {},
                }
            ),
            operation="mutate",
        )
        adapter.run(
            profile,
            json.dumps(
                {
                    "database": "cockpit",
                    "collection": "smoke",
                    "operation": "insert_one",
                    "document": {"_id": "ok", "value": "ok"},
                }
            ),
            operation="mutate",
        )
        result = adapter.run(
            profile,
            json.dumps(
                {
                    "database": "cockpit",
                    "collection": "smoke",
                    "operation": "find",
                    "filter": {"_id": "ok"},
                }
            ),
            operation="query",
        )

        self.assertTrue(result.success)
        self.assertTrue(any("ok" in row[0] for row in result.rows))
