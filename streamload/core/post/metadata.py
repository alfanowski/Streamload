"""NFO metadata file generation for Streamload.

Generates ``.nfo`` XML files compatible with Plex, Kodi, Emby, and
Jellyfin media library managers.  These files provide metadata (title,
year, genre, plot, season/episode numbers) so media scanners can
correctly identify and organise downloaded content.

Nothing is printed to the console -- diagnostics go to the log file.

Usage::

    gen = NFOGenerator()
    gen.generate_movie_nfo(entry, output_dir=Path("./Film/Movie (2024)"))
    gen.generate_episode_nfo(episode, entry, output_dir=Path("./Serie/Show/S01"))
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

from streamload.utils.logger import get_logger

if TYPE_CHECKING:
    from streamload.models.media import Episode, MediaEntry

log = get_logger(__name__)


class NFOGenerator:
    """Generate ``.nfo`` metadata files for media library managers.

    Produces Kodi-compatible NFO XML that is also understood by Plex
    (with the XBMCnfoMoviesImporter agent), Emby, and Jellyfin.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_movie_nfo(
        self,
        entry: MediaEntry,
        output_dir: Path,
    ) -> Path:
        """Generate a ``movie.nfo`` file for a film.

        The file is placed in *output_dir* with the standard Kodi
        filename ``movie.nfo``.

        Parameters
        ----------
        entry:
            The film's metadata.
        output_dir:
            Directory where the NFO file will be written.

        Returns
        -------
        Path
            Absolute path to the generated NFO file.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        nfo_path = output_dir / "movie.nfo"

        xml_content = self._build_movie_xml(entry)
        nfo_path.write_text(xml_content, encoding="utf-8")

        log.info("Generated movie NFO: %s", nfo_path)
        return nfo_path

    def generate_episode_nfo(
        self,
        episode: Episode,
        entry: MediaEntry,
        output_dir: Path,
    ) -> Path:
        """Generate an episode ``.nfo`` file.

        The file is named after the episode using Kodi conventions
        (e.g. ``Show S01E03.nfo``).

        Parameters
        ----------
        episode:
            The episode's metadata.
        entry:
            The parent series/anime metadata.
        output_dir:
            Directory where the NFO file will be written.

        Returns
        -------
        Path
            Absolute path to the generated NFO file.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # Build a filename that matches the video file naming convention.
        safe_title = _sanitize_for_filename(entry.title)
        nfo_filename = (
            f"{safe_title} S{episode.season_number:02d}E{episode.number:02d}.nfo"
        )
        nfo_path = output_dir / nfo_filename

        xml_content = self._build_episode_xml(episode, entry)
        nfo_path.write_text(xml_content, encoding="utf-8")

        log.info("Generated episode NFO: %s", nfo_path)
        return nfo_path

    # ------------------------------------------------------------------
    # XML builders
    # ------------------------------------------------------------------

    def _build_movie_xml(self, entry: MediaEntry) -> str:
        """Build a Kodi-compatible movie NFO XML document.

        Schema reference:
        https://kodi.wiki/view/NFO_files/Movies

        Parameters
        ----------
        entry:
            The film's metadata.

        Returns
        -------
        str
            Complete XML document as a string.
        """
        lines: list[str] = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            "<movie>",
            f"  <title>{escape(entry.title)}</title>",
        ]

        if entry.year is not None:
            lines.append(f"  <year>{entry.year}</year>")

        if entry.description:
            lines.append(f"  <plot>{escape(entry.description)}</plot>")
            lines.append(f"  <outline>{escape(self._truncate(entry.description, 200))}</outline>")

        if entry.genre:
            # Genre may contain comma-separated values.
            for genre in entry.genre.split(","):
                genre = genre.strip()
                if genre:
                    lines.append(f"  <genre>{escape(genre)}</genre>")

        if entry.image_url:
            lines.append("  <thumb>")
            lines.append(f"    <thumb aspect=\"poster\">{escape(entry.image_url)}</thumb>")
            lines.append("  </thumb>")

        if entry.url:
            lines.append(f"  <uniqueid type=\"streamload\">{escape(entry.id)}</uniqueid>")

        lines.append(f"  <source>{escape(entry.service)}</source>")
        lines.append("</movie>")

        return "\n".join(lines) + "\n"

    def _build_episode_xml(
        self,
        episode: Episode,
        entry: MediaEntry,
    ) -> str:
        """Build a Kodi-compatible episode NFO XML document.

        Schema reference:
        https://kodi.wiki/view/NFO_files/TV_shows

        Parameters
        ----------
        episode:
            The episode's metadata.
        entry:
            The parent series/anime metadata.

        Returns
        -------
        str
            Complete XML document as a string.
        """
        lines: list[str] = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            "<episodedetails>",
            f"  <title>{escape(episode.title)}</title>",
            f"  <showtitle>{escape(entry.title)}</showtitle>",
            f"  <season>{episode.season_number}</season>",
            f"  <episode>{episode.number}</episode>",
        ]

        if episode.duration is not None:
            # Kodi expects runtime in minutes.
            runtime_minutes = max(1, episode.duration // 60)
            lines.append(f"  <runtime>{runtime_minutes}</runtime>")

        if entry.description:
            lines.append(f"  <plot>{escape(entry.description)}</plot>")

        if entry.genre:
            for genre in entry.genre.split(","):
                genre = genre.strip()
                if genre:
                    lines.append(f"  <genre>{escape(genre)}</genre>")

        if entry.image_url:
            lines.append(f"  <thumb>{escape(entry.image_url)}</thumb>")

        if episode.id:
            lines.append(
                f"  <uniqueid type=\"streamload\">{escape(episode.id)}</uniqueid>"
            )

        lines.append(f"  <source>{escape(entry.service)}</source>")
        lines.append("</episodedetails>")

        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _truncate(text: str, max_length: int) -> str:
        """Truncate *text* to *max_length* characters, appending '...' if trimmed."""
        if len(text) <= max_length:
            return text
        return text[: max_length - 3].rstrip() + "..."


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _sanitize_for_filename(name: str) -> str:
    """Remove characters that are unsafe in filenames.

    Replaces problematic characters with spaces and collapses runs
    of whitespace.
    """
    import re
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", name)
    sanitized = re.sub(r"\s{2,}", " ", sanitized)
    return sanitized.strip(" .")
