"""Pytest configuration and shared fixtures for Streamload tests."""
from __future__ import annotations

import sys
from pathlib import Path

# Allow `import streamload` from tests without installing the package.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
