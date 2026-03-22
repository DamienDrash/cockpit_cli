from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from cockpit.infrastructure.db.database_adapter import DatabaseAdapter


class DatabaseAdapterTests(unittest.TestCase):
    def test_discovers_sqlite_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database_path = root / "app.sqlite3"
            sqlite3.connect(database_path).close()

            adapter = DatabaseAdapter()
            snapshot = adapter.list_databases(str(root))

            self.assertTrue(snapshot.is_available)
            self.assertIn(str(database_path.resolve()), snapshot.databases)

    def test_runs_select_query(self) -> None:
        with TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "app.db"
            with sqlite3.connect(database_path) as connection:
                connection.execute("CREATE TABLE users(name TEXT)")
                connection.execute("INSERT INTO users(name) VALUES ('alice')")
                connection.execute("INSERT INTO users(name) VALUES ('bob')")
                connection.commit()

            adapter = DatabaseAdapter()
            result = adapter.run_query(str(database_path), "SELECT name FROM users ORDER BY name")

            self.assertTrue(result.success)
            self.assertEqual(result.columns, ["name"])
            self.assertEqual(result.rows, [["alice"], ["bob"]])

    def test_detects_mutating_query_prefixes(self) -> None:
        self.assertTrue(DatabaseAdapter.is_mutating_query("UPDATE users SET name = 'x'"))
        self.assertFalse(DatabaseAdapter.is_mutating_query("SELECT * FROM users"))


if __name__ == "__main__":
    unittest.main()
