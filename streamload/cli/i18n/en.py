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
    "settings.title":       "Settings",
    "settings.language":    "Language",
    "settings.output_path": "Output path",
    "settings.saved":       "Settings saved",
    "settings.reset":       "Settings reset to defaults",

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
