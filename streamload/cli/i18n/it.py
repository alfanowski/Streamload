"""Italian (it) string table for the Streamload CLI."""

from __future__ import annotations

STRINGS: dict[str, str] = {
    # ── Menu ──────────────────────────────────────────────────────────────
    "menu.welcome":          "Benvenuto in Streamload!",
    "menu.search":           "Cerca contenuto",
    "menu.select_service":   "Seleziona servizio",
    "menu.global_search":    "Ricerca globale",
    "menu.settings":         "Impostazioni",
    "menu.exit":             "Esci",
    "menu.back":             "Indietro",

    # ── Search ────────────────────────────────────────────────────────────
    "search.prompt":           "Inserisci il titolo da cercare",
    "search.no_results":       "Nessun risultato trovato per \"{query}\"",
    "search.results_found":    "{count} risultati trovati per \"{query}\"",
    "search.searching":        "Ricerca in corso su {service}...",
    "search.global_searching": "Ricerca in corso su tutti i servizi...",

    # ── Download ──────────────────────────────────────────────────────────
    "download.select_quality":  "Seleziona la qualita video",
    "download.select_audio":    "Seleziona la traccia audio",
    "download.select_subtitle": "Seleziona i sottotitoli",
    "download.progress":        "Scaricamento {name}... {pct}%",
    "download.complete":        "Download completato: {name}",
    "download.failed":          "Download fallito: {name} - {reason}",
    "download.starting":        "Avvio download di {name}...",
    "download.queue_remaining": "{count} download rimanenti in coda",
    "download.speed_total":     "Velocita: {speed} | Scaricati: {total}",
    "download.eta":             "Tempo rimanente stimato: {eta}",
    "download.merging":         "Unione tracce per {name}...",
    "download.cleanup":         "Pulizia file temporanei...",

    # ── Series ────────────────────────────────────────────────────────────
    "series.select_season":    "Seleziona la stagione",
    "series.select_episodes":  "Seleziona gli episodi",
    "series.all_episodes":     "Tutti gli episodi",
    "series.episode_range":    "Episodi da {start} a {end}",
    "series.episodes_selected": "{count} episodi selezionati",

    # ── Track selection ───────────────────────────────────────────────────
    "tracks.video_header":    "Tracce video disponibili",
    "tracks.audio_header":    "Tracce audio disponibili",
    "tracks.subtitle_header": "Sottotitoli disponibili",
    "tracks.confirm":         "Conferma selezione tracce",
    "tracks.none_available":  "Nessuna traccia disponibile",

    # ── Settings ──────────────────────────────────────────────────────────
    "settings.title":       "Impostazioni",
    "settings.language":    "Lingua",
    "settings.output_path": "Percorso di output",
    "settings.saved":       "Impostazioni salvate",
    "settings.reset":       "Impostazioni ripristinate ai valori predefiniti",

    # ── Errors ────────────────────────────────────────────────────────────
    "error.generic":         "Si e verificato un errore: {message}",
    "error.network":         "Errore di rete: {message}",
    "error.service":         "Errore del servizio {service}: {message}",
    "error.drm":             "Errore DRM: impossibile decifrare il contenuto protetto",
    "error.merge":           "Errore durante l'unione delle tracce: {message}",
    "error.config":          "Errore nella configurazione: {message}",
    "error.ffmpeg_missing":  "FFmpeg non trovato. Installalo per continuare.",
    "error.auth_required":   "Autenticazione richiesta per {service}",
    "error.auth_failed":     "Autenticazione fallita per {service}",
    "error.no_streams":      "Nessuno stream disponibile per {name}",

    # ── System ────────────────────────────────────────────────────────────
    "system.checking_deps":    "Verifica dipendenze...",
    "system.ffmpeg_found":     "FFmpeg trovato: {version}",
    "system.ffmpeg_missing":   "FFmpeg non trovato",
    "system.ffmpeg_install":   "Installa FFmpeg per abilitare il download",
    "system.update_available": "Nuova versione disponibile: {version}",
    "system.update_prompt":    "Vuoi aggiornare Streamload alla versione {version}?",
    "system.updating":         "Aggiornamento in corso...",
    "system.update_done":      "Aggiornamento completato alla versione {version}",
    "system.startup":          "Avvio di Streamload v{version}...",
}
