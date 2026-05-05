"""Typed configuration dataclasses for Streamload.

Every field carries a sensible default so the application can always
boot -- even from an empty or corrupt ``config.json``.  Validation is
lenient: invalid values are silently replaced with defaults.

Serialisation round-trips through plain ``dict`` (JSON-compatible).
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field, fields
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(value: int, lo: int, hi: int) -> int:
    """Clamp *value* to the inclusive range [lo, hi]."""
    return max(lo, min(hi, value))


def _safe_get(
    data: dict[str, Any],
    key: str,
    expected_type: type | tuple[type, ...],
    default: Any,
) -> Any:
    """Return ``data[key]`` if present and of *expected_type*, else *default*.

    Logs a warning on type mismatch so config problems are diagnosable.
    """
    if key not in data:
        return default
    value = data[key]
    # Allow None when the default is None (optional fields).
    if value is None and default is None:
        return None
    if not isinstance(value, expected_type):
        log.warning(
            "config: invalid type for %r (expected %s, got %s) -- using default %r",
            key,
            expected_type,
            type(value).__name__,
            default,
        )
        return default
    return value


# ---------------------------------------------------------------------------
# Section dataclasses
# ---------------------------------------------------------------------------

@dataclass
class OutputConfig:
    """Paths and naming templates for downloaded files."""

    root_path: str = "Video"
    movie_folder: str = "Film"
    serie_folder: str = "Serie"
    anime_folder: str = "Anime"
    movie_format: str = "{title} ({year})"
    episode_format: str = "{series}/S{season:02d}/{title} S{season:02d}E{episode:02d}"
    extension: str = "mkv"  # "mkv" | "mp4"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OutputConfig:
        g = _safe_get
        ext = g(data, "extension", str, cls.extension)
        if ext not in ("mkv", "mp4"):
            log.warning("config: invalid extension %r -- using default 'mkv'", ext)
            ext = "mkv"
        return cls(
            root_path=g(data, "root_path", str, cls.root_path),
            movie_folder=g(data, "movie_folder", str, cls.movie_folder),
            serie_folder=g(data, "serie_folder", str, cls.serie_folder),
            anime_folder=g(data, "anime_folder", str, cls.anime_folder),
            movie_format=g(data, "movie_format", str, cls.movie_format),
            episode_format=g(data, "episode_format", str, cls.episode_format),
            extension=ext,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DownloadConfig:
    """Download engine tunables."""

    thread_count: int = 8  # per-download segment parallelism (1-32)
    retry_count: int = 25  # segment-level retries
    max_concurrent: int = 3  # simultaneous downloads
    max_speed: str | None = None  # e.g. "30MB", "500KB", None = unlimited
    cleanup_tmp: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DownloadConfig:
        g = _safe_get
        thread_count = g(data, "thread_count", int, cls.thread_count)
        thread_count = _clamp(thread_count, 1, 32)

        retry_count = g(data, "retry_count", int, cls.retry_count)
        if retry_count < 0:
            retry_count = cls.retry_count

        max_concurrent = g(data, "max_concurrent", int, cls.max_concurrent)
        if max_concurrent < 1:
            max_concurrent = cls.max_concurrent

        return cls(
            thread_count=thread_count,
            retry_count=retry_count,
            max_concurrent=max_concurrent,
            max_speed=g(data, "max_speed", str, cls.max_speed),
            cleanup_tmp=g(data, "cleanup_tmp", bool, cls.cleanup_tmp),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProcessConfig:
    """Post-processing options (FFmpeg, subtitles, metadata)."""

    use_gpu: bool = False
    generate_nfo: bool = False
    merge_audio: bool = True
    merge_subtitle: bool = True
    subtitle_format: str = "auto"  # "auto" | "srt" | "vtt" | "ass"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProcessConfig:
        g = _safe_get
        sub_fmt = g(data, "subtitle_format", str, cls.subtitle_format)
        if sub_fmt not in ("auto", "srt", "vtt", "ass"):
            log.warning(
                "config: invalid subtitle_format %r -- using default 'auto'", sub_fmt
            )
            sub_fmt = "auto"
        return cls(
            use_gpu=g(data, "use_gpu", bool, cls.use_gpu),
            generate_nfo=g(data, "generate_nfo", bool, cls.generate_nfo),
            merge_audio=g(data, "merge_audio", bool, cls.merge_audio),
            merge_subtitle=g(data, "merge_subtitle", bool, cls.merge_subtitle),
            subtitle_format=sub_fmt,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NetworkConfig:
    """HTTP / connectivity tunables."""

    timeout: int = 30  # seconds
    max_retry: int = 8  # general HTTP retries
    verify_ssl: bool = True
    proxy: str | None = None  # "http://host:port"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NetworkConfig:
        g = _safe_get
        timeout = g(data, "timeout", int, cls.timeout)
        if timeout < 1:
            timeout = cls.timeout

        max_retry = g(data, "max_retry", int, cls.max_retry)
        if max_retry < 0:
            max_retry = cls.max_retry

        return cls(
            timeout=timeout,
            max_retry=max_retry,
            verify_ssl=g(data, "verify_ssl", bool, cls.verify_ssl),
            proxy=g(data, "proxy", str, cls.proxy),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DRMDeviceConfig:
    """Configuration for a single remote CDM device (Widevine or PlayReady)."""

    device_type: str | None = None  # "ANDROID", etc.
    system_id: int | None = None
    security_level: int | None = None
    host: str | None = None  # remote CDM URL
    secret: str | None = None
    device_name: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DRMDeviceConfig:
        g = _safe_get
        system_id = g(data, "system_id", int, cls.system_id)
        security_level = g(data, "security_level", int, cls.security_level)
        return cls(
            device_type=g(data, "device_type", str, cls.device_type),
            system_id=system_id,
            security_level=security_level,
            host=g(data, "host", str, cls.host),
            secret=g(data, "secret", str, cls.secret),
            device_name=g(data, "device_name", str, cls.device_name),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DRMConfig:
    """DRM subsystem configuration (Widevine + PlayReady)."""

    widevine: DRMDeviceConfig = field(default_factory=lambda: DRMDeviceConfig(
        device_type="ANDROID",
        system_id=22590,
        security_level=3,
        host="https://cdrm-project.com/remotecdm/widevine",
        secret="CDRM",
        device_name="public",
    ))
    playready: DRMDeviceConfig = field(default_factory=lambda: DRMDeviceConfig(
        host="https://cdrm-project.com/remotecdm/playready",
        secret="CDRM",
        device_name="public",
    ))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DRMConfig:
        default = cls()
        wv_data = data.get("widevine")
        pr_data = data.get("playready")
        return cls(
            widevine=(
                DRMDeviceConfig.from_dict(wv_data)
                if isinstance(wv_data, dict)
                else default.widevine
            ),
            playready=(
                DRMDeviceConfig.from_dict(pr_data)
                if isinstance(pr_data, dict)
                else default.playready
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "widevine": self.widevine.to_dict(),
            "playready": self.playready.to_dict(),
        }


# ---------------------------------------------------------------------------
# Top-level configuration
# ---------------------------------------------------------------------------

@dataclass
class AppConfig:
    """Root configuration object.

    Mirrors the ``config.json`` file structure.  Construct from a dict
    with ``AppConfig.from_dict(data)``; convert back with ``to_dict()``.
    Invalid values silently fall back to defaults -- the application
    must never crash from bad configuration.
    """

    language: str = "auto"  # "auto" | "it" | "en"
    preferred_audio: str = "auto"
    preferred_subtitle: str = "auto"
    auto_update: bool = True
    output: OutputConfig = field(default_factory=OutputConfig)
    download: DownloadConfig = field(default_factory=DownloadConfig)
    process: ProcessConfig = field(default_factory=ProcessConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    drm: DRMConfig = field(default_factory=DRMConfig)
    services: dict[str, dict[str, str]] = field(default_factory=dict)

    # -- Serialisation / deserialisation ------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Produce a JSON-serialisable dict."""
        return {
            "language": self.language,
            "preferred_audio": self.preferred_audio,
            "preferred_subtitle": self.preferred_subtitle,
            "auto_update": self.auto_update,
            "output": self.output.to_dict(),
            "download": self.download.to_dict(),
            "process": self.process.to_dict(),
            "network": self.network.to_dict(),
            "drm": self.drm.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        """Build an ``AppConfig`` from a raw dict (e.g. parsed JSON).

        Every key is optional.  Unknown keys are silently ignored.
        Invalid values fall back to defaults with a warning log.
        """
        if not isinstance(data, dict):
            log.warning("config: expected dict, got %s -- using all defaults", type(data).__name__)
            return cls()

        g = _safe_get

        language = g(data, "language", str, cls.language)
        if language not in ("auto", "it", "en"):
            log.warning("config: invalid language %r -- using default 'auto'", language)
            language = "auto"

        preferred_audio = g(data, "preferred_audio", str, cls.preferred_audio)
        preferred_subtitle = g(data, "preferred_subtitle", str, cls.preferred_subtitle)

        output_data = data.get("output")
        download_data = data.get("download")
        process_data = data.get("process")
        network_data = data.get("network")
        drm_data = data.get("drm")

        raw_services = data.get("services", {})
        if not isinstance(raw_services, dict):
            raw_services = {}
        clean_services: dict[str, dict[str, str]] = {}
        for short_name, sec in raw_services.items():
            if isinstance(sec, dict):
                clean_services[short_name] = {
                    k: str(v) for k, v in sec.items() if isinstance(v, (str, int, float))
                }

        return cls(
            language=language,
            preferred_audio=preferred_audio,
            preferred_subtitle=preferred_subtitle,
            auto_update=g(data, "auto_update", bool, cls.auto_update),
            output=(
                OutputConfig.from_dict(output_data)
                if isinstance(output_data, dict)
                else OutputConfig()
            ),
            download=(
                DownloadConfig.from_dict(download_data)
                if isinstance(download_data, dict)
                else DownloadConfig()
            ),
            process=(
                ProcessConfig.from_dict(process_data)
                if isinstance(process_data, dict)
                else ProcessConfig()
            ),
            network=(
                NetworkConfig.from_dict(network_data)
                if isinstance(network_data, dict)
                else NetworkConfig()
            ),
            drm=(
                DRMConfig.from_dict(drm_data)
                if isinstance(drm_data, dict)
                else DRMConfig()
            ),
            services=clean_services,
        )
