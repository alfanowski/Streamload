#!/usr/bin/env python3
"""Streamload - Professional CLI Video Downloader"""

import argparse
import sys


def main():
    if sys.version_info < (3, 10):
        print(f"Streamload requires Python 3.10+. You have {sys.version_info.major}.{sys.version_info.minor}")
        sys.exit(1)

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--api", action="store_true", help="Start the API server")
    args, _ = parser.parse_known_args()

    if args.api:
        import os
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
