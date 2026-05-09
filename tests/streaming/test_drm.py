from unittest.mock import MagicMock
from streamload.streaming.drm import build_decryptor


def test_build_decryptor_uses_keys_to_decrypt():
    # Provide a mocked low-level decrypt fn
    keys = [{"kid": "x", "key": "y"}]
    raw = b"ciphertext"
    fake_decrypt = MagicMock(return_value=b"plaintext")
    dec = build_decryptor(keys=keys, _decrypt_fn=fake_decrypt)
    out = dec(raw)
    assert out == b"plaintext"
    fake_decrypt.assert_called_once_with(raw, keys)


def test_build_decryptor_returns_none_when_no_keys():
    dec = build_decryptor(keys=None)
    assert dec is None
