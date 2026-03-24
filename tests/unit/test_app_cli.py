from argparse import Namespace
from threading import Event
import unittest

from cockpit.app import (
    build_arg_parser,
    completion_script,
    list_connections_text,
    run_admin_server_task,
    startup_command_text_from_args,
)


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

        self.assertIn("open resume connections datasources admin completion", script)
        self.assertIn("cockpit-cli", script)

    def test_parser_prog_uses_public_command_name(self) -> None:
        parser = build_arg_parser()

        self.assertEqual(parser.prog, "cockpit-cli")

    def test_connections_listing_handles_empty_config(self) -> None:
        text = list_connections_text()

        self.assertEqual(text, "No connection profiles configured.")

    def test_run_admin_server_task_heartbeats_and_shuts_down(self) -> None:
        class _FakeServer:
            def __init__(self) -> None:
                self._stop = Event()
                self.shutdown_calls = 0

            def serve_forever(self) -> None:
                self._stop.wait(1.0)

            def shutdown(self) -> None:
                self.shutdown_calls += 1
                self._stop.set()

            def listen_url(self) -> str | None:
                return "http://127.0.0.1:8765"

        class _FakeContext:
            def __init__(self) -> None:
                self.stop_event = Event()
                self.messages: list[str] = []

            def heartbeat(self, message: str | None = None) -> None:
                if message is not None:
                    self.messages.append(message)
                self.stop_event.set()

        server = _FakeServer()
        context = _FakeContext()

        run_admin_server_task(context, server=server)

        self.assertEqual(server.shutdown_calls, 1)
        self.assertEqual(context.messages, ["http://127.0.0.1:8765"])


if __name__ == "__main__":
    unittest.main()
