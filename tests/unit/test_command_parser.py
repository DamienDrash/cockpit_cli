import unittest

from cockpit.application.dispatch.command_parser import CommandParseError, CommandParser
from cockpit.shared.enums import CommandSource


class CommandParserTests(unittest.TestCase):
    def test_parser_handles_slash_command_with_positional_and_named_args(self) -> None:
        parser = CommandParser()

        command = parser.parse("/workspace open /tmp/project mode=replace")

        self.assertIs(command.source, CommandSource.SLASH)
        self.assertEqual(command.name, "workspace.open")
        self.assertEqual(command.args["argv"], ["/tmp/project"])
        self.assertEqual(command.args["mode"], "replace")

    def test_parser_supports_single_token_commands(self) -> None:
        parser = CommandParser()

        command = parser.parse("/session.restore")

        self.assertEqual(command.name, "session.restore")
        self.assertEqual(command.args["argv"], [])

    def test_parser_rejects_empty_input(self) -> None:
        parser = CommandParser()

        with self.assertRaises(CommandParseError):
            parser.parse("   ")


if __name__ == "__main__":
    unittest.main()

