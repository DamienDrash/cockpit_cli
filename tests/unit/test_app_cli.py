from argparse import Namespace
import unittest

from cockpit.app import startup_command_text_from_args


class CockpitCliTests(unittest.TestCase):
    def test_maps_open_subcommand_to_workspace_open_command(self) -> None:
        command_text = startup_command_text_from_args(
            Namespace(subcommand="open", path="/tmp/project dir")
        )

        self.assertEqual(command_text, "workspace open '/tmp/project dir'")

    def test_maps_resume_subcommand_to_workspace_reopen_last_command(self) -> None:
        command_text = startup_command_text_from_args(Namespace(subcommand="resume"))

        self.assertEqual(command_text, "workspace reopen_last")

    def test_returns_none_for_plain_launch(self) -> None:
        command_text = startup_command_text_from_args(Namespace(subcommand=None))

        self.assertIsNone(command_text)


if __name__ == "__main__":
    unittest.main()
