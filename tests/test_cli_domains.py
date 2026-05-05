from __future__ import annotations

from pathlib import Path

from streamload.cli.commands.domains import cmd_status, cmd_pin, cmd_refresh
from streamload.utils.domain_resolver.cache import DomainCache


def test_status_prints_no_entries(tmp_path: Path, capsys):
    cache = DomainCache(tmp_path / "c.json")
    cmd_status(cache=cache)
    out = capsys.readouterr().out
    assert "no cached domains" in out.lower()


def test_status_prints_each_cached_entry(tmp_path: Path, capsys):
    cache = DomainCache(tmp_path / "c.json")
    cache.set("sc", domain="x.tld", source="remote-github", validated_at=100.0)
    cmd_status(cache=cache)
    out = capsys.readouterr().out
    assert "sc" in out and "x.tld" in out and "remote-github" in out


def test_pin_writes_override_to_config_dict():
    cfg = {}
    cmd_pin(config=cfg, short_name="sc", url="https://my.tld")
    assert cfg["services"]["sc"]["base_url"] == "https://my.tld"


def test_refresh_invalidates_cache(tmp_path: Path):
    cache = DomainCache(tmp_path / "c.json")
    cache.set("sc", domain="x.tld", source="cache", validated_at=1.0)
    cmd_refresh(cache=cache, short_name="sc")
    assert cache.get("sc") is None
