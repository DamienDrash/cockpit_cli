from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from cockpit.infrastructure.secrets.secret_resolver import SecretResolver


class SecretResolverTests(unittest.TestCase):
    def test_resolves_nested_values_from_env_file_and_literals(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            secret_file = root / "token.txt"
            secret_file.write_text("file-secret\n", encoding="utf-8")
            resolver = SecretResolver(base_path=root)

            with patch.dict("os.environ", {"TEST_DB_USER": "analytics"}):
                text = resolver.resolve_text(
                    "postgresql://${DB_USER}:${DB_PASS}@localhost/app",
                    {
                        "DB_USER": "env:TEST_DB_USER",
                        "DB_PASS": {"provider": "file", "path": "token.txt"},
                    },
                )
                nested = resolver.resolve_value(
                    {
                        "dsn": "redis://:${TOKEN}@localhost:6379/0",
                        "tags": ["${TOKEN}", "static"],
                    },
                    {"TOKEN": "literal:abc123"},
                )

            self.assertEqual(text, "postgresql://analytics:file-secret@localhost/app")
            self.assertEqual(
                nested,
                {
                    "dsn": "redis://:abc123@localhost:6379/0",
                    "tags": ["abc123", "static"],
                },
            )

    def test_raises_for_missing_secret_reference(self) -> None:
        resolver = SecretResolver()

        with self.assertRaisesRegex(ValueError, "not defined"):
            resolver.resolve_text("value=${MISSING}", {})
