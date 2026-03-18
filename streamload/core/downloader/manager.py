"""Download orchestrator for Streamload.

Manages the full download pipeline: format detection, concurrent
downloads with queuing, DRM key acquisition, and post-processing
(merge, subtitle conversion, NFO generation).

The orchestrator never prints to the console -- all user-facing
communication flows through :class:`EventCallbacks`.

Usage::

    manager = DownloadManager(config, http_client, drm_manager, callbacks)
    job = DownloadJob(item=episode, bundle=bundle, tracks=tracks)
    path = manager.download_single(job)
"""

from __future__ import annotations

import re
import shutil
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from threading import Semaphore
from typing import TYPE_CHECKING

from streamload.core.downloader.base import BaseDownloader
from streamload.core.downloader.dash import DASHDownloader
from streamload.core.downloader.hls import HLSDownloader
from streamload.core.downloader.mp4 import MP4Downloader
from streamload.core.events import (
    DownloadComplete,
    DownloadProgress,
    ErrorEvent,
    MergeProgress,
    WarningEvent,
)
from streamload.core.exceptions import DRMError, MergeError, StreamloadError
from streamload.core.post.merge import FFmpegMerger
from streamload.models.config import AppConfig, DownloadConfig
from streamload.models.media import Episode, MediaEntry, MediaType
from streamload.models.stream import SelectedTracks, StreamBundle
from streamload.utils.logger import get_logger

if TYPE_CHECKING:
    from streamload.core.drm.manager import DRMManager
    from streamload.core.events import EventCallbacks
    from streamload.utils.http import HttpClient

log = get_logger(__name__)

