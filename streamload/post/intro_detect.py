"""Audio fingerprint-based intro/outro detection.

Uses ``pyacoustid``/``chromaprint`` to extract a fingerprint from the
first 90s of an episode's audio. When two episodes of the same series
share a prefix in their fingerprints, that's the intro.

The fingerprint is a sequence of 32-bit integers at ~8 Hz (one per
~125 ms frame). Comparison via Hamming distance per element.
"""
from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

CHROMAPRINT_SAMPLE_RATE_HZ = 7.84  # libchromaprint's default frame rate


@dataclass
class IntroResult:
    start_seconds: int
    end_seconds: int
    confidence: float


async def extract_fingerprint(audio_path: Path, *, length_seconds: int = 90) -> np.ndarray:
    """Run fpcalc to extract a Chromaprint fingerprint."""
    proc = await asyncio.create_subprocess_exec(
        "fpcalc", "-raw", "-length", str(length_seconds), str(audio_path),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    text = stdout.decode("utf-8")
    # fpcalc -raw outputs FINGERPRINT=<comma-sep-ints>
    line = next(line for line in text.splitlines() if line.startswith("FINGERPRINT="))
    ints = [int(x) for x in line.split("=", 1)[1].split(",") if x]
    return np.array(ints, dtype=np.uint32)


def compare_fingerprints(a: np.ndarray, b: np.ndarray) -> float:
    """Element-wise Hamming similarity, 0..1."""
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    xor = np.bitwise_xor(a[:n].view(np.uint32), b[:n].view(np.uint32))
    bits_diff = int(np.unpackbits(xor.view(np.uint8)).sum())
    bits_total = n * 32
    return 1.0 - (bits_diff / bits_total)


def find_common_intro(
    fp_a: np.ndarray, fp_b: np.ndarray,
    *, sample_rate_hz: float = CHROMAPRINT_SAMPLE_RATE_HZ,
    threshold: float = 0.85,
) -> Optional[IntroResult]:
    """Find the longest common high-similarity prefix.

    Walks frame-by-frame; groups consecutive matching frames; takes the
    longest run starting near offset 0 (the intro is at the beginning).
    """
    n = min(len(fp_a), len(fp_b))
    if n == 0:
        return None
    matches = np.array([compare_fingerprints(fp_a[i:i+1], fp_b[i:i+1]) >= threshold for i in range(n)])
    # Find the first run of True starting at offset 0
    if not matches[0]:
        # No intro starts at zero — try a small offset window (intros sometimes have a 1-2s logo before)
        return None
    end_idx = 0
    while end_idx < n and matches[end_idx]:
        end_idx += 1
    if end_idx < 5:
        return None  # too short to be an intro
    confidence = float(matches[:end_idx].mean())
    return IntroResult(
        start_seconds=0,
        end_seconds=int(end_idx / sample_rate_hz),
        confidence=confidence,
    )
