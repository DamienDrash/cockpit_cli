"""Top-level application entrypoint."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace
from collections.abc import Sequence
from pathlib import Path
import shlex
import sys

from cockpit.application.services.connection_service import ConnectionService
from cockpit.infrastructure.config.config_loader import ConfigLoader


def build_arg_parser() -> ArgumentParser:
    """Create the cockpit CLI parser."""
    parser = ArgumentParser(prog="cockpit")
    subparsers = parser.add_subparsers(dest="subcommand")

    open_parser = subparsers.add_parser("open", help="Open a workspace when the app starts")
    open_parser.add_argument("path", nargs="?", default=".")
    open_parser.add_argument(
        "--connection",
        dest="connection",
        help="Open the workspace via a configured SSH connection alias.",
    )

    subparsers.add_parser("resume", help="Resume the most recent workspace/session")
    subparsers.add_parser("connections", help="List configured connection profiles")

    completion_parser = subparsers.add_parser(
        "completion",
        help="Print shell completion script",
    )
    completion_parser.add_argument("shell", choices=("bash", "zsh"))
    return parser


def startup_command_text_from_args(args: Namespace) -> str | None:
    """Map parsed CLI args into the shared command text format."""
    subcommand = getattr(args, "subcommand", None)
    if subcommand == "open":
        path = getattr(args, "path", ".")
        connection = getattr(args, "connection", None)
        if isinstance(connection, str) and connection:
            normalized_path = str(path or ".")
            profile_path = f"@{connection}"
            if normalized_path not in {".", ""}:
                profile_path = f"{profile_path}:{normalized_path}"
            return f"workspace open {shlex.quote(profile_path)}"
        return f"workspace open {shlex.quote(str(path))}"
    if subcommand == "resume":
        return "workspace reopen_last"
    return None


def list_connections_text(*, start: Path | None = None) -> str:
    """Render configured connection profiles for CLI output."""
    service = ConnectionService(ConfigLoader(start=start))
    profiles = service.list_profiles()
    if not profiles:
        return "No connection profiles configured."
    lines = ["Configured connections:"]
    for profile in profiles:
        description = f" - {profile.description}" if profile.description else ""
        lines.append(
            f"- {profile.alias}: {profile.target_ref} "
            f"(default_path={profile.default_path}){description}"
        )
    return "\n".join(lines)


def completion_script(shell: str) -> str:
    """Return a shell completion script for the lightweight CLI wrapper."""
    if shell == "zsh":
        return "\n".join(
            [
                "#compdef cockpit",
                "_cockpit() {",
                "  local -a commands",
                "  commands=(",
                "    'open:Open a workspace'",
                "    'resume:Resume the latest session'",
                "    'connections:List configured connection profiles'",
                "    'completion:Print completion script'",
                "  )",
                "  _arguments \\",
                "    '1:command:->command' \\",
                "    '*::arg:->args'",
                "  case $state in",
                "    command)",
                "      _describe 'command' commands",
                "      ;;",
                "    args)",
                "      case $words[2] in",
                "        open)",
                "          _arguments '--connection[Connection profile alias]' '1:path:_files -/'",
                "          ;;",
                "        completion)",
                "          _values 'shell' bash zsh",
                "          ;;",
                "      esac",
                "      ;;",
                "  esac",
                "}",
                "compdef _cockpit cockpit",
            ]
        )
    return "\n".join(
        [
            "_cockpit() {",
            "  local cur prev words cword",
            "  _init_completion || return",
            "  if [[ ${cword} -eq 1 ]]; then",
            "    COMPREPLY=( $(compgen -W 'open resume connections completion' -- \"$cur\") )",
            "    return",
            "  fi",
            "  case \"${words[1]}\" in",
            "    open)",
            "      if [[ \"$prev\" == '--connection' ]]; then",
            "        COMPREPLY=()",
            "        return",
            "      fi",
            "      COMPREPLY=( $(compgen -d -- \"$cur\") )",
            "      return",
            "      ;;",
            "    completion)",
            "      COMPREPLY=( $(compgen -W 'bash zsh' -- \"$cur\") )",
            "      return",
            "      ;;",
            "  esac",
            "}",
            "complete -F _cockpit cockpit",
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Cockpit application."""
    from cockpit.ui.screens.app_shell import CockpitApp

    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if getattr(args, "subcommand", None) == "connections":
        print(list_connections_text(start=Path.cwd()))
        return 0
    if getattr(args, "subcommand", None) == "completion":
        print(completion_script(args.shell))
        return 0
    app = CockpitApp(startup_command_text=startup_command_text_from_args(args))
    app.run()
    return 0
