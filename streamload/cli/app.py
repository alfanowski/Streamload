"""Main CLI application orchestrator for Streamload.

Ties together every subsystem -- services, downloads, DRM, configuration,
internationalisation, and the rich terminal UI -- into a cohesive user
flow.  This is the single entry-point for the interactive CLI.

Usage::

    from streamload.cli.app import StreamloadApp

    app = StreamloadApp()
    app.run()
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.status import Status

from streamload.cli.i18n import I18n
from streamload.cli.terminal import TerminalManager
from streamload.cli.ui import (
    DownloadProgressUI,
    InteractiveSelector,
    SearchResultTable,
    UIPrompts,
)
from streamload.core.downloader.manager import DownloadJob, DownloadManager
from streamload.core.drm.manager import DRMManager
from streamload.core.events import (
    DownloadComplete,
    DownloadProgress,
    ErrorEvent,
    EventCallbacks,
    MergeProgress,
    SearchProgress,
    TrackSelection,
    WarningEvent,
)
from streamload.core.exceptions import StreamloadError
from streamload.core.vault.local import LocalVault
from streamload.models.media import (
    Episode,
    MediaEntry,
    MediaType,
    SearchResult,
)
from streamload.models.stream import SelectedTracks, StreamBundle
from streamload.services import ServiceRegistry, load_services
from streamload.services.base import ServiceBase
from streamload.utils.config import ConfigManager
from streamload.utils.http import HttpClient
from streamload.utils.logger import get_logger, setup_logging
from streamload.utils.system import SystemChecker
from streamload.utils.tmdb import TMDBClient
from streamload.utils.updater import Updater
from streamload.version import __version__

if TYPE_CHECKING:
    from streamload.models.media import Season

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# CLI callback adapter
# ---------------------------------------------------------------------------


class CLICallbacks(EventCallbacks):
    """CLI implementation of :class:`EventCallbacks`.

    Routes core-engine events to the appropriate rich UI component so the
    download pipeline never touches the console directly.
    """

    def __init__(
        self,
        console: Console,
        progress_ui: DownloadProgressUI,
        prompts: UIPrompts,
        selector: InteractiveSelector,
        i18n: I18n,
    ) -> None:
        self._console = console
        self._progress = progress_ui
        self._prompts = prompts
        self._selector = selector
        self._i18n = i18n
        self._completed_jobs: list[DownloadComplete] = []

    # -- EventCallbacks interface ------------------------------------------

    def on_track_selection(self, event: TrackSelection) -> SelectedTracks:
        """Present the interactive track selector and return the user's picks.

        Builds a temporary :class:`StreamBundle` from the event data so the
        :class:`InteractiveSelector` can render its standard UI.
        """
        bundle = StreamBundle(
            video=list(event.video_tracks),
            audio=list(event.audio_tracks),
            subtitles=list(event.subtitle_tracks),
        )
        preferred_audio = self._i18n.get_audio_preferences()
        preferred_sub = self._i18n.get_subtitle_preferences()

        result = self._selector.select_tracks(
            bundle,
            preferred_audio=preferred_audio,
            preferred_subtitle=preferred_sub,
        )
        if result is None:
            # User cancelled -- return the first video track with no extras
            # so the pipeline has something valid.  The caller should detect
            # cancellation via the minimal selection.
            from streamload.models.stream import SelectedTracks as ST

            return ST(video=event.video_tracks[0])
        return result

    def on_progress(self, event: DownloadProgress) -> None:
        """Forward download progress to the live progress UI."""
        self._progress.update(event)

    def on_complete(self, event: DownloadComplete) -> None:
        """Record completion and update the progress panel."""
        self._completed_jobs.append(event)
        self._progress.complete(event)

    def on_error(self, event: ErrorEvent) -> None:
        """Display an error to the user via the prompts helper."""
        msg = event.message or str(event.error)
        if event.download_id:
            msg = f"[{event.download_id}] {msg}"
        self._prompts.show_error(msg)
        log.error("CLICallbacks error: %s", msg)

    def on_warning(self, event: WarningEvent) -> None:
        """Display a non-fatal warning."""
        msg = event.message
        if event.context:
            msg = f"{msg} ({event.context})"
        self._prompts.show_warning(msg)

    def on_merge_progress(self, event: MergeProgress) -> None:
        """Update the progress panel with the current merge stage."""
        self._progress.set_merging(event)

    def on_search_progress(self, event: SearchProgress) -> None:
        """Log search progress -- the live spinner is handled at the app level."""
        log.debug(
            "Search progress: service=%s status=%s results=%d",
            event.service_name,
            event.status,
            event.results_count,
        )


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------


class StreamloadApp:
    """Main application orchestrator.

    Implements the complete interactive flow:

    1. **Startup** -- dependency checks, config load, service discovery,
       TMDB / DRM / download-manager initialisation, update check.
    2. **Main menu loop** -- global search, per-service search, settings.
    3. **Search flow** -- query -> aggregated results table -> select.
    4. **Content selection** -- film goes straight to tracks; series
       navigates season -> episodes first.
    5. **Track selection** -- interactive video / audio / subtitle picker.
    6. **Download** -- progress bars, DRM key acquisition, FFmpeg merge.
    7. **Completion summary** -- sizes, paths, elapsed time.
    """

    def __init__(self) -> None:
        self._console = Console()
        self._config_mgr = ConfigManager()
        self._terminal = TerminalManager()

        # These are populated during _startup().
        self._i18n: I18n | None = None
        self._http: HttpClient | None = None
        self._services: dict[str, ServiceBase] = {}
        self._tmdb: TMDBClient | None = None
        self._drm: DRMManager | None = None
        self._vault: LocalVault | None = None
        self._download_mgr: DownloadManager | None = None
        self._prompts: UIPrompts | None = None
        self._tables: SearchResultTable | None = None
        self._selector: InteractiveSelector | None = None
        self._updater: Updater | None = None
        self._progress_ui: DownloadProgressUI | None = None
        self._callbacks: CLICallbacks | None = None

    # ==================================================================
    # Entry point
    # ==================================================================

    def run(self) -> None:
        """Main entry point.  Called from the CLI launcher script."""
        setup_logging()
        log.info("Streamload v%s starting", __version__)

        with self._terminal:
            try:
                self._startup()
                self._main_menu_loop()
            except KeyboardInterrupt:
                self._safe_print("\n[dim]Interrupted. Goodbye.[/dim]")
            except Exception as exc:
                log.error("Fatal error", exc_info=True)
                self._safe_print(f"\n[bold red]Fatal error:[/bold red] {exc}")
            finally:
                self._shutdown()

    # ==================================================================
    # Startup
    # ==================================================================

    def _startup(self) -> None:
        """Execute the full startup sequence.

        1. Load configuration.
        2. Initialise i18n from the configured / detected language.
        3. Build UI components (prompts, tables, selector, progress).
        4. Check system dependencies (Python, FFmpeg, FFprobe).
        5. Initialise the HTTP client.
        6. Discover and instantiate streaming services.
        7. Initialise TMDB client, DRM manager, download manager.
        8. Check for application updates.
        9. Display the startup banner.
        """
        # 1. Config
        config = self._config_mgr.config

        # 2. i18n
        lang = config.language if config.language != "auto" else "auto"
        self._i18n = I18n(lang)

        # 3. UI
        self._prompts = UIPrompts(self._console)
        self._tables = SearchResultTable(self._console)
        self._selector = InteractiveSelector(self._console)
        self._progress_ui = DownloadProgressUI(self._console)

        # 4. System dependencies
        self._check_system_deps()

        # 5. HTTP client
        self._http = HttpClient(config.network)

        # 6. Services
        load_services()
        self._services = ServiceRegistry.instantiate_all(self._http, config)
        self._authenticate_services()

        # 7. TMDB, DRM, downloader
        tmdb_key = self._config_mgr.get_tmdb_api_key()
        self._tmdb = TMDBClient(api_key=tmdb_key or "", http_client=self._http)

        self._vault = LocalVault()
        self._drm = DRMManager(
            config=config.drm,
            http_client=self._http,
            vault=self._vault,
        )

        self._callbacks = CLICallbacks(
            console=self._console,
            progress_ui=self._progress_ui,
            prompts=self._prompts,
            selector=self._selector,
            i18n=self._i18n,
        )

        self._download_mgr = DownloadManager(
            config=config,
            http_client=self._http,
            drm_manager=self._drm,
            callbacks=self._callbacks,
        )

        # 8. Update check
        self._updater = Updater(self._http)
        if config.auto_update:
            self._check_for_updates()

        # 9. Banner
        self._prompts.show_banner(__version__)
        svc_count = len(self._services)
        self._prompts.show_info(
            self._i18n.t("system.startup", version=__version__)
            + f"  ({svc_count} service{'s' if svc_count != 1 else ''} loaded)"
        )

    def _check_system_deps(self) -> None:
        """Verify FFmpeg / FFprobe are installed."""
        assert self._prompts is not None
        assert self._i18n is not None

        checker = SystemChecker()
        results = checker.verify_all()

        for result in results:
            if result.found:
                if result.name == "FFmpeg":
                    self._prompts.show_success(
                        self._i18n.t("system.ffmpeg_found", version=result.version or "?")
                    )
            else:
                if result.name in ("FFmpeg", "FFprobe"):
                    self._prompts.show_error(
                        self._i18n.t("error.ffmpeg_missing")
                        + f"\n{result.message or ''}"
                    )
                    log.error("Missing dependency: %s", result.name)

    def _authenticate_services(self) -> None:
        """Authenticate services that require login using stored credentials."""
        for short_name, service in self._services.items():
            if not service.requires_login:
                continue
            creds = self._config_mgr.get_service_credentials(service.name)
            if creds is None:
                creds = self._config_mgr.get_service_credentials(short_name)
            if creds:
                try:
                    session = service.authenticate(creds)
                    if session:
                        service.set_session(session)
                        log.info("Authenticated with %s", service.name)
                except Exception:
                    log.warning("Authentication failed for %s", service.name, exc_info=True)

    def _check_for_updates(self) -> None:
        """Check GitHub for a newer version and offer to update."""
        assert self._updater is not None
        assert self._prompts is not None
        assert self._i18n is not None

        try:
            info = self._updater.check_update()
        except Exception:
            log.debug("Update check failed", exc_info=True)
            return

        if info is None:
            return

        self._prompts.show_info(
            self._i18n.t("system.update_available", version=info.version)
        )
        if self._prompts.confirm(
            self._i18n.t("system.update_prompt", version=info.version),
            default=False,
        ):
            with Status(
                self._i18n.t("system.updating"), console=self._console
            ):
                success = self._updater.apply_update(info, project_root=Path.cwd())
            if success:
                self._prompts.show_success(
                    self._i18n.t("system.update_done", version=info.version)
                )
                self._prompts.show_info("Please restart Streamload to use the new version.")
            else:
                self._prompts.show_error("Update failed. Check the log for details.")

    # ==================================================================
    # Main menu
    # ==================================================================

    def _main_menu_loop(self) -> None:
        """Display the main menu and dispatch user choices.

        [1] Global search
        [2] Select service
        [3] Settings
        [4] Exit

        Loops until the user selects Exit or presses Ctrl+C.
        """
        assert self._prompts is not None
        assert self._i18n is not None

        while True:
            try:
                choices = [
                    self._i18n.t("menu.global_search"),
                    self._i18n.t("menu.select_service"),
                    self._i18n.t("menu.settings"),
                    self._i18n.t("menu.exit"),
                ]
                selection = self._prompts.choose(
                    self._i18n.t("menu.welcome"), choices
                )

                if selection == 0:
                    self._global_search()
                elif selection == 1:
                    service = self._select_service()
                    if service is not None:
                        self._service_search(service)
                elif selection == 2:
                    self._show_settings()
                elif selection == 3:
                    self._console.print(
                        "\n[dim]Thank you for using Streamload. Goodbye.[/dim]\n"
                    )
                    break

            except KeyboardInterrupt:
                # Ctrl+C inside a menu returns to the top of the loop.
                self._console.print()
                continue

    # ==================================================================
    # Search flows
    # ==================================================================

    def _global_search(self) -> None:
        """Search across all loaded services in parallel.

        Displays a spinner per service while results stream in, then
        shows an aggregated results table.
        """
        assert self._prompts is not None
        assert self._i18n is not None
        assert self._tables is not None

        query = self._prompts.ask(self._i18n.t("search.prompt"))
        if not query.strip():
            return

        self._console.print()
        results: list[SearchResult] = []

        with Status(
            self._i18n.t("search.global_searching"),
            console=self._console,
            spinner="dots",
        ):

            def _on_progress(service_name: str, status: str, count: int) -> None:
                log.info(
                    "Global search: %s -> %s (%d results)",
                    service_name,
                    status,
                    count,
                )

            results = ServiceRegistry.search_all(
                query,
                self._services,
                on_progress=_on_progress,
            )

        if not results:
            self._prompts.show_warning(
                self._i18n.t("search.no_results", query=query)
            )
            return

        # Enrich with TMDB metadata.
        self._enrich_results(results)

        self._prompts.show_info(
            self._i18n.t("search.results_found", count=len(results), query=query)
        )
        self._tables.display(results, title=f"Results for \"{query}\"")

        # Let the user pick one.
        self._pick_from_results(results)

    def _service_search(self, service: ServiceBase) -> None:
        """Search within a single service."""
        assert self._prompts is not None
        assert self._i18n is not None
        assert self._tables is not None

        query = self._prompts.ask(self._i18n.t("search.prompt"))
        if not query.strip():
            return

        self._console.print()
        entries: list[MediaEntry] = []

        with Status(
            self._i18n.t("search.searching", service=service.name),
            console=self._console,
            spinner="dots",
        ):
            try:
                entries = service.search(query)
            except Exception as exc:
                log.error("Search failed on %s", service.name, exc_info=True)
                self._prompts.show_error(
                    self._i18n.t(
                        "error.service",
                        service=service.name,
                        message=str(exc),
                    )
                )
                return

        if not entries:
            self._prompts.show_warning(
                self._i18n.t("search.no_results", query=query)
            )
            return

        results = [
            SearchResult(
                entry=entry,
                service_display_name=service.name,
                match_score=getattr(entry, "match_score", 0.5),
            )
            for entry in entries
        ]

        # Enrich with TMDB metadata.
        self._enrich_results(results)

        self._prompts.show_info(
            self._i18n.t("search.results_found", count=len(results), query=query)
        )
        self._tables.display(results, title=f"Results for \"{query}\" on {service.name}")

        self._pick_from_results(results)

    def _select_service(self) -> ServiceBase | None:
        """Show a numbered list of services and let the user pick one."""
        assert self._prompts is not None

        if not self._services:
            self._prompts.show_warning("No services loaded.")
            return None

        names: list[str] = []
        keys: list[str] = []
        for key, svc in sorted(self._services.items(), key=lambda kv: kv[1].name):
            auth_tag = ""
            if svc.requires_login:
                auth_tag = " [green](authenticated)[/green]" if svc.is_authenticated else " [dim](login required)[/dim]"
            names.append(f"{svc.name} [dim]({svc.language})[/dim]{auth_tag}")
            keys.append(key)

        names.append(self._i18n.t("menu.back") if self._i18n else "Back")
        idx = self._prompts.choose("Select a service", names)

        if idx >= len(keys):
            return None

        return self._services[keys[idx]]

    def _pick_from_results(self, results: list[SearchResult]) -> None:
        """Let the user pick a result from a displayed table, then handle it."""
        assert self._prompts is not None

        if not results:
            return

        options = [
            f"{r.entry.title} ({r.entry.year or '?'}) - {r.service_display_name}"
            for r in results
        ]
        options.append(self._i18n.t("menu.back") if self._i18n else "Back")

        idx = self._prompts.choose("Select a title", options)
        if idx >= len(results):
            return

        self._handle_search_result(results[idx])

    def _enrich_results(self, results: list[SearchResult]) -> None:
        """Enrich search results with TMDB metadata (year, genre, etc.)."""
        if self._tmdb is None or not self._tmdb.enabled:
            return

        assert self._i18n is not None
        tmdb_lang = "it-IT" if self._i18n.lang == "it" else "en-US"

        entries = [r.entry for r in results]
        self._tmdb.enrich_entries(entries, language=tmdb_lang)

    # ==================================================================
    # Content handling
    # ==================================================================

    def _handle_search_result(self, result: SearchResult) -> None:
        """Route a selected result to the film or series flow."""
        entry = result.entry
        service = self._services.get(entry.service)
        if service is None:
            assert self._prompts is not None
            self._prompts.show_error(
                f"Service '{entry.service}' is not available."
            )
            return

        try:
            if entry.type == MediaType.FILM:
                self._handle_film(entry, service)
            else:
                self._handle_series(entry, service)
        except KeyboardInterrupt:
            self._console.print("\n[dim]Cancelled.[/dim]")
        except StreamloadError as exc:
            assert self._prompts is not None
            self._prompts.show_error(str(exc))
            log.error("Content handling error: %s", exc, exc_info=True)
        except Exception as exc:
            assert self._prompts is not None
            self._prompts.show_error(
                self._i18n.t("error.generic", message=str(exc))
                if self._i18n
                else str(exc)
            )
            log.error("Unexpected error handling result", exc_info=True)

    def _handle_film(self, entry: MediaEntry, service: ServiceBase) -> None:
        """Film flow: get streams -> select tracks -> download."""
        assert self._prompts is not None
        assert self._i18n is not None

        # Resolve streams.
        bundle = self._get_streams(entry, service)
        if bundle is None:
            return

        # Select tracks.
        tracks = self._select_tracks(bundle)
        if tracks is None:
            return

        # Download.
        job = DownloadJob(item=entry, bundle=bundle, tracks=tracks)
        self._download_single(job)

    def _handle_series(self, entry: MediaEntry, service: ServiceBase) -> None:
        """Series flow: pick season -> pick episodes -> download batch."""
        assert self._prompts is not None
        assert self._tables is not None
        assert self._selector is not None
        assert self._i18n is not None

        # Fetch seasons.
        seasons: list[Season] = []
        with Status(
            f"Loading seasons for {entry.title}...",
            console=self._console,
            spinner="dots",
        ):
            try:
                seasons = service.get_seasons(entry)
            except Exception as exc:
                self._prompts.show_error(
                    self._i18n.t("error.service", service=service.name, message=str(exc))
                )
                return

        if not seasons:
            self._prompts.show_warning("No seasons found.")
            return

        self._tables.display_seasons(seasons, title=entry.title)

        # Pick season.
        season_options = [
            s.title if s.title else f"Season {s.number}" for s in seasons
        ]
        season_options.append(self._i18n.t("menu.back"))
        season_idx = self._prompts.choose(
            self._i18n.t("series.select_season"), season_options
        )
        if season_idx >= len(seasons):
            return

        selected_season = seasons[season_idx]

        # Fetch episodes.
        episodes: list[Episode] = []
        with Status(
            f"Loading episodes for Season {selected_season.number}...",
            console=self._console,
            spinner="dots",
        ):
            try:
                episodes = service.get_episodes(selected_season)
            except Exception as exc:
                self._prompts.show_error(
                    self._i18n.t("error.service", service=service.name, message=str(exc))
                )
                return

        if not episodes:
            self._prompts.show_warning("No episodes found.")
            return

        self._tables.display_episodes(
            episodes,
            title=f"{entry.title} - Season {selected_season.number}",
        )

        # Pick episodes.
        selected_episodes = self._selector.select_episodes(
            episodes,
            title=self._i18n.t("series.select_episodes"),
        )
        if not selected_episodes:
            return

        self._prompts.show_info(
            self._i18n.t("series.episodes_selected", count=len(selected_episodes))
        )

        # Get streams for the first episode to determine tracks.
        first_bundle = self._get_streams(selected_episodes[0], service)
        if first_bundle is None:
            return

        tracks = self._select_tracks(first_bundle)
        if tracks is None:
            return

        # Build jobs for all selected episodes.
        jobs: list[DownloadJob] = []
        for ep in selected_episodes:
            if ep is selected_episodes[0]:
                bundle = first_bundle
            else:
                bundle = self._get_streams(ep, service)
                if bundle is None:
                    self._prompts.show_warning(
                        f"Skipping E{ep.number:02d} -- could not resolve streams."
                    )
                    continue

            jobs.append(DownloadJob(item=ep, bundle=bundle, tracks=tracks))

        if jobs:
            self._download_batch(jobs)

    # ==================================================================
    # Stream & track helpers
    # ==================================================================

    def _get_streams(
        self, item: Episode | MediaEntry, service: ServiceBase
    ) -> StreamBundle | None:
        """Resolve streams for an item, showing a spinner."""
        assert self._prompts is not None
        assert self._i18n is not None

        name = item.title if isinstance(item, MediaEntry) else f"E{item.number:02d} {item.title}"

        with Status(
            f"Resolving streams for {name}...",
            console=self._console,
            spinner="dots",
        ):
            try:
                bundle = service.get_streams(item)
            except Exception as exc:
                self._prompts.show_error(
                    self._i18n.t("error.no_streams", name=name) + f"\n{exc}"
                )
                log.error("get_streams failed for %s", name, exc_info=True)
                return None

        if not bundle.video:
            self._prompts.show_error(
                self._i18n.t("error.no_streams", name=name)
            )
            return None

        return bundle

    def _select_tracks(self, bundle: StreamBundle) -> SelectedTracks | None:
        """Present the interactive track selector to the user."""
        assert self._selector is not None
        assert self._i18n is not None

        config = self._config_mgr.config
        preferred_audio = config.preferred_audio
        preferred_sub = config.preferred_subtitle

        if preferred_audio == "auto":
            preferred_audio = self._i18n.get_audio_preferences()
        if preferred_sub == "auto":
            preferred_sub = self._i18n.get_subtitle_preferences()

        try:
            return self._selector.select_tracks(
                bundle,
                preferred_audio=preferred_audio,
                preferred_subtitle=preferred_sub,
            )
        except KeyboardInterrupt:
            return None

    # ==================================================================
    # Download execution
    # ==================================================================

    def _download_single(self, job: DownloadJob) -> None:
        """Execute a single download with live progress."""
        assert self._download_mgr is not None
        assert self._progress_ui is not None
        assert self._prompts is not None
        assert self._i18n is not None

        name = (
            job.item.title
            if isinstance(job.item, MediaEntry)
            else f"E{job.item.number:02d} {job.item.title}"
            if isinstance(job.item, Episode)
            else "Unknown"
        )

        self._prompts.show_info(self._i18n.t("download.starting", name=name))

        self._progress_ui.set_queue_info(total=1, remaining=1)
        with self._progress_ui:
            try:
                self._download_mgr.download_single(job)
            except StreamloadError as exc:
                # Error is already reported via callbacks; log it.
                log.error("Download failed: %s", exc)
            except Exception as exc:
                self._prompts.show_error(
                    self._i18n.t("download.failed", name=name, reason=str(exc))
                )
                log.error("Download failed unexpectedly", exc_info=True)

        self._show_job_summary([job])

    def _download_batch(self, jobs: list[DownloadJob]) -> None:
        """Execute multiple download jobs with concurrent progress tracking."""
        assert self._download_mgr is not None
        assert self._progress_ui is not None
        assert self._prompts is not None
        assert self._i18n is not None

        total = len(jobs)
        self._prompts.show_info(
            self._i18n.t("download.queue_remaining", count=total)
        )

        self._progress_ui.set_queue_info(total=total, remaining=total)
        with self._progress_ui:
            try:
                self._download_mgr.download_batch(jobs)
            except Exception as exc:
                self._prompts.show_error(
                    self._i18n.t("error.generic", message=str(exc))
                )
                log.error("Batch download error", exc_info=True)

        self._show_job_summary(jobs)

    def _show_job_summary(self, jobs: list[DownloadJob]) -> None:
        """Print a post-download summary table."""
        assert self._prompts is not None

        completed = [j for j in jobs if j.status == "complete"]
        failed = [j for j in jobs if j.status == "failed"]

        if completed:
            self._console.print()
            for job in completed:
                path_str = str(job.output_path) if job.output_path else "?"
                self._prompts.show_success(
                    f"{self._job_display_name(job)} -> {path_str}"
                )

        if failed:
            self._console.print()
            for job in failed:
                self._prompts.show_error(
                    f"{self._job_display_name(job)}: {job.error or 'Unknown error'}"
                )

        self._console.print()
        self._prompts.show_info(
            f"Completed: {len(completed)}/{len(jobs)}"
            + (f"  |  Failed: {len(failed)}" if failed else "")
        )

    @staticmethod
    def _job_display_name(job: DownloadJob) -> str:
        """Build a human-readable name for a download job."""
        if isinstance(job.item, Episode):
            return f"S{job.item.season_number:02d}E{job.item.number:02d} {job.item.title}"
        if isinstance(job.item, MediaEntry):
            return job.item.title
        return job.id

    # ==================================================================
    # Settings
    # ==================================================================

    def _show_settings(self) -> None:
        """Settings menu -- view and modify configuration values."""
        assert self._prompts is not None
        assert self._i18n is not None

        while True:
            try:
                config = self._config_mgr.config

                settings_choices = [
                    f"{self._i18n.t('settings.language')}: {config.language}",
                    f"Preferred audio: {config.preferred_audio}",
                    f"Preferred subtitle: {config.preferred_subtitle}",
                    f"{self._i18n.t('settings.output_path')}: {config.output.root_path}",
                    f"Output format: {config.output.extension}",
                    f"Max concurrent downloads: {config.download.max_concurrent}",
                    f"Thread count: {config.download.thread_count}",
                    f"Auto-update: {'on' if config.auto_update else 'off'}",
                    self._i18n.t("menu.back"),
                ]

                idx = self._prompts.choose(
                    self._i18n.t("settings.title"), settings_choices
                )

                if idx == 0:
                    self._change_language()
                elif idx == 1:
                    self._change_setting_string("preferred_audio", "Preferred audio language (e.g. ita|it, eng|en)")
                elif idx == 2:
                    self._change_setting_string("preferred_subtitle", "Preferred subtitle language (e.g. ita|it, eng|en)")
                elif idx == 3:
                    self._change_output_path()
                elif idx == 4:
                    self._change_output_format()
                elif idx == 5:
                    self._change_setting_int("download.max_concurrent", "Max concurrent downloads", 1, 10)
                elif idx == 6:
                    self._change_setting_int("download.thread_count", "Thread count per download", 1, 32)
                elif idx == 7:
                    self._toggle_auto_update()
                elif idx >= 8:
                    break

            except KeyboardInterrupt:
                break

    def _change_language(self) -> None:
        """Let the user switch display language."""
        assert self._prompts is not None

        lang_choices = ["English", "Italiano", "Auto-detect"]
        idx = self._prompts.choose("Select language", lang_choices)

        lang_map = {0: "en", 1: "it", 2: "auto"}
        new_lang = lang_map[idx]

        config = self._config_mgr.config
        config.language = new_lang
        self._config_mgr.save_config(config)

        # Reinitialise i18n with the new language.
        self._i18n = I18n(new_lang)
        self._prompts.show_success(self._i18n.t("settings.saved"))

    def _change_output_path(self) -> None:
        """Change the download root directory."""
        assert self._prompts is not None
        assert self._i18n is not None

        config = self._config_mgr.config
        new_path = self._prompts.ask(
            "Output directory", default=config.output.root_path
        )
        if new_path.strip():
            config.output.root_path = new_path.strip()
            self._config_mgr.save_config(config)
            self._prompts.show_success(self._i18n.t("settings.saved"))

    def _change_output_format(self) -> None:
        """Switch between mkv and mp4 container format."""
        assert self._prompts is not None
        assert self._i18n is not None

        fmt_choices = ["mkv", "mp4"]
        idx = self._prompts.choose("Output format", fmt_choices)

        config = self._config_mgr.config
        config.output.extension = fmt_choices[idx]
        self._config_mgr.save_config(config)
        self._prompts.show_success(self._i18n.t("settings.saved"))

    def _change_setting_string(self, field_path: str, label: str) -> None:
        """Change a string configuration value by dotted path."""
        assert self._prompts is not None
        assert self._i18n is not None

        config = self._config_mgr.config
        current = self._get_config_field(config, field_path)
        new_val = self._prompts.ask(label, default=str(current))
        if new_val.strip():
            self._set_config_field(config, field_path, new_val.strip())
            self._config_mgr.save_config(config)
            self._prompts.show_success(self._i18n.t("settings.saved"))

    def _change_setting_int(
        self, field_path: str, label: str, lo: int, hi: int
    ) -> None:
        """Change an integer configuration value with range clamping."""
        assert self._prompts is not None
        assert self._i18n is not None

        config = self._config_mgr.config
        current = self._get_config_field(config, field_path)
        raw = self._prompts.ask(f"{label} ({lo}-{hi})", default=str(current))
        try:
            value = max(lo, min(hi, int(raw)))
            self._set_config_field(config, field_path, value)
            self._config_mgr.save_config(config)
            self._prompts.show_success(self._i18n.t("settings.saved"))
        except ValueError:
            self._prompts.show_error(f"Invalid number: {raw}")

    def _toggle_auto_update(self) -> None:
        """Toggle the auto-update setting."""
        assert self._prompts is not None
        assert self._i18n is not None

        config = self._config_mgr.config
        config.auto_update = not config.auto_update
        self._config_mgr.save_config(config)
        state = "enabled" if config.auto_update else "disabled"
        self._prompts.show_success(f"Auto-update {state}")

    @staticmethod
    def _get_config_field(config: object, path: str) -> object:
        """Traverse dotted path on config object (e.g. 'download.thread_count')."""
        obj: object = config
        for segment in path.split("."):
            obj = getattr(obj, segment)
        return obj

    @staticmethod
    def _set_config_field(config: object, path: str, value: object) -> None:
        """Set a value on a config object via dotted path."""
        parts = path.split(".")
        obj: object = config
        for segment in parts[:-1]:
            obj = getattr(obj, segment)
        setattr(obj, parts[-1], value)

    # ==================================================================
    # Shutdown
    # ==================================================================

    def _shutdown(self) -> None:
        """Release all resources gracefully."""
        if self._http is not None:
            try:
                self._http.close()
            except Exception:
                log.debug("Error closing HTTP client", exc_info=True)

        if self._vault is not None:
            try:
                self._vault.close()
            except Exception:
                log.debug("Error closing vault", exc_info=True)

        log.info("Streamload shutdown complete")

    # ==================================================================
    # Utilities
    # ==================================================================

    def _safe_print(self, text: str) -> None:
        """Print to console, swallowing any I/O errors."""
        try:
            self._console.print(text)
        except Exception:
            pass
