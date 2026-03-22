"""Top-level application entrypoint."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace
from collections.abc import Sequence
import shlex


def build_arg_parser() -> ArgumentParser:
    """Create the cockpit CLI parser."""
    parser = ArgumentParser(prog="cockpit")
    subparsers = parser.add_subparsers(dest="subcommand")

    open_parser = subparsers.add_parser("open", help="Open a workspace when the app starts")
    open_parser.add_argument("path", nargs="?", default=".")

    subparsers.add_parser("resume", help="Resume the most recent workspace/session")
    return parser


def startup_command_text_from_args(args: Namespace) -> str | None:
    """Map parsed CLI args into the shared command text format."""
    subcommand = getattr(args, "subcommand", None)
    if subcommand == "open":
        path = getattr(args, "path", ".")
        return f"workspace open {shlex.quote(str(path))}"
    if subcommand == "resume":
        return "workspace reopen_last"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Cockpit application."""
    from cockpit.ui.screens.app_shell import CockpitApp

    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    app = CockpitApp(startup_command_text=startup_command_text_from_args(args))
    app.run()
    return 0
