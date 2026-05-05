from pathlib import Path
from unittest.mock import MagicMock

from streamload.utils.domain_resolver.factory import build_resolver


def test_build_resolver_returns_configured_instance(tmp_path: Path):
    http = MagicMock()
    cfg_overrides = {"sc": "x.tld"}
    seeds = {"sc": ["seed.tld"]}
    resolver = build_resolver(
        http=http,
        config_overrides=cfg_overrides,
        probe_seeds=seeds,
        cache_path=tmp_path / "c.json",
        repo="alfanowski/Streamload",
        branch="main",
    )
    assert resolver is not None
