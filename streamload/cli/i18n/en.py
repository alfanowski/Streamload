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

    # ── Search ────────────────────────────────────────────────────────────
    "search.prompt":           "Enter a title to search for",
    "search.no_results":       "No results found for \"{query}\"",
    "search.results_found":    "{count} results found for \"{query}\"",
    "search.searching":        "Searching on {service}...",
    "search.global_searching": "Searching across all services...",

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
}
