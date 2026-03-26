"""Top-level application entrypoint."""

from __future__ import annotations

import sys
import traceback
from argparse import ArgumentParser, Namespace
from collections.abc import Sequence
from pathlib import Path
import shlex
from threading import Thread
from time import sleep
import webbrowser

try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
except ImportError:
    print("Error: 'rich' library is missing. Install with pip install rich.")
    sys.exit(1)

from cockpit.application.services.connection_service import ConnectionService
from cockpit.infrastructure.config.config_loader import ConfigLoader
from cockpit.infrastructure.web.admin_server import LocalWebAdminServer
from cockpit.runtime.task_supervisor import SupervisedTaskContext
from cockpit.ui.branding import show_splash


def build_arg_parser() -> ArgumentParser:
    """Create the cockpit CLI parser."""
    parser = ArgumentParser(prog="cockpit-cli")
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
    subparsers.add_parser("datasources", help="List configured datasource profiles")

    admin_parser = subparsers.add_parser("admin", help="Run the local web admin server")
    admin_parser.add_argument("--host", default="127.0.0.1")
    admin_parser.add_argument("--port", type=int, default=8765)
    admin_parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Open the local admin URL in the default browser.",
    )

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


def list_connections(console: Console, *, start: Path | None = None) -> None:
    """Render configured connection profiles for CLI output using rich."""
    service = ConnectionService(ConfigLoader(start=start))
    profiles = service.list_profiles()

    console.print()
    if not profiles:
        console.print("[yellow]No connection profiles configured.[/yellow]")
        return

    table = Table(title="Configured Connections", box=box.ROUNDED, header_style="bold cyan")
    table.add_column("Alias", style="bold green")
    table.add_column("Target", style="white")
    table.add_column("Default Path", style="dim")
    table.add_column("Description", style="italic")

    for profile in profiles:
        table.add_row(
            profile.alias,
            profile.target_ref,
            profile.default_path or "/",
            profile.description or "",
        )

    console.print(table)
    console.print("\n[bold cyan]Next steps:[/bold cyan]")
    console.print("  • Open a connection: [green]cockpit-cli open --connection <alias>[/green]")
    console.print("  • List datasources:  [green]cockpit-cli datasources[/green]")
    console.print()


def list_datasources(console: Console, *, start: Path | None = None) -> None:
    """Render configured datasource profiles for CLI output using rich."""
    from cockpit.bootstrap import build_container

    container = build_container(start=start)
    try:
        profiles = container.data_source_service.list_profiles()
        console.print()
        if not profiles:
            console.print("[yellow]No datasource profiles configured.[/yellow]")
        else:
            table = Table(title="Configured Datasources", box=box.ROUNDED, header_style="bold cyan")
            table.add_column("Name", style="bold green")
            table.add_column("Backend", style="magenta")
            table.add_column("Target", style="white")

            for profile in profiles:
                target = profile.connection_url or profile.target_ref or "(unset)"
                table.add_row(profile.name, profile.backend, target)

            console.print(table)
            console.print("\n[bold cyan]Next steps:[/bold cyan]")
            console.print("  • Open workspace: [green]cockpit-cli open .[/green]")
            console.print("  • Run query:      [dim]Use the 'DB' tab inside the TUI[/dim]")
            console.print()
    finally:
        container.shutdown()


def completion_script(shell: str) -> str:
    """Return a shell completion script for the lightweight CLI wrapper."""
    if shell == "zsh":
        return "\n".join(
            [
                "#compdef cockpit",
                "_cockpit_cli() {",
                "  local a commands",
                "  commands=(",
                "    'open:Open a workspace'",
                "    'resume:Resume the latest session'",
                "    'connections:List configured connection profiles'",
                "    'datasources:List datasource profiles'",
                "    'admin:Run the local web admin server'",
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
                "compdef _cockpit_cli cockpit-cli",
            ]
        )
    return "\n".join(
        [
            "_cockpit_cli() {",
            "  local cur prev words cword",
            "  _init_completion || return",
            "  if [[ ${cword} -eq 1 ]]; then",
            "    COMPREPLY=( $(compgen -W 'open resume connections datasources admin completion' -- \"$cur\") )",
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
            "complete -F _cockpit_cli cockpit-cli",
        ]
    )


def run_admin_server_task(
    context: SupervisedTaskContext,
    *,
    server: LocalWebAdminServer,
) -> None:
    """Run the local web admin server under heartbeat supervision."""

    thread = Thread(
        target=server.serve_forever,
        name="cockpit-web-admin-http",
        daemon=True,
    )
    thread.start()
    try:
        while not context.stop_event.is_set():
            listen_url = server.listen_url()
            context.heartbeat(listen_url or "starting")
            if not thread.is_alive():
                raise RuntimeError("web admin server thread exited unexpectedly")
            sleep(0.5)
    finally:
        server.shutdown()
        thread.join(timeout=2.0)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Cockpit application with error reporting."""
    try:
        from cockpit.ui.screens.app_shell import CockpitApp

        console = Console()
        parser = build_arg_parser()
        
        cli_args = list(argv) if argv is not None else sys.argv[1:]
        args = parser.parse_args(cli_args)

        if getattr(args, "subcommand", None) == "connections":
            list_connections(console, start=Path.cwd())
            return 0

        if getattr(args, "subcommand", None) == "datasources":
            list_datasources(console, start=Path.cwd())
            return 0

        if getattr(args, "subcommand", None) == "admin":
            from cockpit.bootstrap import build_container

            container = build_container(start=Path.cwd())
            server = LocalWebAdminServer(
                container.web_admin_service,
                host=args.host,
                port=args.port,
            )
            try:
                container.task_supervisor.spawn_supervised(
                    "web-admin-server",
                    lambda context: run_admin_server_task(context, server=server),
                    heartbeat_timeout_seconds=3.0,
                    restartable=True,
                    metadata={
                        "component_id": "web-admin:local",
                        "component_kind": "web_admin",
                        "display_name": "Web Admin Server",
                    },
                )
                opened_browser = False
                while True:
                    listen_url = server.listen_url()
                    if listen_url and getattr(args, "open_browser", False) and not opened_browser:
                        webbrowser.open(listen_url, new=0, autoraise=True)
                        opened_browser = True
                    sleep(0.25)
            except KeyboardInterrupt:
                return 0
            finally:
                container.task_supervisor.stop("web-admin-server", timeout=2.0)
                server.shutdown()
                container.shutdown()
            return 0

        if getattr(args, "subcommand", None) == "completion":
            print(completion_script(args.shell))
            return 0

        # Splash Screen
        try:
            show_splash(console)
        except Exception:
            # Fallback if splash fails
            console.print("[dim]Booting engine...[/]")

        # Start App
        startup_cmd = startup_command_text_from_args(args)
        app = CockpitApp(startup_command_text=startup_cmd)
        app.run()
        return 0
        
    except Exception:
        print("\n[CRITICAL SYSTEM ERROR]", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
