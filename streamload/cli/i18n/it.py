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
    "menu.exit_confirm":     "Vuoi davvero uscire?",
    "menu.yes":              "Si",
    "menu.no":               "No",
    "menu.goodbye":          "Grazie per aver usato Streamload. Arrivederci!",

    # ── Search ────────────────────────────────────────────────────────────
    "search.prompt":           "Inserisci il titolo da cercare",
    "search.no_results":       "Nessun risultato trovato per \"{query}\"",
    "search.results_found":    "{count} risultati trovati per \"{query}\"",
    "search.searching":        "Ricerca in corso su {service}...",
    "search.global_searching": "Ricerca in corso su tutti i servizi...",
    "search.searching_service": "Cerca su {service}",

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
    "series.loading_seasons":  "Caricamento stagioni per {name}...",
    "series.loading_episodes": "Caricamento episodi per {name}...",

    # ── Track selection ───────────────────────────────────────────────────
    "tracks.video_header":    "Tracce video disponibili",
    "tracks.audio_header":    "Tracce audio disponibili",
    "tracks.subtitle_header": "Sottotitoli disponibili",
    "tracks.confirm":         "Conferma selezione tracce",
    "tracks.none_available":  "Nessuna traccia disponibile",

    # ── Settings ──────────────────────────────────────────────────────────
    "settings.title":              "Impostazioni",
    "settings.language":           "Lingua",
    "settings.preferred_audio":    "Audio preferito",
    "settings.preferred_subtitle": "Sottotitoli preferiti",
    "settings.output_path":        "Percorso di output",
    "settings.output_format":      "Formato di output",
    "settings.max_concurrent":     "Download simultanei",
    "settings.thread_count":       "Thread per download",
    "settings.auto_update":        "Aggiornamento automatico",
    "settings.on":                 "attivo",
    "settings.off":                "disattivo",
    "settings.saved":              "Impostazioni salvate",
    "settings.reset":              "Impostazioni ripristinate ai valori predefiniti",
    "settings.select_language":    "Seleziona la lingua",
    "settings.output_dir_prompt":  "Cartella di output (attuale: {current})",
    "settings.preferred_audio_prompt": "Lingua audio preferita (es. ita|it, eng|en)",
    "settings.preferred_subtitle_prompt": "Lingua sottotitoli preferita (es. ita|it, eng|en)",
    "settings.max_concurrent_prompt": "Download simultanei ({lo}-{hi}, attuale: {current})",
    "settings.thread_count_prompt": "Thread per download ({lo}-{hi}, attuale: {current})",
    "settings.invalid_number":     "Numero non valido: {value}",
    "settings.auto_update_enabled": "Aggiornamento automatico attivato",
    "settings.auto_update_disabled": "Aggiornamento automatico disattivato",

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
    "error.no_seasons":      "Nessuna stagione trovata.",
    "error.no_episodes":     "Nessun episodio trovato.",
    "error.no_services":     "Nessun servizio caricato.",
    "error.service_unavailable": "Il servizio '{service}' non e disponibile.",

    # ── Navigation ──────────────────────────────────────────────────────
    "nav.filter_placeholder":  "Digita per filtrare...",
    "nav.no_matches":          "Nessuna corrispondenza",
    "nav.items_above":         "{count} sopra",
    "nav.items_below":         "{count} sotto",
    "nav.selected_count":      "{count} selezionati",
    "nav.confirm_selection":   "Invio per confermare | Esc per annullare",
    "nav.type_to_filter":      "Digita per filtrare | Frecce per navigare",
    "nav.select_title":        "Seleziona un titolo",
    "nav.select_service":      "Seleziona un servizio",

    # ── Track selection (new) ────────────────────────────────────────────
    "tracks.no_video":         "Nessuna traccia video disponibile",
    "tracks.no_audio":         "Nessuna traccia audio trovata. Il download continuera senza audio.",
    "tracks.audio_embedded":   "Audio incluso nel video (nessuna selezione necessaria)",
    "tracks.no_subtitle":      "Nessun sottotitolo disponibile",
    "tracks.selection_summary": "{video} | {audio_count} audio | {sub_count} sottotitoli",
    "tracks.tab_hint":         "Tab: cambia sezione | Spazio: seleziona | Invio: conferma",

    # ── Download (new) ──────────────────────────────────────────────────
    "download.cancel_all":     "Annulla tutti",
    "download.cancel_selected": "Annulla selezionato",
    "download.pause":          "Pausa/Riprendi",
    "download.cancelled":      "Download annullato",
    "download.paused":         "In pausa",
    "download.completed_count": "{done}/{total} completati | {remaining} rimanenti",
    "download.total_speed":    "Velocita totale: {speed}",

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
    "system.restart_required": "Riavvia Streamload per utilizzare la nuova versione.",
    "system.update_failed":    "Aggiornamento fallito. Controlla il log per i dettagli.",

    # ── Download (resolving) ─────────────────────────────────────────────
    "download.resolving_streams": "Risoluzione stream per {name}...",
    "download.stream_resolution": "Risoluzione stream",
    "download.completed_summary": "Completati: {done}/{total}",
    "download.failed_summary":    "Falliti: {failed}",
    "download.skipping_episode":  "Salto E{number} -- impossibile risolvere gli stream.",

    # ── Film info ────────────────────────────────────────────────────────
    "info.film_details":     "Dettagli contenuto",
    "info.title":            "Titolo",
    "info.year":             "Anno",
    "info.genre":            "Genere",
    "info.service":          "Servizio",
    "info.type":             "Tipo",
    "info.not_available":    "N/D",
    "info.continue":         "Premi Invio per continuare...",

    # ── Breadcrumb ───────────────────────────────────────────────────────
    "breadcrumb.home":       "Home",
    "breadcrumb.results":    "Risultati",
    "breadcrumb.tracks":     "Tracce",
    "breadcrumb.season":     "Stagione {n}",
}
