from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from cockpit.datasources.adapters.database_adapter import DatabaseAdapter
from cockpit.datasources.adapters.ssh_command_runner import SSHCommandResult
from cockpit.core.enums import SessionTargetKind


class FakeSSHCommandRunner:
    def __init__(self, result: SSHCommandResult) -> None:
        self._result = result

    def run(
        self,
        target_ref: str,
        command: str,
        *,
        timeout_seconds: int = 5,
        input_text: str | None = None,
    ) -> SSHCommandResult:
        del timeout_seconds, input_text
        return SSHCommandResult(
            target_ref=target_ref,
            command=command,
            returncode=self._result.returncode,
            stdout=self._result.stdout,
            stderr=self._result.stderr,
            is_available=self._result.is_available,
            message=self._result.message,
        )


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
            result = adapter.run_query(
                str(database_path), "SELECT name FROM users ORDER BY name"
            )

            self.assertTrue(result.success)
            self.assertEqual(result.columns, ["name"])
            self.assertEqual(result.rows, [["alice"], ["bob"]])

    def test_detects_mutating_query_prefixes(self) -> None:
        self.assertTrue(
            DatabaseAdapter.is_mutating_query("UPDATE users SET name = 'x'")
        )
        self.assertFalse(DatabaseAdapter.is_mutating_query("SELECT * FROM users"))

    def test_runs_remote_query_via_ssh_runner(self) -> None:
        adapter = DatabaseAdapter(
            ssh_command_runner=FakeSSHCommandRunner(
                SSHCommandResult(
                    target_ref="dev@example.com",
                    command="python3",
                    returncode=0,
                    stdout=(
                        '{"success": true, "database_path": "/srv/app/app.db", '
                        '"query": "SELECT 1", "columns": ["value"], "rows": [["1"]], '
                        '"row_count": 1, "message": "Returned 1 row."}'
                    ),
                    stderr="",
                )
            )
        )

        result = adapter.run_query(
            "/srv/app/app.db",
            "SELECT 1",
            target_kind=SessionTargetKind.SSH,
            target_ref="dev@example.com",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.columns, ["value"])
        self.assertEqual(result.rows, [["1"]])


if __name__ == "__main__":
    unittest.main()
