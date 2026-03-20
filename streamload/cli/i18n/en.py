"""English (en) string table for the Streamload CLI."""

from __future__ import annotations

STRINGS: dict[str, str] = {
    # ── Menu ──────────────────────────────────────────────────────────────
    "menu.welcome":          "Welcome to Streamload!",
    "menu.search":           "Search content",
    "menu.select_service":   "Select service",
    "menu.global_search":    "Global search",
    "menu.settings":         "Settings",
    "menu.exit":             "Exit",
    "menu.back":             "Back",
    "menu.exit_confirm":     "Do you really want to exit?",
    "menu.yes":              "Yes",
    "menu.no":               "No",
    "menu.goodbye":          "Thank you for using Streamload. Goodbye!",

    # ── Search ────────────────────────────────────────────────────────────
    "search.prompt":           "Enter a title to search for",
    "search.no_results":       "No results found for \"{query}\"",
    "search.results_found":    "{count} results found for \"{query}\"",
    "search.searching":        "Searching on {service}...",
    "search.global_searching": "Searching across all services...",
    "search.searching_service": "Search {service}",

    # ── Download ──────────────────────────────────────────────────────────
    "download.select_quality":  "Select video quality",
    "download.select_audio":    "Select audio track",
    "download.select_subtitle": "Select subtitles",
    "download.progress":        "Downloading {name}... {pct}%",
    "download.complete":        "Download complete: {name}",
    "download.failed":          "Download failed: {name} - {reason}",
    "download.starting":        "Starting download of {name}...",
    "download.queue_remaining": "{count} downloads remaining in queue",
    "download.speed_total":     "Speed: {speed} | Downloaded: {total}",
    "download.eta":             "Estimated time remaining: {eta}",
    "download.merging":         "Merging tracks for {name}...",
    "download.cleanup":         "Cleaning up temporary files...",

    # ── Series ────────────────────────────────────────────────────────────
    "series.select_season":    "Select season",
    "series.select_episodes":  "Select episodes",
    "series.all_episodes":     "All episodes",
    "series.episode_range":    "Episodes {start} to {end}",
    "series.episodes_selected": "{count} episodes selected",
    "series.loading_seasons":  "Loading seasons for {name}...",
    "series.loading_episodes": "Loading episodes for {name}...",

    # ── Track selection ───────────────────────────────────────────────────
    "tracks.video_header":    "Available video tracks",
    "tracks.audio_header":    "Available audio tracks",
    "tracks.subtitle_header": "Available subtitles",
    "tracks.confirm":         "Confirm track selection",
    "tracks.none_available":  "No tracks available",

    # ── Settings ──────────────────────────────────────────────────────────
    "settings.title":              "Settings",
    "settings.language":           "Language",
    "settings.preferred_audio":    "Preferred audio",
    "settings.preferred_subtitle": "Preferred subtitle",
    "settings.output_path":        "Output path",
    "settings.output_format":      "Output format",
    "settings.max_concurrent":     "Concurrent downloads",
    "settings.thread_count":       "Threads per download",
    "settings.auto_update":        "Auto-update",
    "settings.on":                 "on",
    "settings.off":                "off",
    "settings.saved":              "Settings saved",
    "settings.reset":              "Settings reset to defaults",
    "settings.select_language":    "Select language",
    "settings.output_dir_prompt":  "Output directory (current: {current})",
    "settings.preferred_audio_prompt": "Preferred audio language (e.g. ita|it, eng|en)",
    "settings.preferred_subtitle_prompt": "Preferred subtitle language (e.g. ita|it, eng|en)",
    "settings.max_concurrent_prompt": "Max concurrent downloads ({lo}-{hi}, current: {current})",
    "settings.thread_count_prompt": "Thread count per download ({lo}-{hi}, current: {current})",
    "settings.invalid_number":     "Invalid number: {value}",
    "settings.auto_update_enabled": "Auto-update enabled",
    "settings.auto_update_disabled": "Auto-update disabled",

    # ── Errors ────────────────────────────────────────────────────────────
    "error.generic":         "An error occurred: {message}",
    "error.network":         "Network error: {message}",
    "error.service":         "Service error on {service}: {message}",
    "error.drm":             "DRM error: unable to decrypt protected content",
    "error.merge":           "Error merging tracks: {message}",
    "error.config":          "Configuration error: {message}",
    "error.ffmpeg_missing":  "FFmpeg not found. Please install it to continue.",
    "error.auth_required":   "Authentication required for {service}",
    "error.auth_failed":     "Authentication failed for {service}",
    "error.no_streams":      "No streams available for {name}",
    "error.no_seasons":      "No seasons found.",
    "error.no_episodes":     "No episodes found.",
    "error.no_services":     "No services loaded.",
    "error.service_unavailable": "Service '{service}' is not available.",

    # ── Navigation ──────────────────────────────────────────────────────
    "nav.filter_placeholder":  "Type to filter...",
    "nav.no_matches":          "No matches",
    "nav.items_above":         "{count} above",
    "nav.items_below":         "{count} below",
    "nav.selected_count":      "{count} selected",
    "nav.confirm_selection":   "Enter to confirm | Esc to cancel",
    "nav.type_to_filter":      "Type to filter | Arrows to navigate",
    "nav.select_title":        "Select a title",
    "nav.select_service":      "Select a service",

    # ── Track selection (new) ────────────────────────────────────────────
    "tracks.no_video":         "No video tracks available",
    "tracks.no_audio":         "No audio tracks found. Download will continue without audio.",
    "tracks.audio_embedded":   "Audio embedded in video (no selection needed)",
    "tracks.no_subtitle":      "No subtitles available",
    "tracks.selection_summary": "{video} | {audio_count} audio | {sub_count} subtitles",
    "tracks.tab_hint":         "Tab: switch section | Space: select | Enter: confirm",

    # ── Download (new) ──────────────────────────────────────────────────
    "download.cancel_all":     "Cancel all",
    "download.cancel_selected": "Cancel selected",
    "download.pause":          "Pause/Resume",
    "download.cancelled":      "Download cancelled",
    "download.paused":         "Paused",
    "download.completed_count": "{done}/{total} completed | {remaining} remaining",
    "download.total_speed":    "Total speed: {speed}",

    # ── System ────────────────────────────────────────────────────────────
    "system.checking_deps":    "Checking dependencies...",
    "system.ffmpeg_found":     "FFmpeg found: {version}",
    "system.ffmpeg_missing":   "FFmpeg not found",
    "system.ffmpeg_install":   "Install FFmpeg to enable downloading",
    "system.update_available": "New version available: {version}",
    "system.update_prompt":    "Would you like to update Streamload to version {version}?",
    "system.updating":         "Updating...",
    "system.update_done":      "Updated to version {version}",
    "system.startup":          "Starting Streamload v{version}...",
    "system.restart_required": "Please restart Streamload to use the new version.",
    "system.update_failed":    "Update failed. Check the log for details.",

    # ── Download (resolving) ─────────────────────────────────────────────
    "download.resolving_streams": "Resolving streams for {name}...",
    "download.stream_resolution": "Stream Resolution",
    "download.completed_summary": "Completed: {done}/{total}",
    "download.failed_summary":    "Failed: {failed}",
    "download.skipping_episode":  "Skipping E{number} -- could not resolve streams.",

    # ── Film info ────────────────────────────────────────────────────────
    "info.film_details":     "Content Details",
    "info.title":            "Title",
    "info.year":             "Year",
    "info.genre":            "Genre",
    "info.service":          "Service",
    "info.type":             "Type",
    "info.not_available":    "N/A",
    "info.continue":         "Press Enter to continue...",

    # ── Breadcrumb ───────────────────────────────────────────────────────
    "breadcrumb.home":       "Home",
    "breadcrumb.results":    "Results",
    "breadcrumb.tracks":     "Tracks",
    "breadcrumb.season":     "Season {n}",
}
