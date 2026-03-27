from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from cockpit.datasources.adapters.secret_resolver import SecretResolver


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

    def test_resolves_managed_secret_references(self) -> None:
        resolver = SecretResolver(
            named_reference_lookup=lambda name: {
                "provider": "literal",
                "value": f"value-for-{name}",
            },
        )

        value = resolver.resolve_text(
            "postgres://${TOKEN}", {"TOKEN": "stored:analytics-pass"}
        )

        self.assertEqual(value, "postgres://value-for-analytics-pass")

    def test_dispatches_vault_refs_and_reuses_dynamic_results_per_resolution(
        self,
    ) -> None:
        calls: list[tuple[str, str, str]] = []

        def lookup(
            reference: dict[str, object],
            *,
            resolution_cache: dict[str, object] | None = None,
        ) -> str:
            del resolution_cache
            calls.append(
                (
                    str(reference.get("kind")),
                    str(reference.get("mount")),
                    str(reference.get("field")),
                )
            )
            if reference.get("kind") == "dynamic":
                return (
                    "dyn-user" if reference.get("field") == "username" else "dyn-pass"
                )
            return "vault-secret"

        resolver = SecretResolver(vault_reference_lookup=lookup)

        value = resolver.resolve_text(
            "postgres://${DB_USER}:${DB_PASS}@localhost/app",
            {
                "DB_USER": "vault+dynamic://ops-vault/database/app#username",
                "DB_PASS": "vault+dynamic://ops-vault/database/app#password",
            },
        )

        self.assertEqual(value, "postgres://dyn-user:dyn-pass@localhost/app")
        self.assertEqual(
            calls,
            [
                ("dynamic", "database", "username"),
                ("dynamic", "database", "password"),
            ],
        )

    def test_rejects_vault_transit_interpolation(self) -> None:
        resolver = SecretResolver(
            vault_reference_lookup=lambda reference, *, resolution_cache=None: "ignored"
        )

        with self.assertRaisesRegex(ValueError, "transit"):
            resolver.resolve_ref("vault+transit://ops-vault/app-key")


if __name__ == "__main__":
    unittest.main()
