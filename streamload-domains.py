#!/usr/bin/env python3
"""Standalone CLI for managing the Streamload domain resolver.

Usage:
    streamload-domains.py status
    streamload-domains.py refresh [<service>]
    streamload-domains.py pin <service> <url>

The main Streamload app is curses-based; this script provides operator-grade
domain management without entering the interactive UI.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from streamload.cli.commands.domains import cmd_pin, cmd_refresh, cmd_status
from streamload.utils.domain_resolver.cache import DomainCache

CACHE_PATH = Path("data/domains_cache.json")
CONFIG_PATH = Path("config.json")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="streamload-domains")
    sub = p.add_subparsers(dest="action", required=True)

    sub.add_parser("status")

    p_refresh = sub.add_parser("refresh")
    p_refresh.add_argument("service", nargs="?", default=None)

    p_pin = sub.add_parser("pin")
    p_pin.add_argument("service")
    p_pin.add_argument("url")

    args = p.parse_args(argv)
    cache = DomainCache(CACHE_PATH)

    if args.action == "status":
        cmd_status(cache=cache)
    elif args.action == "refresh":
        cmd_refresh(cache=cache, short_name=args.service)
    elif args.action == "pin":
        config = {}
        if CONFIG_PATH.exists():
            try:
                config = json.loads(CONFIG_PATH.read_text())
            except json.JSONDecodeError:
                print(f"warning: could not parse {CONFIG_PATH}; will overwrite", file=sys.stderr)
        cmd_pin(config=config, short_name=args.service, url=args.url)
        CONFIG_PATH.write_text(json.dumps(config, indent=4, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
