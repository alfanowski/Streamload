"""Formatting helpers for media items in the Streamload CLI.

Provides standalone functions that return rich-markup strings for
search results, episodes, seasons, and stream tracks.  These are
consumed by :class:`InteractiveSelector` and other UI components
that need formatted display labels.

The old ``SearchResultTable`` class has been removed -- display is
now handled by the interactive selector.  This module focuses solely
on producing well-formatted rich-markup strings for individual items.
"""

from __future__ import annotations

from streamload.models.media import Episode, MediaType, SearchResult, Season
from streamload.models.stream import AudioTrack, SubtitleTrack, VideoTrack

# ---------------------------------------------------------------------------
# Media type badge styles
# ---------------------------------------------------------------------------

_TYPE_BADGES: dict[MediaType, tuple[str, str]] = {
    MediaType.FILM: ("bold white on blue", "FILM"),
    MediaType.SERIE: ("bold white on magenta", "SERIE"),
    MediaType.ANIME: ("bold white on red", "ANIME"),
}

# ---------------------------------------------------------------------------
# Language display names (common ISO 639 codes)
# ---------------------------------------------------------------------------

_LANG_NAMES: dict[str, str] = {
    "ita": "Italian",
    "it": "Italian",
    "eng": "English",
    "en": "English",
    "spa": "Spanish",
    "es": "Spanish",
    "fra": "French",
    "fr": "French",
    "deu": "German",
    "de": "German",
    "por": "Portuguese",
    "pt": "Portuguese",
    "jpn": "Japanese",
    "ja": "Japanese",
    "kor": "Korean",
    "ko": "Korean",
    "zho": "Chinese",
    "zh": "Chinese",
    "ara": "Arabic",
    "ar": "Arabic",
    "rus": "Russian",
    "ru": "Russian",
    "hin": "Hindi",
    "hi": "Hindi",
    "und": "Unknown",
}


def _lang_display(code: str) -> str:
    """Return a human-readable language name for an ISO 639 code."""
    return _LANG_NAMES.get(code.lower(), code)


# ---------------------------------------------------------------------------
# Duration formatting
# ---------------------------------------------------------------------------


def _format_duration(seconds: int | None) -> str:
    """Format seconds as a human-readable duration string."""
    if seconds is None:
        return ""
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    remaining = minutes % 60
    if remaining:
        return f"{hours}h {remaining}m"
    return f"{hours}h"


# ---------------------------------------------------------------------------
# Bitrate formatting
# ---------------------------------------------------------------------------


def _format_bitrate(bps: int | None) -> str:
    """Format bits-per-second as a readable bitrate string."""
    if bps is None:
        return ""
    kbps = bps // 1000
    if kbps >= 1000:
        return f"{kbps / 1000:.1f}Mbps"
    return f"{kbps}kbps"


# ---------------------------------------------------------------------------
# Public formatting functions
# ---------------------------------------------------------------------------


def format_search_result(result: SearchResult) -> str:
    """Format a search result as a rich-markup string.

    Example output::

        [bold cyan][FILM][/] Cars - Motori ruggenti [dim](2006)[/] [dim]StreamingCommunity[/]
    """
    entry = result.entry
    media_type = entry.type

    # Type badge
    if media_type in _TYPE_BADGES:
        style, label = _TYPE_BADGES[media_type]
        badge = f"[{style}] {label} [/{style}]"
    else:
        badge = f"[bold]{media_type.value.upper()}[/bold]"

    # Title
    title = f"[bold white]{entry.title}[/bold white]"

    # Year
    year = f" [dim]({entry.year})[/dim]" if entry.year else ""

    # Service
    service = f" [dim]{result.service_display_name}[/dim]"

    return f"{badge} {title}{year}{service}"


def format_episode(episode: Episode) -> str:
    """Format an episode as a rich-markup string.

    Example output::

        E01 - Pilot [dim](45 min)[/]
    """
    ep_num = f"[bold cyan]E{episode.number:02d}[/bold cyan]"
    title = episode.title or ""
    duration = ""
    if episode.duration:
        duration = f" [dim]({_format_duration(episode.duration)})[/dim]"

    if title:
        return f"{ep_num} - {title}{duration}"
    return f"{ep_num}{duration}"


def format_season(season: Season) -> str:
    """Format a season as a rich-markup string.

    Example output::

        Season 1 [dim](10 episodes)[/]
    """
    name = season.title if season.title else f"Season {season.number}"
    label = f"[bold white]{name}[/bold white]"

    if season.episode_count:
        ep_word = "episode" if season.episode_count == 1 else "episodes"
        count = f" [dim]({season.episode_count} {ep_word})[/dim]"
    else:
        count = ""

    return f"{label}{count}"


def format_video_track(track: VideoTrack) -> str:
    """Format a video track as a rich-markup string.

    Example output::

        1080p [dim]h264 4500kbps[/] [bold yellow]HDR[/]
    """
    height = track.height
    resolution = f"{height}p" if height else track.resolution
    label = f"[bold white]{resolution}[/bold white]"

    details_parts: list[str] = [track.codec]
    if track.bitrate:
        details_parts.append(_format_bitrate(track.bitrate))
    if track.fps:
        details_parts.append(f"{track.fps:.0f}fps")

    details = " ".join(details_parts)
    result = f"{label} [dim]{details}[/dim]"

    if track.hdr:
        result += " [bold yellow]HDR[/bold yellow]"

    return result


def format_audio_track(track: AudioTrack) -> str:
    """Format an audio track as a rich-markup string.

    Example output::

        Italian [dim]aac 2.0[/]
    """
    lang = _lang_display(track.language)
    label = f"[bold white]{lang}[/bold white]"

    details_parts: list[str] = [track.codec]
    if track.channels:
        details_parts.append(track.channels)
    if track.bitrate:
        details_parts.append(_format_bitrate(track.bitrate))

    details = " ".join(details_parts)
    result = f"{label} [dim]{details}[/dim]"

    if track.name:
        result += f" [dim]({track.name})[/dim]"

    return result


def format_subtitle_track(track: SubtitleTrack) -> str:
    """Format a subtitle track as a rich-markup string.

    Example output::

        English [dim]vtt[/] [yellow][forced][/]
    """
    lang = _lang_display(track.language)
    label = f"[bold white]{lang}[/bold white]"
    fmt = f" [dim]{track.format}[/dim]"

    result = f"{label}{fmt}"

    if track.forced:
        result += " [yellow][forced][/yellow]"

    if track.name:
        result += f" [dim]({track.name})[/dim]"

    return result


def format_service(service: object) -> str:
    """Format a service name with language tag.

    Expects an object with ``name`` and ``language`` attributes (i.e.
    a :class:`ServiceBase` subclass).

    Example output::

        StreamingCommunity [dim](it)[/]
    """
    name = getattr(service, "name", str(service))
    language = getattr(service, "language", "")

    result = f"[bold white]{name}[/bold white]"
    if language:
        result += f" [dim]({language})[/dim]"

    return result
