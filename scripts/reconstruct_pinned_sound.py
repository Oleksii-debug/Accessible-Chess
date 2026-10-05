"""Reassemble the test branch's pinned, immutable 330-WAV build input."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys


CHUNK_COUNT = 30
EXPECTED_BYTES = 20_838_229


def reconstruct(source: Path, target: Path, wanted_sha256: str) -> None:
    if len(wanted_sha256) != 64 or any(c not in "0123456789abcdef" for c in wanted_sha256):
        raise ValueError("invalid expected sound archive SHA-256")
    expected = [f"{index:02d}.part" for index in range(CHUNK_COUNT)]
    actual = sorted(path.name for path in source.iterdir())
    if actual != expected:
        raise ValueError("pinned sound chunks are incomplete")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    digest = hashlib.sha256()
    total = 0
    try:
        with temporary.open("xb") as output:
            for name in expected:
                with (source / name).open("rb") as part:
                    while data := part.read(1024 * 1024):
                        total += len(data)
                        if total > EXPECTED_BYTES:
                            raise ValueError("pinned sound archive exceeds expected size")
                        digest.update(data)
                        output.write(data)
        if total != EXPECTED_BYTES or digest.hexdigest() != wanted_sha256:
            raise ValueError("pinned sound archive identity mismatch")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: reconstruct_pinned_sound.py PARTS OUTPUT SHA256")
    reconstruct(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
