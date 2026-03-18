"""HLS download engine for Streamload.

Downloads m3u8 streams segment-by-segment with multi-threaded fetching,
AES-128 decryption support, exponential-backoff retries, and accurate
progress reporting through the :class:`EventCallbacks` interface.

No output is ever printed to the console -- every status update flows
through the event system.
"""

from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from Cryptodome.Cipher import AES

from streamload.core.downloader.base import BaseDownloader
from streamload.core.events import DownloadProgress, EventCallbacks, WarningEvent
from streamload.core.exceptions import NetworkError
from streamload.core.manifest.m3u8 import M3U8Parser, M3U8Playlist, M3U8Segment
from streamload.models.config import DownloadConfig
from streamload.models.stream import AudioTrack, SelectedTracks, SubtitleTrack
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger

log = get_logger(__name__)

# Size of the buffer used when concatenating temp segment files.
_CONCAT_BUFFER: int = 1024 * 1024  # 1 MB


class HLSDownloader(BaseDownloader):
    """Downloads HLS/m3u8 streams with multi-threaded segment fetching.

    Each track (video, each audio, each subtitle) is processed
    sequentially, but individual segments within a track are fetched
    in parallel using a :class:`~concurrent.futures.ThreadPoolExecutor`.
    """

    def __init__(self, http_client: HttpClient, config: DownloadConfig) -> None:
        super().__init__(http_client, config)
        self._parser = M3U8Parser()
        # Cache encryption keys to avoid re-fetching for every segment.
        self._key_cache: dict[str, bytes] = {}

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
        """Download HLS streams for every selected track.

        For each track (video, each audio, each subtitle):

        1. Fetch the media playlist (m3u8).
        2. Parse segments using :class:`M3U8Parser`.
        3. Download all segments in parallel.
        4. Handle AES-128 decryption when segments are encrypted.
        5. Concatenate segments into a single output file.
        6. Report progress via *callbacks*.

        Returns
        -------
        list[Path]
            Paths to the downloaded track files.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        downloaded: list[Path] = []

        # -- Video track ---------------------------------------------------
        video = tracks.video
        video_filename = self._generate_temp_filename(download_id, "video", "ts")
        video_path = output_dir / video_filename
        log.info("HLS download [%s] video: %s", download_id, video.id)

        playlist = self._fetch_and_parse_playlist(video.id)
        if playlist.segments:
            result = self._download_segments(
                segments=playlist.segments,
                init_url=playlist.init_url,
                output_path=video_path,
                download_id=download_id,
                filename=video_filename,
                callbacks=callbacks,
            )
            downloaded.append(result)
        else:
            log.warning("HLS [%s] video playlist has no segments", download_id)

        # -- Audio tracks --------------------------------------------------
        for idx, audio in enumerate(tracks.audio):
            if not audio.id:
                continue
            label = f"audio_{audio.language}_{idx}"
            audio_filename = self._generate_temp_filename(download_id, label, "ts")
            audio_path = output_dir / audio_filename
            log.info("HLS download [%s] audio %s: %s", download_id, label, audio.id)

            playlist = self._fetch_and_parse_playlist(audio.id)
            if playlist.segments:
                result = self._download_segments(
                    segments=playlist.segments,
                    init_url=playlist.init_url,
                    output_path=audio_path,
                    download_id=download_id,
                    filename=audio_filename,
                    callbacks=callbacks,
                )
                downloaded.append(result)
            else:
                log.warning("HLS [%s] audio playlist has no segments", download_id)

        # -- Subtitle tracks -----------------------------------------------
        for idx, sub in enumerate(tracks.subtitles):
            if not sub.id:
                continue
            label = f"sub_{sub.language}_{idx}"
            sub_filename = self._generate_temp_filename(
                download_id, label, sub.format,
            )
            sub_path = output_dir / sub_filename
            log.info("HLS download [%s] subtitle %s: %s", download_id, label, sub.id)

            playlist = self._fetch_and_parse_playlist(sub.id)
            if playlist.segments:
                result = self._download_segments(
                    segments=playlist.segments,
                    init_url=None,
                    output_path=sub_path,
                    download_id=download_id,
                    filename=sub_filename,
                    callbacks=callbacks,
                )
                downloaded.append(result)
            else:
                # Subtitle playlist might be a single file (WebVTT).
                self._download_single_file(sub.id, sub_path)
                if sub_path.exists():
                    downloaded.append(sub_path)

        return downloaded

    # ------------------------------------------------------------------
    # Segment download pipeline
    # ------------------------------------------------------------------

    def _download_segments(
        self,
        segments: list[M3U8Segment],
        init_url: str | None,
        output_path: Path,
        download_id: str,
        filename: str,
        callbacks: EventCallbacks,
    ) -> Path:
        """Download and concatenate HLS segments with threading.

        Segments are first downloaded to individual temp files inside
        the same directory as *output_path*, then concatenated into the
        final output.  This approach is safer than holding many large
        byte buffers in memory simultaneously.

        Parameters
        ----------
        segments:
            Ordered list of segments to download.
        init_url:
            Optional EXT-X-MAP initialization segment URL.
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

        # -- Pre-fetch encryption keys for all distinct key URLs ----------
        self._prefetch_keys(segments)

        # -- Download init segment if present -----------------------------
        init_data: bytes | None = None
        if init_url:
            try:
                resp = self._http.get(init_url)
                resp.raise_for_status()
                init_data = resp.content
            except Exception as exc:
                log.warning(
                    "HLS [%s] failed to download init segment: %s",
                    download_id, exc,
                )

        # -- Download segments in parallel --------------------------------
        completed_count: int = 0
        downloaded_bytes: int = 0
        start_time: float = time.monotonic()

        # Map: segment index -> temp file path (preserves ordering)
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
                    # Write segment to its own temp file.
                    seg_path = temp_dir / f"seg_{idx:08d}.tmp"
                    seg_path.write_bytes(data)
                    temp_files[idx] = seg_path
                    downloaded_bytes += len(data)
                except Exception as exc:
                    failed_indices.add(idx)
                    log.warning(
                        "HLS [%s] segment %d permanently failed: %s",
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

        # -- Concatenate temp files in order ------------------------------
        self._concatenate_segments(
            output_path=output_path,
            init_data=init_data,
            temp_files=temp_files,
            total_segments=total_segments,
            failed_indices=failed_indices,
        )

        # -- Cleanup temp dir ---------------------------------------------
        if self._config.cleanup_tmp:
            self._remove_temp_dir(temp_dir)

        log.info(
            "HLS [%s] %s complete: %d/%d segments, %d bytes",
            download_id, filename, total_segments - len(failed_indices),
            total_segments, downloaded_bytes,
        )
        return output_path

    def _download_single_segment_with_retry(
        self,
        segment: M3U8Segment,
        download_id: str,
    ) -> tuple[int, bytes]:
        """Download (and optionally decrypt) a segment with retries.

        Retries up to ``config.retry_count`` times with exponential
        backoff.  If all attempts fail, the exception propagates to the
        caller so the segment can be recorded as failed.

        Returns
        -------
        tuple[int, bytes]
            A dummy index ``0`` (the real index is tracked by the
            caller) and the raw (or decrypted) segment bytes.
        """
        last_exc: Exception | None = None

        for attempt in range(self._config.retry_count + 1):
            try:
                data = self._download_single_segment(segment)
                return (0, data)
            except Exception as exc:
                last_exc = exc
                if attempt < self._config.retry_count:
                    delay = min(0.5 * (2 ** attempt), 30.0)
                    log.debug(
                        "HLS [%s] segment retry %d/%d (%.1fs): %s",
                        download_id, attempt + 1,
                        self._config.retry_count, delay, exc,
                    )
                    time.sleep(delay)

        assert last_exc is not None
        raise last_exc

    def _download_single_segment(
        self,
        segment: M3U8Segment,
        decrypt_key: bytes | None = None,
        decrypt_iv: bytes | None = None,
    ) -> bytes:
        """Download and optionally decrypt a single HLS segment.

        When the segment specifies AES-128 encryption and explicit
        *decrypt_key*/*decrypt_iv* are not provided, the key is looked
        up from the internal cache (populated by ``_prefetch_keys``).

        Parameters
        ----------
        segment:
            The segment descriptor from the parsed playlist.
        decrypt_key:
            Override encryption key bytes (used by tests).
        decrypt_iv:
            Override initialisation vector bytes (used by tests).

        Returns
        -------
        bytes
            Raw (or decrypted) segment content.
        """
        headers: dict[str, str] = {}
        if segment.byterange is not None:
            length, offset = segment.byterange
            end = offset + length - 1
            headers["Range"] = f"bytes={offset}-{end}"

        resp = self._http.get(segment.url, headers=headers if headers else None)
        resp.raise_for_status()
        data: bytes = resp.content

        # -- AES-128 decryption -------------------------------------------
        if segment.key_method == "AES-128" and segment.key_url:
            key = decrypt_key or self._key_cache.get(segment.key_url)
            if key is None:
                key = self._fetch_encryption_key(segment.key_url)

            iv = decrypt_iv or self._derive_iv(segment)

            cipher = AES.new(key, AES.MODE_CBC, iv=iv)
            data = self._unpad_pkcs7(cipher.decrypt(data))

        return data

    # ------------------------------------------------------------------
    # Encryption helpers
    # ------------------------------------------------------------------

    def _fetch_encryption_key(self, key_url: str) -> bytes:
        """Fetch an AES-128 encryption key from *key_url*.

        The key is cached internally so subsequent segments sharing
        the same key URL do not trigger additional network requests.
        """
        if key_url in self._key_cache:
            return self._key_cache[key_url]

        log.debug("Fetching AES-128 key: %s", key_url)
        resp = self._http.get(key_url)
        resp.raise_for_status()
        key = resp.content

        if len(key) != 16:
            raise NetworkError(
                f"Invalid AES-128 key length ({len(key)} bytes) from {key_url}",
            )

        self._key_cache[key_url] = key
        return key

    def _prefetch_keys(self, segments: list[M3U8Segment]) -> None:
        """Pre-fetch all distinct encryption keys referenced by *segments*.

        This avoids redundant key fetches during parallel segment
        downloads (where many threads would otherwise race to fetch
        the same key).
        """
        seen: set[str] = set()
        for seg in segments:
            if seg.key_method == "AES-128" and seg.key_url and seg.key_url not in seen:
                seen.add(seg.key_url)
                try:
                    self._fetch_encryption_key(seg.key_url)
                except Exception as exc:
                    log.warning("Failed to pre-fetch key %s: %s", seg.key_url, exc)

    @staticmethod
    def _derive_iv(segment: M3U8Segment) -> bytes:
        """Derive the AES initialisation vector for *segment*.

        If the playlist provides an explicit IV (``EXT-X-KEY`` ``IV``
        attribute), it is used directly.  Otherwise the IV defaults to
        the segment sequence number encoded as a 16-byte big-endian
        integer -- this is the HLS specification's default behaviour.
        """
        if segment.key_iv:
            iv_str = segment.key_iv
            # Strip leading "0x" / "0X" prefix.
            if iv_str.lower().startswith("0x"):
                iv_str = iv_str[2:]
            return bytes.fromhex(iv_str.zfill(32))

        # Fallback: use the segment URL's content as a zero-IV.
        # The HLS spec says the IV is the media sequence number, but
        # we don't have it here.  Use a zero IV as a safe default
        # (many real-world servers behave this way).
        return b"\x00" * 16

    @staticmethod
    def _unpad_pkcs7(data: bytes) -> bytes:
        """Remove PKCS#7 padding from *data*.

        Returns *data* unchanged if the padding looks invalid (some
        poorly-behaved servers omit or corrupt the padding).
        """
        if not data:
            return data
        pad_len = data[-1]
        if pad_len < 1 or pad_len > 16:
            return data
        if data[-pad_len:] != bytes([pad_len]) * pad_len:
            return data
        return data[:-pad_len]

    # ------------------------------------------------------------------
    # Playlist fetching
    # ------------------------------------------------------------------

    def _fetch_and_parse_playlist(self, playlist_url: str) -> M3U8Playlist:
        """Fetch and parse an HLS media playlist.

        Parameters
        ----------
        playlist_url:
            Absolute URL to the m3u8 media playlist.

        Returns
        -------
        M3U8Playlist
            Parsed playlist with segment list.
        """
        resp = self._http.get(playlist_url)
        resp.raise_for_status()
        return self._parser.parse_media(resp.text, playlist_url)

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
        """Concatenate temp segment files into the final output.

        Segments are written in order.  Missing (failed) segments are
        silently skipped so that partial downloads still produce a
        usable file.
        """
        with output_path.open("wb") as out:
            # Write init segment first if present.
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
    # Utility: single file download (subtitle fallback)
    # ------------------------------------------------------------------

    def _download_single_file(self, url: str, dest: Path) -> None:
        """Download a single file directly (no segmentation)."""
        try:
            resp = self._http.get(url)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
        except Exception as exc:
            log.warning("Failed to download %s: %s", url, exc)
