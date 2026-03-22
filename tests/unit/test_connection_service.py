from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.application.services.connection_service import ConnectionService
from cockpit.infrastructure.config.config_loader import ConfigLoader


class ConnectionServiceTests(unittest.TestCase):
    def test_loads_declared_connection_profiles(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "config").mkdir(parents=True)
            (root / "src").mkdir()
            (root / "pyproject.toml").write_text("[project]\nname='cockpit'\n", encoding="utf-8")
            (root / "config" / "connections.yaml").write_text(
                "\n".join(
                    [
                        "connections:",
                        "  prod:",
                        "    target: deploy@example.com",
                        "    default_path: /srv/app",
                        "    description: Production app",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            service = ConnectionService(ConfigLoader(start=root))
            profile = service.get("prod")

            self.assertIsNotNone(profile)
            assert profile is not None
            self.assertEqual(profile.target_ref, "deploy@example.com")
            self.assertEqual(profile.default_path, "/srv/app")
            self.assertEqual(service.list_profiles()[0].alias, "prod")


if __name__ == "__main__":
    unittest.main()
