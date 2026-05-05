from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def test_sign_creates_valid_signature(tmp_path: Path):
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path = tmp_path / "k.pem"
    key_path.write_bytes(priv_pem)

    manifest_path = tmp_path / "domains.json"
    payload = {
        "schema_version": 1,
        "key_id": "x",
        "issued_at": "2026-05-05T00:00:00Z",
        "ttl_seconds": 60,
        "services": {},
    }
    manifest_path.write_text(json.dumps(payload, sort_keys=True))

    out = subprocess.run(
        [sys.executable, "tools/sign_domains.py",
         "--key", str(key_path),
         "--manifest", str(manifest_path)],
        capture_output=True, text=True, check=True,
    )
    sig_path = manifest_path.with_suffix(manifest_path.suffix + ".sig")
    assert sig_path.exists()

    sig = base64.b64decode(sig_path.read_text().strip())
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    Ed25519PublicKey.from_public_bytes(pub_raw).verify(sig, manifest_path.read_bytes())
