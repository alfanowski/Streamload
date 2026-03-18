"""FFmpeg merge operations for Streamload.

Combines video, audio, and subtitle tracks into a single output file
using FFmpeg.  Supports MKV and MP4 containers, codec metadata,
language tags, and optional GPU acceleration.

Nothing is printed to the console -- all diagnostics are logged to
the rotating file log.

Usage::

    merger = FFmpegMerger(config)
    final = merger.merge(
        video_path=Path("video.ts"),
        audio_paths=[Path("audio_ita.aac"), Path("audio_eng.aac")],
        subtitle_paths=[Path("sub_ita.srt")],
        output_path=Path("output.mkv"),
    )
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from streamload.core.exceptions import MergeError
from streamload.utils.logger import get_logger
from streamload.utils.system import SystemChecker

if TYPE_CHECKING:
    from streamload.models.config import ProcessConfig
    from streamload.models.stream import AudioTrack, SubtitleTrack

log = get_logger(__name__)


class FFmpegMerger:
    """Merges video, audio, and subtitle tracks using FFmpeg.

    Parameters
    ----------
    config:
        Post-processing configuration (GPU, merge flags, subtitle format).
    """

    def __init__(self, config: ProcessConfig) -> None:
        self._config = config
        self._ffmpeg = SystemChecker().get_ffmpeg_path() or "ffmpeg"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def merge(
        self,
        video_path: Path,
        audio_paths: list[Path],
        subtitle_paths: list[Path],
        output_path: Path,
        extension: str = "mkv",
        audio_tracks: list[AudioTrack] | None = None,
        subtitle_tracks: list[SubtitleTrack] | None = None,
    ) -> Path:
        """Merge video + audio tracks + subtitles into a final output file.

        FFmpeg command structure::

            ffmpeg -i video.ts -i audio_ita.aac -i audio_eng.aac -i sub_ita.srt
                   -map 0:v -map 1:a -map 2:a -map 3:s
                   -c copy
                   -metadata:s:a:0 language=ita
                   -metadata:s:a:1 language=eng
                   output.mkv

        Behaviour flags:

        - If ``config.merge_audio`` is ``False``: only the first audio
          track is included.
        - If ``config.merge_subtitle`` is ``False``: subtitles are
          skipped entirely.
        - If the video file is the only input and no merging is needed,
          a simple remux is performed instead.

        Parameters
        ----------
        video_path:
            Path to the downloaded video file.
        audio_paths:
            Paths to downloaded audio files (may be empty).
        subtitle_paths:
            Paths to downloaded subtitle files (may be empty).
        output_path:
            Desired output file path (extension is overridden by
            *extension*).
        extension:
            Container format: ``"mkv"`` or ``"mp4"``.
        audio_tracks:
            Track metadata for language tagging (parallel to
            *audio_paths*).
        subtitle_tracks:
            Track metadata for language tagging (parallel to
            *subtitle_paths*).

        Returns
        -------
        Path
            Absolute path to the final merged file.

        Raises
        ------
        MergeError
            If FFmpeg exits with a non-zero return code.
        """
        # Ensure correct extension on the output path.
        final_path = output_path.with_suffix(f".{extension}")
        final_path.parent.mkdir(parents=True, exist_ok=True)

        # Filter based on config flags.
        effective_audio = self._filter_audio_paths(audio_paths)
        effective_subs = self._filter_subtitle_paths(subtitle_paths)
        effective_audio_tracks = self._filter_audio_tracks(audio_tracks)
        effective_sub_tracks = self._filter_subtitle_tracks(subtitle_tracks)

        # If there is nothing to merge (no extra audio or subs), just remux.
        if not effective_audio and not effective_subs:
            log.info("No additional tracks to merge -- performing simple remux")
            return self.remux(video_path, final_path)

        cmd = self._build_merge_command(
            video=video_path,
            audios=effective_audio,
            subs=effective_subs,
            output=final_path,
            audio_tracks=effective_audio_tracks,
            subtitle_tracks=effective_sub_tracks,
            extension=extension,
        )

        log.info("Merging %d inputs -> %s", 1 + len(effective_audio) + len(effective_subs), final_path)
        self._run_ffmpeg(cmd)
        log.info("Merge complete: %s", final_path)

        return final_path

    def remux(self, input_path: Path, output_path: Path) -> Path:
        """Simple remux (container change) without re-encoding.

        Copies all streams from *input_path* into *output_path* using
        ``-c copy``.  Useful for TS -> MKV or MP4 container changes.

        Parameters
        ----------
        input_path:
            Source media file.
        output_path:
            Destination file (container determined by extension).

        Returns
        -------
        Path
            The *output_path* after successful remuxing.

        Raises
        ------
        MergeError
            If FFmpeg fails.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            self._ffmpeg,
            "-hide_banner",
            "-loglevel", "warning",
            "-y",
            "-i", str(input_path),
            "-c", "copy",
            str(output_path),
        ]

        log.info("Remuxing %s -> %s", input_path.name, output_path.name)
        self._run_ffmpeg(cmd)

        return output_path

    # ------------------------------------------------------------------
    # Command building
    # ------------------------------------------------------------------

    def _build_merge_command(
        self,
        video: Path,
        audios: list[Path],
        subs: list[Path],
        output: Path,
        audio_tracks: list[AudioTrack] | None = None,
        subtitle_tracks: list[SubtitleTrack] | None = None,
        extension: str = "mkv",
    ) -> list[str]:
        """Build the full FFmpeg command with inputs, maps, codecs, and metadata.

        Parameters
        ----------
        video:
            Video input file.
        audios:
            Audio input files.
        subs:
            Subtitle input files.
        output:
            Output file path.
        audio_tracks:
            Audio track metadata for language tags.
        subtitle_tracks:
            Subtitle track metadata for language tags.
        extension:
            Output container format.

        Returns
        -------
        list[str]
            Complete FFmpeg command as a list of arguments.
        """
        audio_tracks = audio_tracks or []
        subtitle_tracks = subtitle_tracks or []

        cmd: list[str] = [self._ffmpeg, "-hide_banner", "-loglevel", "warning", "-y"]

        # -- GPU acceleration (advisory, mainly useful for transcoding) -----
        if self._config.use_gpu:
            cmd.extend(self._get_hwaccel_flags())

        # -- Input files ---------------------------------------------------
        cmd.extend(["-i", str(video)])
        for audio_path in audios:
            cmd.extend(["-i", str(audio_path)])
        for sub_path in subs:
            cmd.extend(["-i", str(sub_path)])

        # -- Stream mapping ------------------------------------------------
        # Input index 0 = video, 1..N = audio, N+1..M = subtitles.
        cmd.extend(["-map", "0:v:0"])

        audio_start_idx = 1
        for i in range(len(audios)):
            cmd.extend(["-map", f"{audio_start_idx + i}:a:0"])

        sub_start_idx = audio_start_idx + len(audios)
        for i in range(len(subs)):
            cmd.extend(["-map", f"{sub_start_idx + i}:0"])

        # -- Codec configuration -------------------------------------------
        cmd.extend(self._get_codec_flags(extension, has_subs=bool(subs)))

        # -- Language metadata for audio streams ---------------------------
        for i, audio_path in enumerate(audios):
            language = self._extract_language_from_track(
                index=i,
                tracks=audio_tracks,
                filepath=audio_path,
            )
            if language:
                cmd.extend([f"-metadata:s:a:{i}", f"language={language}"])

            # Set audio track title from track metadata if available.
            title = self._extract_title_from_track(i, audio_tracks)
            if title:
                cmd.extend([f"-metadata:s:a:{i}", f"title={title}"])

        # -- Language metadata for subtitle streams ------------------------
        for i, sub_path in enumerate(subs):
            language = self._extract_language_from_track(
                index=i,
                tracks=subtitle_tracks,
                filepath=sub_path,
            )
            if language:
                cmd.extend([f"-metadata:s:s:{i}", f"language={language}"])

            # Forced flag for subtitle tracks.
            is_forced = self._is_forced_subtitle(i, subtitle_tracks)
            if is_forced:
                cmd.extend([f"-disposition:s:{i}", "forced"])
                cmd.extend([f"-metadata:s:s:{i}", "title=Forced"])

        # -- Output file ---------------------------------------------------
        cmd.append(str(output))

        log.debug("FFmpeg command: %s", " ".join(cmd))
        return cmd

    def _get_codec_flags(
        self,
        extension: str,
        has_subs: bool,
    ) -> list[str]:
        """Return codec flags for the merge command.

        Default is ``-c copy`` (stream copy, no re-encoding).  Overrides
        are applied when the config specifies custom video/audio params.

        For MP4 containers with subtitle tracks, subtitles are converted
        to ``mov_text`` since MP4 has limited subtitle codec support.

        Returns
        -------
        list[str]
            FFmpeg codec arguments.
        """
        flags: list[str] = []

        # Video codec: copy by default.
        flags.extend(["-c:v", "copy"])

        # Audio codec: copy by default.
        flags.extend(["-c:a", "copy"])

        # Subtitle codec: depends on container.
        if has_subs:
            if extension == "mp4":
                # MP4 only supports mov_text subtitles.
                flags.extend(["-c:s", "mov_text"])
            else:
                # MKV supports virtually every subtitle format.
                flags.extend(["-c:s", "copy"])

        return flags

    @staticmethod
    def _get_hwaccel_flags() -> list[str]:
        """Return hardware acceleration flags for FFmpeg.

        These are advisory -- FFmpeg will fall back to software decoding
        if the hardware is not available.  Hardware acceleration is mainly
        useful when transcoding (re-encoding), not when stream-copying.

        Returns
        -------
        list[str]
            Hardware acceleration arguments.
        """
        # Auto-detect the best available hardware.
        return ["-hwaccel", "auto"]

    # ------------------------------------------------------------------
    # Track metadata extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_language_from_track(
        index: int,
        tracks: list[AudioTrack] | list[SubtitleTrack],
        filepath: Path,
    ) -> str | None:
        """Extract the ISO 639 language code for a track.

        Tries the track metadata first; falls back to parsing the
        filename (e.g. ``dl_abc_audio_ita_0.ts``).

        Parameters
        ----------
        index:
            Index into *tracks*.
        tracks:
            List of track metadata objects.
        filepath:
            Downloaded file path (used as fallback).

        Returns
        -------
        str | None
            Language code, or ``None`` if undetermined.
        """
        # Try metadata first.
        if index < len(tracks):
            lang = tracks[index].language
            if lang:
                return lang

        # Fallback: parse from filename.
        # Convention: dl_<id>_audio_<lang>_<idx>.ext
        #          or dl_<id>_sub_<lang>_<idx>.ext
        parts = filepath.stem.split("_")
        # Look for a 2-3 letter language code after "audio" or "sub".
        for i, part in enumerate(parts):
            if part in ("audio", "sub") and i + 1 < len(parts):
                candidate = parts[i + 1]
                if 2 <= len(candidate) <= 3 and candidate.isalpha():
                    return candidate

        return None

    @staticmethod
    def _extract_title_from_track(
        index: int,
        tracks: list[AudioTrack] | list[SubtitleTrack],
    ) -> str | None:
        """Extract a display title for an audio or subtitle track.

        Returns the track's ``name`` field if available, otherwise
        constructs a label from the language and codec/format.
        """
        if index >= len(tracks):
            return None

        track = tracks[index]
        if hasattr(track, "name") and track.name:
            return track.name

        # Build a label from available metadata.
        parts: list[str] = []
        if track.language:
            parts.append(track.language.upper())
        if hasattr(track, "codec") and track.codec:
            parts.append(track.codec.upper())
        if hasattr(track, "channels") and track.channels:
            parts.append(track.channels)

        return " ".join(parts) if parts else None

    @staticmethod
    def _is_forced_subtitle(
        index: int,
        tracks: list[SubtitleTrack],
    ) -> bool:
        """Check whether a subtitle track is flagged as forced."""
        if index < len(tracks):
            return tracks[index].forced
        return False

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _filter_audio_paths(self, paths: list[Path]) -> list[Path]:
        """Apply ``config.merge_audio`` policy to audio file list.

        If merge_audio is disabled, only the first audio track is kept.
        """
        if not paths:
            return []
        if not self._config.merge_audio:
            return paths[:1]
        return list(paths)

    def _filter_subtitle_paths(self, paths: list[Path]) -> list[Path]:
        """Apply ``config.merge_subtitle`` policy to subtitle file list.

        If merge_subtitle is disabled, no subtitles are included.
        """
        if not self._config.merge_subtitle:
            return []
        return list(paths)

    def _filter_audio_tracks(
        self,
        tracks: list[AudioTrack] | None,
    ) -> list[AudioTrack]:
        """Filter audio track metadata to match filtered audio paths."""
        if not tracks:
            return []
        if not self._config.merge_audio:
            return tracks[:1]
        return list(tracks)

    def _filter_subtitle_tracks(
        self,
        tracks: list[SubtitleTrack] | None,
    ) -> list[SubtitleTrack]:
        """Filter subtitle track metadata to match filtered subtitle paths."""
        if not tracks:
            return []
        if not self._config.merge_subtitle:
            return []
        return list(tracks)

    # ------------------------------------------------------------------
    # FFmpeg execution
    # ------------------------------------------------------------------

    def _run_ffmpeg(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        """Run an FFmpeg command and return the result.

        Captures stderr for error diagnosis.  Raises :class:`MergeError`
        on non-zero exit codes with the last lines of FFmpeg's stderr
        attached.

        Parameters
        ----------
        cmd:
            Complete FFmpeg command as a list of arguments.

        Returns
        -------
        subprocess.CompletedProcess
            The completed process result.

        Raises
        ------
        MergeError
            If FFmpeg exits with a non-zero return code or cannot be
            started.
        """
        log.debug("Running FFmpeg: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hour timeout for very long merges
            )
        except FileNotFoundError:
            raise MergeError(
                f"FFmpeg not found at '{self._ffmpeg}'. "
                f"Install: {SystemChecker.get_install_instructions('ffmpeg')}"
            )
        except subprocess.TimeoutExpired as exc:
            raise MergeError(
                "FFmpeg process timed out after 1 hour",
                stderr=str(exc.stderr) if exc.stderr else None,
            ) from exc
        except OSError as exc:
            raise MergeError(
                f"Failed to start FFmpeg: {exc}",
            ) from exc

        if result.returncode != 0:
            stderr = result.stderr.strip() if result.stderr else ""
            log.error(
                "FFmpeg exited with code %d. stderr:\n%s",
                result.returncode, stderr,
            )
            raise MergeError(
                f"FFmpeg exited with code {result.returncode}",
                stderr=stderr,
            )

        if result.stderr:
            # Log warnings from FFmpeg even on success.
            log.debug("FFmpeg stderr (success): %s", result.stderr.strip())

        return result
