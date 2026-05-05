"""Verify the CLI startup wires the DomainResolver into instantiated services."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


def test_startup_attaches_resolver_to_all_services():
    """When the app boots, every instantiated service receives a resolver."""
    from streamload.cli.app import StreamloadApp
    from streamload.models.config import AppConfig
    from streamload.utils.domain_resolver.factory import build_resolver  # noqa: F401

    # Build two fake service instances whose attach_resolver we can spy on.
    fake_svc_a = MagicMock()
    fake_svc_b = MagicMock()
    fake_instances = {"sc": fake_svc_a, "au": fake_svc_b}

    fake_resolver = MagicMock()

    app = StreamloadApp.__new__(StreamloadApp)

    # Patch out the real startup helpers so we isolate the wiring logic.
    with (
        patch(
            "streamload.cli.app.load_services",
        ),
        patch(
            "streamload.cli.app.ServiceRegistry.instantiate_all",
            return_value=fake_instances,
        ),
        patch(
            "streamload.cli.app.ServiceRegistry.get_all",
            return_value=[],
        ),
        patch(
            "streamload.cli.app.build_resolver",
            return_value=fake_resolver,
        ) as mock_build,
        patch.object(app.__class__, "_check_system_deps"),
        patch.object(app.__class__, "_authenticate_services"),
        patch.object(app.__class__, "_check_for_updates"),
        patch.object(app.__class__, "_config_mgr", create=True, new_callable=MagicMock),
    ):
        # Provide a minimal config with no service overrides.
        fake_config = AppConfig()
        app._config_mgr.config = fake_config  # type: ignore[attr-defined]

        # Stub out UI / HTTP components so _startup() doesn't crash.
        app._console = MagicMock()  # type: ignore[attr-defined]
        app._i18n = MagicMock()  # type: ignore[attr-defined]
        app._prompts = MagicMock()  # type: ignore[attr-defined]
        app._selector = MagicMock()  # type: ignore[attr-defined]
        app._progress_ui = MagicMock()  # type: ignore[attr-defined]
        app._breadcrumb = []  # type: ignore[attr-defined]
        app._http = MagicMock()  # type: ignore[attr-defined]
        app._tmdb = MagicMock()  # type: ignore[attr-defined]
        app._vault = MagicMock()  # type: ignore[attr-defined]
        app._drm = MagicMock()  # type: ignore[attr-defined]
        app._download_mgr = MagicMock()  # type: ignore[attr-defined]
        app._callbacks = MagicMock()  # type: ignore[attr-defined]
        app._updater = MagicMock()  # type: ignore[attr-defined]

        with (
            patch("streamload.cli.app.HttpClient", return_value=app._http),
            patch("streamload.cli.app.I18n", return_value=app._i18n),
            patch("streamload.cli.app.UIPrompts", return_value=app._prompts),
            patch("streamload.cli.app.InteractiveSelector", return_value=app._selector),
            patch("streamload.cli.app.DownloadProgressUI", return_value=app._progress_ui),
            patch("streamload.cli.app.TMDBClient", return_value=app._tmdb),
            patch("streamload.cli.app.LocalVault", return_value=app._vault),
            patch("streamload.cli.app.DRMManager", return_value=app._drm),
            patch("streamload.cli.app.DownloadManager", return_value=app._download_mgr),
            patch("streamload.cli.app.CLICallbacks", return_value=app._callbacks),
            patch("streamload.cli.app.Updater", return_value=app._updater),
            patch("streamload.cli.app.ConfigManager", return_value=app._config_mgr),
        ):
            app._startup()

    # build_resolver must have been called once.
    mock_build.assert_called_once()

    # cache_path must be the agreed location.
    _, kwargs = mock_build.call_args
    assert kwargs["cache_path"] == Path("data/domains_cache.json")
    assert kwargs["repo"] == "alfanowski/Streamload"

    # Every service instance must have received the resolver.
    fake_svc_a.attach_resolver.assert_called_once_with(fake_resolver)
    fake_svc_b.attach_resolver.assert_called_once_with(fake_resolver)
