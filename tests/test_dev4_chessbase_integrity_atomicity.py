from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import acs.chessbase_integrity as integrity


class Dev4ChessBaseIntegrityAtomicityTests(unittest.TestCase):
    """QA gate: ChessBase integrity evidence must describe one stable snapshot."""

    def test_snapshot_rejects_same_size_mutation_during_hashing(self) -> None:
        original = b"A" * (2 * 1024 * 1024)
        replacement = b"B" * len(original)

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "atomic.cbh"
            source.write_bytes(original)

            real_sha256 = hashlib.sha256
            mutated = False

            class MutatingDigest:
                def __init__(self) -> None:
                    self._inner = real_sha256()

                def update(self, chunk: bytes) -> None:
                    nonlocal mutated
                    self._inner.update(chunk)
                    if not mutated:
                        mutated = True
                        source.write_bytes(replacement)

                def hexdigest(self) -> str:
                    return self._inner.hexdigest()

            with patch.object(integrity, "sha256", side_effect=lambda: MutatingDigest()):
                with self.assertRaises((OSError, RuntimeError, ValueError)):
                    integrity.capture_integrity_snapshot(source)

            self.assertTrue(mutated, "test must exercise an in-flight same-size source mutation")
            self.assertEqual(source.stat().st_size, len(original))


if __name__ == "__main__":
    unittest.main()
