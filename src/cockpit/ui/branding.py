"""Branding and splash screen assets for Cockpit - Optimized."""

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
import time
import random

# Cyberpunk Palette
C_PRIMARY = "bold cyan"
C_SECONDARY = "bold magenta"
C_ACCENT = "bright_blue"
C_DIM = "dim white"

LOGO = r"""
 ██████╗  ██████╗  ██████╗██╗  ██╗██████╗ ██╗████████╗
██╔════╝ ██╔═══██╗██╔════╝██║ ██╔╝██╔══██╗██║╚══██╔══╝
██║      ██║   ██║██║     █████╔╝ ██████╔╝██║   ██║   
██║      ██║   ██║██║     ██╔═██╗ ██╔═══╝ ██║   ██║   
╚██████╗ ╚██████╔╝╚██████╗██║  ██╗██║     ██║   ██║   
 ╚═════╝  ╚═════╝  ╚═════╝╚═╝  ╚═╝╚═╝     ╚═╝   ╚═╝   
"""


def show_splash(console: Console) -> None:
    """Show a cyberpunk splash screen with snappy animation."""

    logo_text = Text(LOGO, style=C_PRIMARY)
    console.print(
        Panel(
            logo_text,
            border_style=C_SECONDARY,
            padding=(1, 2),
            title="[bold white]v0.1.44[/]",
            subtitle="[dim]Keyboard-First TUI Platform[/]",
        )
    )
    console.print()

    # Reduced tasks and faster intervals for "snappier" feel
    tasks = [
        "Scanning Neural Links...",
        "Syncing Data Grids...",
        "Calibrating...",
        "System READY.",
    ]

    with Progress(
        SpinnerColumn(spinner_name="dots12", style=C_PRIMARY),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=30, style=C_ACCENT, complete_style=C_PRIMARY),
        console=console,
        transient=True,
    ) as progress:
        boot_task = progress.add_task("[bold white]BOOTING...", total=len(tasks))

        for step in tasks:
            progress.update(boot_task, description=f"[{C_SECONDARY}]{step}[/]")
            time.sleep(random.uniform(0.05, 0.15))  # Much faster
            progress.advance(boot_task)

    # Very short trickle or skip if resources are low
    _matrix_trickle(console, 0.3)


def _matrix_trickle(console: Console, duration: float) -> None:
    """Fast, low-resource matrix-style character trickle."""
    chars = "0123456789ABCDEF@#$%&*"
    width = min(console.width, 80)  # Limit width for performance
    start_time = time.time()

    with Live(Text(""), console=console, refresh_per_second=15, transient=True) as live:
        while time.time() - start_time < duration:
            line = "".join(
                random.choice(chars) if random.random() > 0.92 else " "
                for _ in range(width)
            )
            live.update(Text(line, style="green dim"))
            time.sleep(0.04)
