from argparse import Namespace
import unittest

from cockpit.app import completion_script, list_connections_text, startup_command_text_from_args


class CockpitCliTests(unittest.TestCase):
    def test_maps_open_subcommand_to_workspace_open_command(self) -> None:
        command_text = startup_command_text_from_args(
            Namespace(subcommand="open", path="/tmp/project dir")
        )

        self.assertEqual(command_text, "workspace open '/tmp/project dir'")

    def test_maps_resume_subcommand_to_workspace_reopen_last_command(self) -> None:
        command_text = startup_command_text_from_args(Namespace(subcommand="resume"))

        self.assertEqual(command_text, "workspace reopen_last")

    def test_maps_profile_open_subcommand_to_workspace_open_command(self) -> None:
        command_text = startup_command_text_from_args(
            Namespace(subcommand="open", path="/srv/app", connection="prod")
        )

        self.assertEqual(command_text, "workspace open @prod:/srv/app")

    def test_returns_none_for_plain_launch(self) -> None:
        command_text = startup_command_text_from_args(Namespace(subcommand=None))

        self.assertIsNone(command_text)

    def test_completion_script_mentions_commands(self) -> None:
        script = completion_script("bash")

        self.assertIn("open resume connections completion", script)

    def test_connections_listing_handles_empty_config(self) -> None:
        text = list_connections_text()

        self.assertEqual(text, "No connection profiles configured.")


if __name__ == "__main__":
    unittest.main()