# Characters that are unsafe in filenames across platforms.
_UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class DownloadJob:
    """A single download job tracked through the pipeline.

    Attributes
    ----------
    id:
        Short unique identifier (8 hex chars).
    item:
        The media item being downloaded (episode or film).
    bundle:
        All available streams for this item.
    tracks:
        The user's final track selection.
    output_path:
        Final output file path (populated during download).
    status:
        Current pipeline stage.
    error:
        Human-readable error message when ``status == "failed"``.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    item: Episode | MediaEntry | None = None
    bundle: StreamBundle | None = None
    tracks: SelectedTracks | None = None
    output_path: Path | None = None
    status: str = "pending"  # pending | downloading | merging | complete | failed
    error: str | None = None


# ---------------------------------------------------------------------------
# Download manager
# ---------------------------------------------------------------------------


class DownloadManager:
    """Orchestrates the download pipeline: detect format, download,
    DRM decrypt, merge, and clean up.

    Parameters
    ----------
    config:
        Root application configuration.
    http_client:
        Shared HTTP client instance.
    drm_manager:
        DRM key acquisition orchestrator.
    callbacks:
        Event interface for progress reporting.
    """

    def __init__(
        self,
        config: AppConfig,
        http_client: HttpClient,
        drm_manager: DRMManager,
        callbacks: EventCallbacks,
    ) -> None:
        self._config = config
        self._http = http_client
        self._drm = drm_manager
        self._callbacks = callbacks
        self._merger = FFmpegMerger(config.process)
        self._semaphore = Semaphore(config.download.max_concurrent)

        # Create one downloader instance per format.
        self._hls = HLSDownloader(http_client, config.download)
        self._dash = DASHDownloader(http_client, config.download)
        self._mp4 = MP4Downloader(http_client, config.download)

    # ------------------------------------------------------------------
    # Single-item download
    # ------------------------------------------------------------------

    def download_single(self, job: DownloadJob) -> Path:
        """Download a single item (film or episode) end-to-end.

        Pipeline:

        1. Validate job inputs.
        2. Detect stream type from bundle (HLS / DASH / MP4).
        3. If DRM-protected: acquire decryption keys via DRMManager.
        4. Download all selected tracks to a temp directory.
        5. Merge with FFmpeg (video + audio + subtitles -> final file).
        6. Clean up temp files.

        Parameters
        ----------
        job:
            A fully populated :class:`DownloadJob`.

        Returns
        -------
        Path
            Absolute path to the final output file.

        Raises
        ------
        StreamloadError
            On any unrecoverable failure (network, DRM, merge, etc.).
        """
        start_time = time.monotonic()
        job.status = "downloading"

        try:
            self._validate_job(job)

            assert job.item is not None
            assert job.bundle is not None
            assert job.tracks is not None

            # -- Build output path -------------------------------------------
            job.output_path = self._build_output_path(job.item)
            job.output_path.parent.mkdir(parents=True, exist_ok=True)

            # -- Temp working directory for raw downloads --------------------
            temp_dir = job.output_path.parent / f".tmp_{job.id}"
            temp_dir.mkdir(parents=True, exist_ok=True)

            # -- DRM key acquisition ----------------------------------------
            drm_keys: list[tuple[str, str]] | None = None
            if job.bundle.drm_type and job.bundle.pssh and job.bundle.license_url:
                log.info(
                    "Job [%s] acquiring %s keys",
                    job.id, job.bundle.drm_type,
                )
                try:
                    service_name = (
                        job.item.service
                        if isinstance(job.item, MediaEntry)
                        else "unknown"
                    )
                    drm_keys = self._drm.get_keys(
                        pssh=job.bundle.pssh,
                        license_url=job.bundle.license_url,
                        drm_type=job.bundle.drm_type,
                        service=service_name,
                    )
                    log.info(
                        "Job [%s] obtained %d DRM key(s)",
                        job.id, len(drm_keys),
                    )
                except DRMError as exc:
                    raise StreamloadError(
                        f"DRM key acquisition failed: {exc.message}"
                    ) from exc

            # -- Detect downloader and execute download ----------------------
            downloader = self._detect_downloader(job.bundle)

            # Pre-load DASH manifest if using DASHDownloader.
            if (
                isinstance(downloader, DASHDownloader)
                and job.bundle.manifest_url
            ):
                resp = self._http.get(job.bundle.manifest_url)
                resp.raise_for_status()
                downloader.set_mpd(job.bundle.manifest_url, resp.text)

            log.info(
                "Job [%s] downloading with %s",
                job.id, type(downloader).__name__,
            )
            downloaded_files = downloader.download(
                download_id=job.id,
                tracks=job.tracks,
                output_dir=temp_dir,
                callbacks=self._callbacks,
            )

            if not downloaded_files:
                raise StreamloadError(
                    f"No files were downloaded for job {job.id}"
                )

            # -- Classify downloaded files ----------------------------------
            video_path, audio_paths, subtitle_paths = self._classify_files(
                downloaded_files, job.id,
            )

            if video_path is None:
                raise StreamloadError(
                    f"No video file found among downloaded files for job {job.id}"
                )

            # -- Merge ------------------------------------------------------
            job.status = "merging"
            self._callbacks.on_merge_progress(MergeProgress(
                download_id=job.id,
                filename=job.output_path.name,
                stage="merging",
            ))

            extension = self._config.output.extension
            final_path = self._merger.merge(
                video_path=video_path,
                audio_paths=audio_paths,
                subtitle_paths=subtitle_paths,
                output_path=job.output_path,
                extension=extension,
                audio_tracks=job.tracks.audio if job.tracks else [],
                subtitle_tracks=job.tracks.subtitles if job.tracks else [],
            )

            # -- Cleanup temp directory -------------------------------------
            if self._config.download.cleanup_tmp:
                self._cleanup_temp_dir(temp_dir)

            # -- Mark complete ----------------------------------------------
            job.status = "complete"
            job.output_path = final_path

            elapsed = time.monotonic() - start_time
            file_size = final_path.stat().st_size if final_path.exists() else 0
            self._callbacks.on_complete(DownloadComplete(
                download_id=job.id,
                filepath=final_path,
                duration=elapsed,
                size=file_size,
            ))

            log.info(
                "Job [%s] complete: %s (%d bytes, %.1fs)",
                job.id, final_path, file_size, elapsed,
            )
            return final_path

        except Exception as exc:
            job.status = "failed"
            error_msg = str(exc)
            job.error = error_msg

            streamload_exc = (
                exc if isinstance(exc, StreamloadError)
                else StreamloadError(error_msg)
            )
            self._callbacks.on_error(ErrorEvent(
                download_id=job.id,
                error=streamload_exc,
                message=error_msg,
                recoverable=False,
            ))
            log.error("Job [%s] failed: %s", job.id, error_msg)
            raise

    # ------------------------------------------------------------------
    # Batch download
    # ------------------------------------------------------------------

    def download_batch(self, jobs: list[DownloadJob]) -> list[DownloadJob]:
        """Download multiple items with concurrency control.

        Uses a :class:`~threading.Semaphore` to limit concurrent downloads
        to ``config.download.max_concurrent``.  Each job runs in its own
        thread via :class:`~concurrent.futures.ThreadPoolExecutor`.

        Failed jobs are recorded in-place (``job.status = "failed"``,
        ``job.error`` populated) but do not abort the batch.

        Parameters
        ----------
        jobs:
            List of download jobs to execute.

        Returns
        -------
        list[DownloadJob]
            The same list with each job's status updated.
        """
        if not jobs:
            return jobs

        max_workers = self._config.download.max_concurrent

        def _run_with_semaphore(job: DownloadJob) -> DownloadJob:
            self._semaphore.acquire()
            try:
                self.download_single(job)
            except Exception:
                # Error is already recorded on the job by download_single.
                pass
            finally:
                self._semaphore.release()
            return job

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures: dict[Future[DownloadJob], DownloadJob] = {}
            for job in jobs:
                future = pool.submit(_run_with_semaphore, job)
                futures[future] = job

            for future in as_completed(futures):
                job = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    # Belt-and-suspenders: ensure the job is marked failed
                    # even if something unexpected happens in the thread.
                    if job.status != "failed":
                        job.status = "failed"
                        job.error = str(exc)
                        log.error(
                            "Job [%s] unexpected batch failure: %s",
                            job.id, exc,
                        )

        completed = sum(1 for j in jobs if j.status == "complete")
        failed = sum(1 for j in jobs if j.status == "failed")
        log.info(
            "Batch download finished: %d/%d complete, %d failed",
            completed, len(jobs), failed,
        )
        return jobs

    # ------------------------------------------------------------------
    # Format detection
    # ------------------------------------------------------------------

    def _detect_downloader(self, bundle: StreamBundle) -> BaseDownloader:
        """Detect which downloader to use based on the stream bundle.

        Decision logic:

        - If ``manifest_url`` ends with ``.m3u8`` or contains ``m3u8`` in
          the path component -> HLS.
        - If ``manifest_url`` ends with ``.mpd`` or contains ``mpd`` in
          the path component -> DASH.
        - Otherwise -> MP4 (direct download).

        Parameters
        ----------
        bundle:
            Stream bundle with manifest URL information.

        Returns
        -------
        BaseDownloader
            The appropriate downloader instance.
        """
        url = bundle.manifest_url or ""
        # Strip query string and fragment for cleaner matching.
        url_path = url.split("?")[0].split("#")[0].lower()

        if url_path.endswith(".m3u8") or "m3u8" in url_path:
            log.debug("Detected HLS stream from manifest URL")
            return self._hls

        if url_path.endswith(".mpd") or "mpd" in url_path:
            log.debug("Detected DASH stream from manifest URL")
            return self._dash

        # Fallback: check video track IDs for format hints.
        if bundle.video:
            first_video_id = bundle.video[0].id.lower()
            if "m3u8" in first_video_id:
                log.debug("Detected HLS stream from video track ID")
                return self._hls
            if "mpd" in first_video_id:
                log.debug("Detected DASH stream from video track ID")
                return self._dash

        log.debug("Defaulting to MP4 downloader")
        return self._mp4

    # ------------------------------------------------------------------
    # Output path building
    # ------------------------------------------------------------------

    def _build_output_path(self, item: Episode | MediaEntry) -> Path:
        """Build the final output file path using config naming templates.

        Uses ``config.output.movie_format`` for films and
        ``config.output.episode_format`` for episodes.  Template
        placeholders (``{title}``, ``{year}``, ``{season}``, etc.) are
        filled from the item's metadata.

        Parameters
        ----------
        item:
            The media item (episode or film entry).

        Returns
        -------
        Path
            Absolute output file path.
        """
        output_cfg = self._config.output
        root = Path(output_cfg.root_path)
        extension = output_cfg.extension

        if isinstance(item, Episode):
            return self._build_episode_path(item, root, extension)
        else:
            return self._build_movie_path(item, root, extension)

    def _build_movie_path(
        self,
        entry: MediaEntry,
        root: Path,
        extension: str,
    ) -> Path:
        """Build the output path for a film.

        Uses ``config.output.movie_format`` with ``{title}`` and
        ``{year}`` placeholders.
        """
        output_cfg = self._config.output
        folder = self._get_type_folder(entry.type)

        template = output_cfg.movie_format
        filename = template.format(
            title=self._sanitize_filename(entry.title),
            year=entry.year or "Unknown",
        )
        filename = self._sanitize_filename(filename)

        return root / folder / f"{filename}.{extension}"

    def _build_episode_path(
        self,
        episode: Episode,
        root: Path,
        extension: str,
    ) -> Path:
        """Build the output path for an episode.

        Uses ``config.output.episode_format`` with ``{series}``,
        ``{season}``, ``{episode}``, and ``{title}`` placeholders.
        """
        output_cfg = self._config.output
        # Episodes belong under the serie or anime folder.
        folder = output_cfg.serie_folder

        template = output_cfg.episode_format
        formatted = template.format(
            series=self._sanitize_filename(episode.title),
            title=self._sanitize_filename(episode.title),
            season=episode.season_number,
            episode=episode.number,
        )
        formatted = self._sanitize_filename(formatted)

        return root / folder / f"{formatted}.{extension}"

    def _get_type_folder(self, media_type: MediaType) -> str:
        """Return the subfolder name for a given media type."""
        output_cfg = self._config.output
        mapping = {
            MediaType.FILM: output_cfg.movie_folder,
            MediaType.SERIE: output_cfg.serie_folder,
            MediaType.ANIME: output_cfg.anime_folder,
        }
        return mapping.get(media_type, output_cfg.movie_folder)

    # ------------------------------------------------------------------
    # File classification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_files(
        files: list[Path],
        download_id: str,
    ) -> tuple[Path | None, list[Path], list[Path]]:
        """Classify downloaded files into video, audio, and subtitle groups.

        Classification is based on filename conventions used by the
        downloaders (``dl_<id>_video.*``, ``dl_<id>_audio_*.*``,
        ``dl_<id>_sub_*.*``).

        Parameters
        ----------
        files:
            List of downloaded file paths.
        download_id:
            The job ID used in temp filenames.

        Returns
        -------
        tuple
            ``(video_path, audio_paths, subtitle_paths)`` where
            ``video_path`` may be ``None`` if no video file was found.
        """
        video_path: Path | None = None
        audio_paths: list[Path] = []
        subtitle_paths: list[Path] = []

        subtitle_extensions = {".srt", ".vtt", ".ass", ".ttml", ".dfxp"}

        for f in files:
            name = f.name.lower()
            if f"dl_{download_id}_video" in name:
                video_path = f
            elif f"dl_{download_id}_audio" in name:
                audio_paths.append(f)
            elif f"dl_{download_id}_sub" in name:
                subtitle_paths.append(f)
            elif f.suffix.lower() in subtitle_extensions:
                subtitle_paths.append(f)
            elif video_path is None:
                # First unclassified file is assumed to be video.
                video_path = f
            else:
                audio_paths.append(f)

        return video_path, audio_paths, subtitle_paths

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    @staticmethod
    def _cleanup_temp_dir(temp_dir: Path) -> None:
        """Remove a temporary working directory and all its contents."""
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
            log.debug("Cleaned up temp directory: %s", temp_dir)
        except OSError as exc:
            log.debug("Could not fully remove temp dir %s: %s", temp_dir, exc)

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_job(job: DownloadJob) -> None:
        """Validate that a job has all required fields populated.

        Raises
        ------
        StreamloadError
            If any required field is missing.
        """
        if job.item is None:
            raise StreamloadError(f"Job {job.id}: missing 'item'")
        if job.bundle is None:
            raise StreamloadError(f"Job {job.id}: missing 'bundle'")
        if job.tracks is None:
            raise StreamloadError(f"Job {job.id}: missing 'tracks'")
        if job.tracks.video is None:
            raise StreamloadError(f"Job {job.id}: missing video track in selection")

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Remove or replace characters that are unsafe in filenames.

        Replaces unsafe characters with underscores and collapses
        multiple consecutive underscores/spaces.
        """
        sanitized = _UNSAFE_FILENAME_RE.sub("_", name)
        # Collapse multiple underscores/spaces.
        sanitized = re.sub(r"[_ ]{2,}", " ", sanitized)
        # Strip leading/trailing whitespace and dots (Windows issue).
        sanitized = sanitized.strip(" .")
        return sanitized or "Untitled"
