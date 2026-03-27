"""Slash command input widget with semantic syntax highlighting."""

from rich.highlighter import RegexHighlighter
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


class SlashInput(Input):
    """Input field for slash commands with Cyberpunk-themed highlighting."""

    def __init__(self) -> None:
        highlighter = SlashCmdHighlighter()
        highlighter.styles["command"] = f"{C_PRIMARY} bold"
        highlighter.styles["flag"] = f"{C_SECONDARY} italic"
        highlighter.styles["target"] = "bold yellow"
        highlighter.styles["string"] = "green"

        super().__init__(
            placeholder=(
                ' ❯ Type /workspace open @prod, /db run_query "SELECT 1", '
                "/cron disable, /curl send GET https://example.com..."
            ),
            id="slash-input",
            highlighter=highlighter,
        )
