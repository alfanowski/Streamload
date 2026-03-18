"""User input and message prompts for the Streamload CLI.

Provides text input, confirmations, numbered choices, and styled status
messages using rich panels and prompts.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.text import Text

_BANNER = r"""
  ____  _                            _                 _
 / ___|| |_ _ __ ___  __ _ _ __ ___ | | ___   __ _  __| |
 \___ \| __| '__/ _ \/ _` | '_ ` _ \| |/ _ \ / _` |/ _` |
  ___) | |_| | |  __/ (_| | | | | | | | (_) | (_| | (_| |
 |____/ \__|_|  \___|\__,_|_| |_| |_|_|\___/ \__,_|\__,_|
"""


class UIPrompts:
    """User input and confirmation prompts."""

    def __init__(self, console: Console) -> None:
        self._console = console

    # -- Input prompts -----------------------------------------------------

    def ask(self, message: str, default: str = "") -> str:
        """Ask for text input, returning the entered string."""
        return Prompt.ask(
            f"[bold cyan]>[/bold cyan] {message}",
            default=default or None,
            console=self._console,
        ) or ""

    def confirm(self, message: str, default: bool = True) -> bool:
        """Ask a yes/no confirmation question."""
        return Confirm.ask(
            f"[bold cyan]?[/bold cyan] {message}",
            default=default,
            console=self._console,
        )

    def choose(self, message: str, choices: list[str], default: int = 0) -> int:
        """Display numbered options and return the chosen index.

        Returns the zero-based index of the selected option.
        """
        self._console.print()
        self._console.print(f"[bold cyan]?[/bold cyan] {message}")
        for idx, choice in enumerate(choices):
            marker = "[bold cyan]>[/bold cyan]" if idx == default else " "
            self._console.print(f"  {marker} [bold]{idx + 1}[/bold]. {choice}")
        self._console.print()

        while True:
            raw = Prompt.ask(
                "[dim]Enter number[/dim]",
                default=str(default + 1),
                console=self._console,
            )
            try:
                selection = int(raw) - 1
                if 0 <= selection < len(choices):
                    return selection
            except (ValueError, TypeError):
                pass
            self._console.print(
                f"[red]Please enter a number between 1 and {len(choices)}.[/red]"
            )

    # -- Status messages ---------------------------------------------------

    def show_error(self, message: str) -> None:
        """Display an error message in a red panel."""
        self._console.print()
        self._console.print(
            Panel(
                Text(message, style="bold red"),
                title="Error",
                title_align="left",
                border_style="red",
                padding=(0, 1),
            )
        )

    def show_warning(self, message: str) -> None:
        """Display a warning message in yellow."""
        self._console.print(f"[bold yellow]![/bold yellow] {message}")

    def show_success(self, message: str) -> None:
        """Display a success message in green."""
        self._console.print(f"[bold green]\u2713[/bold green] {message}")

    def show_info(self, message: str) -> None:
        """Display an informational message."""
        self._console.print(f"[bold blue]i[/bold blue] {message}")

    def show_banner(self, version: str) -> None:
        """Display the Streamload startup banner with version string."""
        banner_text = Text(_BANNER, style="bold cyan")
        self._console.print(banner_text, highlight=False)
        self._console.print(
            f"  [dim]v{version}[/dim]  [dim]\u2502[/dim]  "
            f"[dim]Professional media downloader[/dim]",
        )
        self._console.print()
