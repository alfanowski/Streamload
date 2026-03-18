"""Search result and media tables for the Streamload CLI.

Renders search results, seasons, and episodes as rich tables with
color-coded type badges and score indicators.
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.text import Text

from streamload.models.media import Episode, MediaType, SearchResult, Season

# -- Colour mapping for media types ----------------------------------------

_TYPE_STYLES: dict[MediaType, str] = {
    MediaType.FILM: "bold cyan",
    MediaType.SERIE: "bold green",
    MediaType.ANIME: "bold magenta",
}

_TYPE_LABELS: dict[MediaType, str] = {
    MediaType.FILM: "Film",
    MediaType.SERIE: "Serie",
    MediaType.ANIME: "Anime",
}

# -- Score bar helpers -----------------------------------------------------

_SCORE_THRESHOLDS: list[tuple[float, str]] = [
    (0.8, "bold green"),
    (0.5, "bold yellow"),
    (0.0, "bold red"),
]


def _score_style(score: float) -> str:
    """Return a rich style string based on score value."""
    for threshold, style in _SCORE_THRESHOLDS:
        if score >= threshold:
            return style
    return "dim"


def _score_bar(score: float, width: int = 10) -> Text:
    """Build a coloured bar + percentage for a 0.0-1.0 score."""
    filled = round(score * width)
    bar = "\u2588" * filled + "\u2591" * (width - filled)
    pct = f" {score * 100:3.0f}%"
    style = _score_style(score)
    text = Text()
    text.append(bar, style=style)
    text.append(pct, style=style)
    return text


def _format_duration(seconds: int | None) -> str:
    """Format seconds as ``HH:MM:SS`` or ``MM:SS``."""
    if seconds is None:
        return "\u2014"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class SearchResultTable:
    """Renders search results in beautiful rich tables."""

    def __init__(self, console: Console) -> None:
        self._console = console

    # -- Public API --------------------------------------------------------

    def display(self, results: list[SearchResult], title: str = "") -> None:
        """Display search results in a formatted table.

        Columns: #, Title, Year, Type, Service, Language, Score.
        The *Type* column is colour-coded per :data:`_TYPE_STYLES`.
        """
        if not results:
            self._console.print("[dim]No results found.[/dim]")
            return

        table = Table(
            title=title or "Search Results",
            title_style="bold white",
            border_style="dim",
            show_lines=False,
            padding=(0, 1),
            expand=False,
        )

        table.add_column("#", style="dim", width=4, justify="right")
        table.add_column("Title", style="bold white", min_width=20, max_width=50)
        table.add_column("Year", style="dim cyan", width=6, justify="center")
        table.add_column("Type", width=7, justify="center")
        table.add_column("Service", style="blue", min_width=8, max_width=22)
        table.add_column("Score", width=18, justify="left")

        for idx, result in enumerate(results, start=1):
            entry = result.entry
            media_type = entry.type

            type_text = Text(
                _TYPE_LABELS.get(media_type, media_type.value),
                style=_TYPE_STYLES.get(media_type, ""),
            )
            year_str = str(entry.year) if entry.year else "\u2014"
            score_text = _score_bar(result.match_score)

            table.add_row(
                str(idx),
                entry.title,
                year_str,
                type_text,
                result.service_display_name,
                score_text,
            )

        self._console.print()
        self._console.print(table)
        self._console.print()

    def display_seasons(self, seasons: list[Season], title: str = "") -> None:
        """Display seasons in a compact table.

        Columns: #, Season, Episodes.
        """
        if not seasons:
            self._console.print("[dim]No seasons available.[/dim]")
            return

        table = Table(
            title=title or "Seasons",
            title_style="bold white",
            border_style="dim",
            show_lines=False,
            padding=(0, 1),
            expand=False,
        )

        table.add_column("#", style="dim", width=4, justify="right")
        table.add_column("Season", style="bold white", min_width=12)
        table.add_column("Episodes", style="cyan", width=10, justify="center")

        for idx, season in enumerate(seasons, start=1):
            display_name = season.title if season.title else f"Season {season.number}"
            episode_str = str(season.episode_count) if season.episode_count else "\u2014"
            table.add_row(str(idx), display_name, episode_str)

        self._console.print()
        self._console.print(table)
        self._console.print()

    def display_episodes(self, episodes: list[Episode], title: str = "") -> None:
        """Display episodes in a table.

        Columns: #, Episode, Title, Duration.
        """
        if not episodes:
            self._console.print("[dim]No episodes available.[/dim]")
            return

        table = Table(
            title=title or "Episodes",
            title_style="bold white",
            border_style="dim",
            show_lines=False,
            padding=(0, 1),
            expand=False,
        )

        table.add_column("#", style="dim", width=4, justify="right")
        table.add_column("Episode", style="bold cyan", width=8, justify="center")
        table.add_column("Title", style="white", min_width=20, max_width=50)
        table.add_column("Duration", style="dim", width=10, justify="right")

        for idx, ep in enumerate(episodes, start=1):
            table.add_row(
                str(idx),
                str(ep.number),
                ep.title,
                _format_duration(ep.duration),
            )

        self._console.print()
        self._console.print(table)
        self._console.print()
