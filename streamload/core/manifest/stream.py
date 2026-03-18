"""Stream variant selection logic for Streamload.

Picks the best video, audio, and subtitle tracks from a parsed
:class:`StreamBundle` based on user preferences.  Used by the download
engine when auto-selection is enabled (no interactive prompt).
"""

from __future__ import annotations

import logging
import re

from streamload.models.stream import (
    AudioTrack,
    SelectedTracks,
    StreamBundle,
    SubtitleTrack,
    VideoTrack,
)

log = logging.getLogger(__name__)


class StreamSelector:
    """Select best tracks based on user preferences.

    The preference strings use the same ``"ita|it"`` pipe-delimited
    pattern that :class:`AppConfig` stores -- each token is matched
    case-insensitively against the track's ``language`` field.

    Usage::

        selector = StreamSelector()
        selected = selector.auto_select(bundle, preferred_audio="ita|it")
    """

    # -- Public API ---------------------------------------------------------

    def auto_select(
        self,
        bundle: StreamBundle,
        preferred_audio: str = "ita|it",
        preferred_subtitle: str = "ita|it",
    ) -> SelectedTracks:
        """Auto-select the best tracks from *bundle*.

        Strategy:
        - **Video:** highest resolution (by height), breaking ties with
          bitrate.
        - **Audio:** all tracks matching the first preferred language
          that has at least one hit; if none match, take the single best
          available track.
        - **Subtitles:** all non-forced tracks matching the first
          preferred language; if none match, no subtitles.

        Parameters
        ----------
        bundle:
            The full set of available tracks.
        preferred_audio:
            Pipe-delimited language codes (e.g. ``"ita|it"``).
        preferred_subtitle:
            Pipe-delimited language codes.

        Returns
        -------
        SelectedTracks:
            Ready-to-download selection.  ``video`` is always populated
            (unless the bundle has no video tracks, which would be an
            error state).

        Raises
        ------
        ValueError:
            If *bundle* contains no video tracks.
        """
        video = self.select_best_video(bundle.video)
        if video is None:
            raise ValueError("StreamBundle contains no video tracks")

        # -- Audio ----------------------------------------------------------
        audio_matches = self.filter_audio_by_language(
            bundle.audio, preferred_audio,
        )
        if audio_matches:
            # Pick the best from matched tracks (highest bitrate, preferring
            # more channels).
            audio = [self._best_audio(audio_matches)]
        elif bundle.audio:
            audio = [self._best_audio(bundle.audio)]
        else:
            audio = []

        # -- Subtitles ------------------------------------------------------
        sub_matches = self.filter_subtitle_by_language(
            bundle.subtitles, preferred_subtitle,
        )
        # Exclude forced tracks from auto-selection -- they are meant to
        # be embedded for foreign-language scenes, not standalone viewing.
        subtitles = [s for s in sub_matches if not s.forced]

        return SelectedTracks(
            video=video,
            audio=audio,
            subtitles=subtitles,
        )

    def select_best_video(
        self, tracks: list[VideoTrack],
    ) -> VideoTrack | None:
        """Select the highest-quality video track.

        Sorting priority:
        1. Resolution height (descending).
        2. Bitrate (descending, ``None`` treated as 0).

        Returns ``None`` when *tracks* is empty.
        """
        if not tracks:
            return None

        def _sort_key(t: VideoTrack) -> tuple[int, int]:
            return (t.height, t.bitrate or 0)

        return max(tracks, key=_sort_key)

    def filter_audio_by_language(
        self,
        tracks: list[AudioTrack],
        preferred: str,
    ) -> list[AudioTrack]:
        """Return audio tracks matching the preferred language pattern.

        *preferred* is a pipe-delimited list of language codes
        (e.g. ``"ita|it"``).  Each code is tried in order; the first
        one that matches at least one track wins and all tracks for
        that language are returned.

        If no track matches any code, an empty list is returned (the
        caller decides the fallback behaviour).
        """
        codes = self._parse_language_codes(preferred)
        if not codes:
            return []

        for code in codes:
            matches = [
                t for t in tracks
                if self._language_matches(t.language, code)
            ]
            if matches:
                return matches

        return []

    def filter_subtitle_by_language(
        self,
        tracks: list[SubtitleTrack],
        preferred: str,
    ) -> list[SubtitleTrack]:
        """Return subtitle tracks matching the preferred language pattern.

        Semantics are identical to :meth:`filter_audio_by_language`.
        """
        codes = self._parse_language_codes(preferred)
        if not codes:
            return []

        for code in codes:
            matches = [
                t for t in tracks
                if self._language_matches(t.language, code)
            ]
            if matches:
                return matches

        return []

    # -- Internal helpers ---------------------------------------------------

    @staticmethod
    def _parse_language_codes(preferred: str) -> list[str]:
        """Split a pipe-delimited preference string into normalised codes.

        Empty strings and whitespace-only tokens are discarded.
        """
        return [
            code.strip().lower()
            for code in preferred.split("|")
            if code.strip()
        ]

    @staticmethod
    def _language_matches(track_lang: str, code: str) -> bool:
        """Return ``True`` if *track_lang* matches *code*.

        Matching is case-insensitive and also succeeds when the track
        language *starts with* the code (so ``"it"`` matches ``"ita"``
        and ``"it-IT"``), or when the code starts with the track
        language (so ``"ita"`` matches ``"it"``).
        """
        lang = track_lang.lower()
        if lang == code:
            return True
        if lang.startswith(code) or code.startswith(lang):
            return True
        # Handle BCP-47 subtags: "it-IT" should match "it".
        if "-" in lang and lang.split("-")[0] == code:
            return True
        if "-" in code and code.split("-")[0] == lang:
            return True
        return False

    @staticmethod
    def _best_audio(tracks: list[AudioTrack]) -> AudioTrack:
        """Pick the single best audio track from a non-empty list.

        Prefers higher channel count, then higher bitrate.
        """
        def _channel_rank(ch: str) -> int:
            """Assign a numeric rank to a channel label for sorting."""
            mapping: dict[str, int] = {
                "1.0": 1,
                "2.0": 2,
                "5.1": 6,
                "7.1": 8,
            }
            if ch in mapping:
                return mapping[ch]
            # Try to parse "Nch" format.
            m = re.match(r"(\d+)", ch)
            return int(m.group(1)) if m else 2

        def _sort_key(t: AudioTrack) -> tuple[int, int]:
            return (_channel_rank(t.channels), t.bitrate or 0)

        return max(tracks, key=_sort_key)
