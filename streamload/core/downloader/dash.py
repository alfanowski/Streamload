"""DASH download engine for Streamload.

Downloads MPEG-DASH (MPD) streams segment-by-segment with
multi-threaded fetching.  Structurally similar to the HLS engine but
adapted for DASH specifics:

* Uses :class:`MPDParser` and :class:`DASHSegment` instead of M3U8
  equivalents.
* Handles init segments that must be prepended to the media stream.
* Does **not** deal with AES-128 encryption -- DRM decryption is
  managed externally by :class:`DRMManager` before the download
  engine is invoked.

All status updates flow through the :class:`EventCallbacks` interface.
Nothing is printed to the console.
"""

from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path

from streamload.core.downloader.base import BaseDownloader
from streamload.core.events import DownloadProgress, EventCallbacks, WarningEvent
from streamload.core.manifest.mpd import DASHRepresentation, DASHSegment, MPDParser
from streamload.models.config import DownloadConfig
from streamload.models.stream import SelectedTracks
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

# Size of the buffer used when concatenating temp segment files.
_CONCAT_BUFFER: int = 1024 * 1024  # 1 MB


class DASHDownloader(BaseDownloader):
    """Downloads DASH/MPD streams with multi-threaded segment fetching.

    Tracks are processed sequentially; segments within each track are
    fetched in parallel via :class:`~concurrent.futures.ThreadPoolExecutor`.
    """

    def __init__(self, http_client: HttpClient, config: DownloadConfig) -> None:
        super().__init__(http_client, config)
        self._parser = MPDParser()
        # Cache for the raw MPD text so we don't re-fetch it per track.
        self._mpd_cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def download(
        self,
        download_id: str,
        tracks: SelectedTracks,
        output_dir: Path,
        callbacks: EventCallbacks,
    ) -> list[Path]:
        """Download DASH streams for every selected track.

        For each track:

        1. Parse MPD to get segments for the selected representation.
        2. Download the init segment (if present).
        3. Download all media segments in parallel.
        4. Concatenate init + media segments into a single file.
        5. Report progress via *callbacks*.

        Returns
        -------
        list[Path]
            Paths to the downloaded track files.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        downloaded: list[Path] = []

        # -- Video track ---------------------------------------------------
        video = tracks.video
        video_ext = self._guess_extension(video.codec)
        video_filename = self._generate_temp_filename(
            download_id, "video", video_ext,
        )
        video_path = output_dir / video_filename
        log.info("DASH download [%s] video rep=%s", download_id, video.id)

        video_rep = self._get_representation(video.id)
        if video_rep and video_rep.segments:
            result = self._download_segments(
                segments=video_rep.segments,
                init_url=video_rep.init_url,
                output_path=video_path,
                download_id=download_id,
                filename=video_filename,
                callbacks=callbacks,
            )
            downloaded.append(result)
        else:
            log.warning("DASH [%s] no segments for video rep %s", download_id, video.id)

        # -- Audio tracks --------------------------------------------------
        for idx, audio in enumerate(tracks.audio):
            if not audio.id:
                continue
            label = f"audio_{audio.language}_{idx}"
            audio_ext = self._guess_extension(audio.codec)
            audio_filename = self._generate_temp_filename(
                download_id, label, audio_ext,
            )
            audio_path = output_dir / audio_filename
            log.info("DASH download [%s] audio %s rep=%s", download_id, label, audio.id)

            audio_rep = self._get_representation(audio.id)
            if audio_rep and audio_rep.segments:
                result = self._download_segments(
                    segments=audio_rep.segments,
                    init_url=audio_rep.init_url,
                    output_path=audio_path,
                    download_id=download_id,
                    filename=audio_filename,
                    callbacks=callbacks,
                )
                downloaded.append(result)
            else:
                log.warning(
                    "DASH [%s] no segments for audio rep %s",
                    download_id, audio.id,
                )

        # -- Subtitle tracks -----------------------------------------------
        for idx, sub in enumerate(tracks.subtitles):
            if not sub.id:
                continue
            label = f"sub_{sub.language}_{idx}"
            sub_filename = self._generate_temp_filename(
                download_id, label, sub.format,
            )
            sub_path = output_dir / sub_filename
            log.info("DASH download [%s] subtitle %s rep=%s", download_id, label, sub.id)

            sub_rep = self._get_representation(sub.id)
            if sub_rep and sub_rep.segments:
                result = self._download_segments(
                    segments=sub_rep.segments,
                    init_url=sub_rep.init_url,
                    output_path=sub_path,
                    download_id=download_id,
                    filename=sub_filename,
                    callbacks=callbacks,
                )
                downloaded.append(result)
            elif sub_rep and sub_rep.init_url:
                # Single-segment subtitle (e.g. TTML in a single file).
                self._download_single_file(sub_rep.init_url, sub_path)
                if sub_path.exists():
                    downloaded.append(sub_path)
            else:
                log.warning(
                    "DASH [%s] no segments for subtitle rep %s",
                    download_id, sub.id,
                )

        return downloaded

    # ------------------------------------------------------------------
    # MPD manifest helpers
    # ------------------------------------------------------------------

    def set_mpd(self, manifest_url: str, mpd_text: str) -> None:
        """Pre-load an MPD manifest so it is not re-fetched.

        The orchestrator typically fetches the manifest once and passes
        it here before calling :meth:`download`.

        Parameters
        ----------
        manifest_url:
            The URL the MPD was fetched from (used for URL resolution).
        mpd_text:
            The raw XML text of the MPD document.
        """
        self._mpd_cache[manifest_url] = mpd_text

    def _get_representation(
        self, representation_id: str,
    ) -> DASHRepresentation | None:
        """Resolve segment list for a given representation.

        Iterates over all cached MPD manifests and returns the first
        non-empty representation that matches *representation_id*.
        """
        for manifest_url, mpd_text in self._mpd_cache.items():
            rep = self._parser.get_segments(mpd_text, manifest_url, representation_id)
            if rep.segments:
                return rep
        log.warning("Representation %r not found in any cached MPD", representation_id)
        return None

    # ------------------------------------------------------------------
    # Segment download pipeline
    # ------------------------------------------------------------------

    def _download_segments(
        self,
        segments: list[DASHSegment],
        init_url: str | None,
        output_path: Path,
        download_id: str,
        filename: str,
        callbacks: EventCallbacks,
    ) -> Path:
        """Download DASH segments with threading and concatenate.

        Parameters
        ----------
        segments:
            Ordered list of media segments.
        init_url:
            Optional initialization segment URL.
        output_path:
            Final concatenated output file.
        download_id:
            Unique download identifier for progress events.
        filename:
            Display name used in progress events.
        callbacks:
            Event interface for progress reporting.

        Returns
        -------
        Path
            The *output_path* after successful concatenation.
        """
        total_segments = len(segments)
        temp_dir = output_path.parent / f".tmp_{output_path.stem}"
        temp_dir.mkdir(parents=True, exist_ok=True)

        # -- Download init segment ----------------------------------------
        init_data: bytes | None = None
        if init_url:
            try:
                resp = self._http.get(init_url)
                resp.raise_for_status()
                init_data = resp.content
                log.debug("DASH [%s] init segment: %d bytes", download_id, len(init_data))
            except Exception as exc:
                log.warning(
                    "DASH [%s] failed to download init segment: %s",
                    download_id, exc,
                )

        # -- Download media segments in parallel --------------------------
        completed_count: int = 0
        downloaded_bytes: int = 0
        start_time: float = time.monotonic()

        temp_files: dict[int, Path] = {}
        failed_indices: set[int] = set()

        with ThreadPoolExecutor(max_workers=self._config.thread_count) as pool:
            future_to_idx: dict[Future[tuple[int, bytes]], int] = {}

            for idx, segment in enumerate(segments):
                future = pool.submit(
                    self._download_single_segment_with_retry,
                    segment,
                    download_id,
                )
                future_to_idx[future] = idx

            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    _, data = future.result()
                    seg_path = temp_dir / f"seg_{idx:08d}.tmp"
                    seg_path.write_bytes(data)
                    temp_files[idx] = seg_path
                    downloaded_bytes += len(data)
                except Exception as exc:
                    failed_indices.add(idx)
                    log.warning(
                        "DASH [%s] segment %d permanently failed: %s",
                        download_id, idx, exc,
                    )
                    callbacks.on_warning(WarningEvent(
                        message=f"Segment {idx + 1}/{total_segments} failed after "
                                f"all retries: {exc}",
                        context=filename,
                    ))

                completed_count += 1
                elapsed = time.monotonic() - start_time
                speed = downloaded_bytes / elapsed if elapsed > 0 else 0.0
                callbacks.on_progress(DownloadProgress(
                    download_id=download_id,
                    filename=filename,
                    downloaded=completed_count,
                    total=total_segments,
                    speed=speed,
                ))

        # -- Concatenate --------------------------------------------------
        self._concatenate_segments(
            output_path=output_path,
            init_data=init_data,
            temp_files=temp_files,
            total_segments=total_segments,
            failed_indices=failed_indices,
        )

        # -- Cleanup ------------------------------------------------------
        if self._config.cleanup_tmp:
            self._remove_temp_dir(temp_dir)

        log.info(
            "DASH [%s] %s complete: %d/%d segments, %d bytes",
            download_id, filename, total_segments - len(failed_indices),
            total_segments, downloaded_bytes,
        )
        return output_path

    def _download_single_segment_with_retry(
        self,
        segment: DASHSegment,
        download_id: str,
    ) -> tuple[int, bytes]:
        """Download a DASH segment with exponential-backoff retries.

        Retries up to ``config.retry_count`` times.  If all attempts
        fail, the exception propagates so the caller can record the
        segment as failed.

        Returns
        -------
        tuple[int, bytes]
            ``(segment.number, raw_bytes)``.
        """
        last_exc: Exception | None = None

        for attempt in range(self._config.retry_count + 1):
            try:
                data = self._download_single_segment(segment)
                return (segment.number, data)
            except Exception as exc:
                last_exc = exc
                if attempt < self._config.retry_count:
                    delay = min(0.5 * (2 ** attempt), 30.0)
                    log.debug(
                        "DASH [%s] segment %d retry %d/%d (%.1fs): %s",
                        download_id, segment.number,
                        attempt + 1, self._config.retry_count, delay, exc,
                    )
                    time.sleep(delay)

        assert last_exc is not None
        raise last_exc

    def _download_single_segment(self, segment: DASHSegment) -> bytes:
        """Download a single DASH segment.

        Unlike HLS, DASH segments are not individually encrypted at
        the transport level -- DRM decryption is handled externally
        by :class:`DRMManager`.

        Returns
        -------
        bytes
            Raw segment content.
        """
        resp = self._http.get(segment.url)
        resp.raise_for_status()
        return resp.content

    # ------------------------------------------------------------------
    # File concatenation
    # ------------------------------------------------------------------

    @staticmethod
    def _concatenate_segments(
        output_path: Path,
        init_data: bytes | None,
        temp_files: dict[int, Path],
        total_segments: int,
        failed_indices: set[int],
    ) -> None:
        """Concatenate init data + temp segment files into the final output.

        Segments are written in index order.  Failed segments are
        skipped so partial downloads still produce a playable file.
        """
        with output_path.open("wb") as out:
            if init_data:
                out.write(init_data)

            for idx in range(total_segments):
                if idx in failed_indices:
                    continue
                seg_path = temp_files.get(idx)
                if seg_path is None or not seg_path.exists():
                    continue
                with seg_path.open("rb") as seg_fp:
                    while True:
                        chunk = seg_fp.read(_CONCAT_BUFFER)
                        if not chunk:
                            break
                        out.write(chunk)

    @staticmethod
    def _remove_temp_dir(temp_dir: Path) -> None:
        """Remove a temporary segment directory and all its contents."""
        try:
            for child in temp_dir.iterdir():
                child.unlink(missing_ok=True)
            temp_dir.rmdir()
        except OSError as exc:
            log.debug("Could not remove temp dir %s: %s", temp_dir, exc)

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def _download_single_file(self, url: str, dest: Path) -> None:
        """Download a single file directly (no segmentation)."""
        try:
            resp = self._http.get(url)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
        except Exception as exc:
            log.warning("Failed to download %s: %s", url, exc)

    @staticmethod
    def _guess_extension(codec: str) -> str:
        """Guess a file extension from a codec name.

        DASH segments are typically ``.m4s`` fragments, so the
        concatenated result is an ``.mp4`` (or ``.m4a`` for
        audio-only).  We use ``.mp4`` for video codecs and ``.m4a``
        for audio codecs as safe defaults.
        """
        audio_codecs = {"aac", "opus", "eac3", "ac3", "dts", "flac", "vorbis"}
        if codec.lower() in audio_codecs:
            return "m4a"
        return "mp4"
