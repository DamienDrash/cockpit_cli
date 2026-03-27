"""Slash command input widget with semantic syntax highlighting."""

import re
from rich.highlighter import RegexHighlighter
from rich.text import Text
from textual.widgets import Input

from cockpit.ui.branding import C_PRIMARY, C_SECONDARY


class SlashCmdHighlighter(RegexHighlighter):
    """Semantic syntax highlighter for the slash command input.

    Styles:
    - Commands (/cmd): Cyan/Bold
    - Flags (--flag): Magenta/Italic
    - Targets (@target): Yellow
    - Quoted Strings: Green
    """

    base_style = ""
    highlights = [
        r"(?P<command>^/[a-z0-9_\.]+)",
        r"(?P<flag>--[a-z0-9_\-]+)",
        r"(?P<target>@[a-z0-9_\-\.]+)",
        r"(?P<string>\"[^\"]*\"|'[^']*')",
    ]

    def __init__(self) -> None:
        super().__init__()
        self.styles: dict[str, str] = {
            "command": f"{C_PRIMARY} bold",
            "flag": f"{C_SECONDARY} italic",
            "target": "bold yellow",
            "string": "green",
        }

    def highlight(self, text: Text) -> None:
        """Highlight text using internal style mapping."""
        for highlight in self.highlights:
            for match in re.finditer(highlight, text.plain):
                for name, value in match.groupdict().items():
                    if value and name in self.styles:
                        start, end = match.span(name)
                        text.stylize(self.styles[name], start, end)


class SlashInput(Input):
    """Input field for slash commands with Cyberpunk-themed highlighting."""

    def __init__(self) -> None:
        super().__init__(
            placeholder=(
                ' ❯ Type /workspace open @prod, /db run_query "SELECT 1", '
                "/cron disable, /curl send GET https://example.com..."
            ),
            id="slash-input",
            highlighter=SlashCmdHighlighter(),
        )
