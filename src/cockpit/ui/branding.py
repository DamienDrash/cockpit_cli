"""Branding and splash screen assets for Cockpit."""

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
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
    """Show a cyberpunk splash screen with animation."""
    
    # 1. Show Logo with Glow Effect
    logo_text = Text(LOGO, style=C_PRIMARY)
    console.print(Panel(logo_text, border_style=C_SECONDARY, padding=(1, 2), title="[bold white]v0.1.4[/]", subtitle="[dim]Keyboard-First TUI Platform[/]"))
    console.print()

    # 2. Initialization Animation
    tasks = [
        "Scanning workspace hardware...",
        "Linking Git adapters...",
        "Calibrating terminal engines...",
        "Igniting core platform spine...",
        "System READY."
    ]

    with Progress(
        SpinnerColumn(spinner_name="dots12", style=C_PRIMARY),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40, style=C_ACCENT, complete_style=C_PRIMARY),
        TaskProgressColumn(),
        console=console,
        transient=True,
    ) as progress:
        
        boot_task = progress.add_task("[bold white]INITIALIZING COCKPIT...", total=len(tasks))
        
        for step in tasks:
            progress.update(boot_task, description=f"[{C_SECONDARY}]{step}[/]")
            # Simulate variable load times
            time.sleep(random.uniform(0.2, 0.4))
            progress.advance(boot_task)
            
    # 3. Small "Matrix Trickle" after-effect (optional, fast)
    _matrix_trickle(console, 0.5)

def _matrix_trickle(console: Console, duration: float) -> None:
    """A very fast matrix-style character trickle for flavor."""
    chars = "0123456789ABCDEF@#$%&*"
    width = console.width
    start_time = time.time()
    
    with Live(Text(""), console=console, refresh_per_second=20, transient=True) as live:
        while time.time() - start_time < duration:
            line = "".join(random.choice(chars) if random.random() > 0.9 else " " for _ in range(width))
            live.update(Text(line, style="green dim"))
            time.sleep(0.05)
