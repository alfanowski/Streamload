#!/usr/bin/env python3
"""Streamload - Professional CLI Video Downloader"""

import argparse
import os
import sys
from pathlib import Path


def _load_dotenv() -> None:
    """Load KEY=VALUE pairs from a sibling `.env` file into os.environ.

    Existing env vars take precedence (so a shell export overrides .env).
    Quiet no-op if the file is missing.
    """
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main():
    if sys.version_info < (3, 10):
        print(f"Streamload requires Python 3.10+. You have {sys.version_info.major}.{sys.version_info.minor}")
        sys.exit(1)

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--api", action="store_true", help="Start the API server")
    args, _ = parser.parse_known_args()

    if args.api:
        _load_dotenv()
        from granian import Granian

        server = Granian(
            target="streamload.api.app:app",
            address=os.environ.get("STREAMLOAD_API_HOST", "127.0.0.1"),
            port=int(os.environ.get("STREAMLOAD_API_PORT", "8000")),
            interface="asgi",
            loop="auto",
            workers=1,
        )
        server.serve()
        sys.exit(0)

    from streamload.cli.app import StreamloadApp

    app = StreamloadApp()
    app.run()


if __name__ == "__main__":
    main()
