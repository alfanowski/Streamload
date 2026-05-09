"""Audio fingerprint extraction + comparison."""
import numpy as np
import pytest

from streamload.post.intro_detect import (
    compare_fingerprints,
    find_common_intro,
)


def test_compare_identical_returns_high_score():
    fp = np.array([1, 2, 3, 4, 5], dtype=np.int32)
    assert compare_fingerprints(fp, fp) > 0.99


def test_compare_different_returns_low_score():
    # Use uint32 values that differ maximally in bit representation (alternating 0/1 patterns)
    a = np.array([0x55555555] * 5, dtype=np.uint32)   # 0101...0101
    b = np.array([0xAAAAAAAA] * 5, dtype=np.uint32)   # 1010...1010 — every bit flipped
    assert compare_fingerprints(a, b) < 0.1


def test_find_common_intro_detects_shared_prefix():
    """Two fingerprints with same first N samples should yield N as the intro length."""
    common = np.array([1, 2, 3, 4, 5, 6, 7, 8], dtype=np.int32)
    diff_a = np.array([10, 11, 12], dtype=np.int32)
    diff_b = np.array([20, 21, 22], dtype=np.int32)
    fp_a = np.concatenate([common, diff_a])
    fp_b = np.concatenate([common, diff_b])
    res = find_common_intro(fp_a, fp_b, sample_rate_hz=8.0)  # synthetic SR
    assert res is not None
    assert res.start_seconds == 0
    assert res.end_seconds == 1  # 8 samples / 8 Hz = 1s
    assert res.confidence > 0.8
