"""Direct MP4/file download engine for Streamload.

Downloads content from services that provide direct file URLs (as
opposed to segmented HLS/DASH manifests).  Uses streaming HTTP with
progress tracking and ``Content-Length`` for accurate totals.

All status updates flow through the :class:`EventCallbacks` interface.
Nothing is printed to the console.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from streamload.core.downloader.base import BaseDownloader
from streamload.core.events import DownloadProgress, EventCallbacks, WarningEvent
from streamload.core.exceptions import NetworkError
from streamload.models.config import DownloadConfig
from streamload.models.stream import SelectedTracks
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

# Chunk size for streaming downloads.
_CHUNK_SIZE: int = 64 * 1024  # 64 KB


class MP4Downloader(BaseDownloader):
    """Downloads direct MP4 / video file URLs with progress tracking.

    Suitable for services that expose a plain ``https://…/video.mp4``
    link rather than an adaptive manifest.  Each track (video, audio,
    subtitle) is downloaded as a separate streamed file.
    """

    def __init__(self, http_client: HttpClient, config: DownloadConfig) -> None:
        super().__init__(http_client, config)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def download(
        self,
        download_id: str,
        tracks: SelectedTracks,
        output_dir: Path,
        callbacks: EventCallbacks,
        extra_headers: dict[str, str] | None = None,
    ) -> list[Path]:
        """Download direct video/audio/subtitle files.

        Uses streaming HTTP to write data incrementally and reports
        progress based on ``Content-Length`` (when the server provides
        it) or on downloaded byte count (when it does not).

        Returns
        -------
        list[Path]
            Paths to the downloaded files.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        downloaded: list[Path] = []

        # -- Video track ---------------------------------------------------
        video = tracks.video
        video_ext = self._guess_extension_from_url(video.id, default="mp4")
        video_filename = self._generate_temp_filename(
            download_id, "video", video_ext,
        )
        video_path = output_dir / video_filename
        log.info("MP4 download [%s] video: %s", download_id, video.id)

        result = self._download_file(
            url=video.id,
            output_path=video_path,
            download_id=download_id,
            filename=video_filename,
            callbacks=callbacks,
        )
        if result is not None:
            downloaded.append(result)

        # -- Audio tracks --------------------------------------------------
        for idx, audio in enumerate(tracks.audio):
            if not audio.id:
                continue
            label = f"audio_{audio.language}_{idx}"
            audio_ext = self._guess_extension_from_url(audio.id, default="m4a")
            audio_filename = self._generate_temp_filename(
                download_id, label, audio_ext,
            )
            audio_path = output_dir / audio_filename
            log.info("MP4 download [%s] audio %s: %s", download_id, label, audio.id)

            result = self._download_file(
                url=audio.id,
                output_path=audio_path,
                download_id=download_id,
                filename=audio_filename,
                callbacks=callbacks,
            )
            if result is not None:
                downloaded.append(result)

        # -- Subtitle tracks -----------------------------------------------
        for idx, sub in enumerate(tracks.subtitles):
            if not sub.id:
                continue
            label = f"sub_{sub.language}_{idx}"
            sub_ext = self._guess_extension_from_url(sub.id, default=sub.format)
            sub_filename = self._generate_temp_filename(
                download_id, label, sub_ext,
            )
            sub_path = output_dir / sub_filename
            log.info("MP4 download [%s] subtitle %s: %s", download_id, label, sub.id)

            result = self._download_file(
                url=sub.id,
                output_path=sub_path,
                download_id=download_id,
                filename=sub_filename,
                callbacks=callbacks,
            )
            if result is not None:
                downloaded.append(result)

        return downloaded

    # ------------------------------------------------------------------
    # Streaming file download
    # ------------------------------------------------------------------

    def _download_file(
        self,
        url: str,
        output_path: Path,
        download_id: str,
        filename: str,
        callbacks: EventCallbacks,
    ) -> Path | None:
        """Download a single file with streaming and progress reporting.

        Retries up to ``config.retry_count`` times with exponential
        backoff on transient failures.

        Parameters
        ----------
        url:
            Source URL.
        output_path:
            Destination file path.
        download_id:
            Unique download identifier for progress events.
        filename:
            Display name used in progress events.
        callbacks:
            Event interface for progress reporting.

        Returns
        -------
        Path | None
            The *output_path* on success, or ``None`` if the download
            failed permanently.
        """
        last_exc: Exception | None = None

        for attempt in range(self._config.retry_count + 1):
            try:
                return self._stream_download(
                    url=url,
                    output_path=output_path,
                    download_id=download_id,
                    filename=filename,
                    callbacks=callbacks,
                )
            except Exception as exc:
                last_exc = exc
                if attempt < self._config.retry_count and self._is_retriable(exc):
                    delay = min(0.5 * (2 ** attempt), 30.0)
                    log.debug(
                        "MP4 [%s] retry %d/%d for %s (%.1fs): %s",
                        download_id, attempt + 1,
                        self._config.retry_count, filename, delay, exc,
                    )
                    time.sleep(delay)
                    continue
                # Non-retriable or retries exhausted.
                break

        log.warning(
            "MP4 [%s] download failed for %s after %d attempts: %s",
            download_id, filename, self._config.retry_count + 1, last_exc,
        )
        callbacks.on_warning(WarningEvent(
            message=f"Download failed after all retries: {last_exc}",
            context=filename,
        ))
        return None

    def _stream_download(
        self,
        url: str,
        output_path: Path,
        download_id: str,
        filename: str,
        callbacks: EventCallbacks,
    ) -> Path:
        """Execute a single streaming download attempt.

        Opens an ``httpx`` stream, writes chunks to *output_path*, and
        emits progress events after each chunk.

        Raises on HTTP errors or transport failures so the caller can
        decide whether to retry.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # We access the underlying httpx client directly for streaming
        # since HttpClient.download_file() doesn't expose progress hooks.
        start_time: float = time.monotonic()
        downloaded_bytes: int = 0

        try:
            with self._http._httpx.stream(
                "GET", url, follow_redirects=True,
            ) as stream:
                if stream.status_code >= 400:
                    raise NetworkError(
                        f"HTTP {stream.status_code} for {url}",
                        status_code=stream.status_code,
                    )

                # Parse Content-Length for total size (0 if unknown).
                total_bytes = int(
                    stream.headers.get("content-length", "0"),
                )

                with output_path.open("wb") as fp:
                    for chunk in stream.iter_bytes(chunk_size=_CHUNK_SIZE):
                        fp.write(chunk)
                        downloaded_bytes += len(chunk)

                        elapsed = time.monotonic() - start_time
                        speed = (
                            downloaded_bytes / elapsed if elapsed > 0 else 0.0
                        )
                        callbacks.on_progress(DownloadProgress(
                            download_id=download_id,
                            filename=filename,
                            downloaded=downloaded_bytes,
                            total=total_bytes,
                            speed=speed,
                        ))

        except httpx.TransportError as exc:
            # Clean up partial file on transport error.
            if output_path.exists():
                output_path.unlink(missing_ok=True)
            raise NetworkError(
                f"Transport error downloading {url}: {exc}",
            ) from exc

        log.info(
            "MP4 [%s] %s complete: %d bytes",
            download_id, filename, downloaded_bytes,
        )
        return output_path

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _guess_extension_from_url(url: str, *, default: str = "mp4") -> str:
        """Extract a file extension from *url*, falling back to *default*.

        Strips query strings and fragments before inspecting the path.
        Only returns the extension if it looks like a recognised media
        type; otherwise returns *default*.
        """
        known_extensions = {
            "mp4", "mkv", "avi", "webm", "m4v", "mov", "flv",
            "m4a", "aac", "mp3", "ogg", "opus", "flac", "wav",
            "srt", "vtt", "ass", "ttml", "dfxp",
        }
        # Remove query and fragment.
        clean = url.split("?")[0].split("#")[0]
        if "." in clean:
            ext = clean.rsplit(".", 1)[-1].lower()
            if ext in known_extensions:
                return ext
        return default

    @staticmethod
    def _is_retriable(exc: Exception) -> bool:
        """Determine whether *exc* is a transient error worth retrying."""
        if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
            return True
        if isinstance(exc, NetworkError) and exc.status_code is not None:
            return exc.status_code == 429 or exc.status_code >= 500
        return False
