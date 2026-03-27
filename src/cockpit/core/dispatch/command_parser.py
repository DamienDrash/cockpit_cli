"""Command parsing."""

from __future__ import annotations

import re
import shlex

from cockpit.core.command import Command
from cockpit.core.enums import CommandSource
from cockpit.core.utils import make_id


class CommandParseError(ValueError):
    """Raised when a raw command string cannot be parsed."""


class CommandParser:
    """Parses slash and non-slash command input into `Command` objects."""

    _NAMED_ARG_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*=.*$")

    def parse(
        self,
        raw_input: str,
        *,
        source: CommandSource = CommandSource.SLASH,
        context: dict[str, object] | None = None,
    ) -> Command:
        text = raw_input.strip()
        if not text:
            raise CommandParseError("Command input cannot be empty.")

        if text.startswith("/"):
            text = text[1:].strip()

        tokens = shlex.split(text)
        if not tokens:
            raise CommandParseError("Command input cannot be empty.")

        if len(tokens) == 1:
            command_name = tokens[0]
            tail: list[str] = []
        else:
            if "." in tokens[0]:
                command_name = tokens[0]
                tail = tokens[1:]
            else:
                command_name = f"{tokens[0]}.{tokens[1]}"
                tail = tokens[2:]

        args: dict[str, object] = {"argv": []}
        argv = []
        for token in tail:
            if self._NAMED_ARG_RE.match(token):
                key, value = token.split("=", 1)
                args[key] = value
            else:
                argv.append(token)
        args["argv"] = argv

        return Command(
            id=make_id("cmd"),
            source=source,
            name=command_name,
            args=args,
            context=context or {},
        )
