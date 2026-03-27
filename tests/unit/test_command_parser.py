import unittest

from cockpit.core.dispatch.command_parser import CommandParseError, CommandParser
from cockpit.core.enums import CommandSource


class CommandParserTests(unittest.TestCase):
    def test_parser_handles_slash_command_with_positional_and_named_args(self) -> None:
        parser = CommandParser()

        command = parser.parse("/workspace open /tmp/project mode=replace")

        self.assertIs(command.source, CommandSource.SLASH)
        self.assertEqual(command.name, "workspace.open")
        self.assertEqual(command.args["argv"], ["/tmp/project"])
        self.assertEqual(command.args["mode"], "replace")

    def test_parser_keeps_equals_inside_quoted_positional_args(self) -> None:
        parser = CommandParser()

        command = parser.parse('/db run_query "UPDATE users SET active = 0"')

        self.assertEqual(command.name, "db.run_query")
        self.assertEqual(command.args["argv"], ["UPDATE users SET active = 0"])

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
