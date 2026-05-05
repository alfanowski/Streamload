"""Sign domains.json with the Ed25519 private key.

Usage::

    python tools/sign_domains.py --key secret/domains_signing_key.pem \
                                 --manifest domains.json

Output: writes ``<manifest>.sig`` containing base64-encoded signature.
"""
from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--key", required=True, type=Path,
                   help="Path to PEM-encoded Ed25519 private key")
    p.add_argument("--manifest", required=True, type=Path,
                   help="Path to domains.json")
    args = p.parse_args(argv)

    priv_obj = serialization.load_pem_private_key(args.key.read_bytes(), password=None)
    if not isinstance(priv_obj, Ed25519PrivateKey):
        print("ERROR: key is not Ed25519", file=sys.stderr)
        return 2

    payload = args.manifest.read_bytes()
    sig = priv_obj.sign(payload)
    sig_b64 = base64.b64encode(sig).decode("ascii")

    sig_path = args.manifest.with_suffix(args.manifest.suffix + ".sig")
    sig_path.write_text(sig_b64 + "\n")
    print(f"wrote {sig_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
