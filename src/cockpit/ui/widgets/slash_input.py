"""Slash command input widget."""

from textual.widgets import Input


class SlashInput(Input):
    """Input field for slash commands."""

    def __init__(self) -> None:
        super().__init__(
            placeholder=(
                'Type /workspace open @prod, /db run_query "SELECT 1", '
                "/cron disable, /curl send GET https://example.com, or /session restore"
            ),
            id="slash-input",
        )
