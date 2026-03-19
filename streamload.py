#!/usr/bin/env python3
"""Streamload - Professional CLI Video Downloader"""

import sys


def main():
    if sys.version_info < (3, 10):
        print(f"Streamload requires Python 3.10+. You have {sys.version_info.major}.{sys.version_info.minor}")
        sys.exit(1)

    from streamload.cli.app import StreamloadApp

    app = StreamloadApp()
    app.run()


if __name__ == "__main__":
    main()
