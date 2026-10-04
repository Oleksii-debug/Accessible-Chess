from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from acs.import_contract import fingerprint


class Dev4ImportFingerprintAtomicityTests(unittest.TestCase):
    """QA gate for provenance snapshots taken while a source is changing."""

    def test_fingerprint_rejects_source_mutation_during_hashing(self) -> None:
        """A fingerprint must describe one stable source state, not stale/mixed bytes.

        The shared import boundary relies on SourceFingerprint as provenance
        evidence.  Mutating the source immediately after the first digest update
        deterministically places a write inside the current hash loop.  A safe
        implementation must detect the unstable snapshot and fail closed rather
        than return a normal SourceFingerprint for bytes that changed while the
        evidence was being collected.
        """

        original = b"AAAA1111"
        replacement = b"BBBB2222"  # same size: size-only checks cannot save us.

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "changing.pgn"
            source.write_bytes(original)
            real_sha256 = hashlib.sha256

            class MutatingDigest:
                def __init__(self) -> None:
                    self._inner = real_sha256()
                    self._mutated = False

                def update(self, chunk: bytes) -> None:
                    self._inner.update(chunk)
                    if not self._mutated:
                        self._mutated = True
                        source.write_bytes(replacement)

                def hexdigest(self) -> str:
                    return self._inner.hexdigest()

            with mock.patch(
                "acs.import_contract.hashlib.sha256",
                side_effect=MutatingDigest,
            ):
                with self.assertRaises((ValueError, OSError, RuntimeError)):
                    fingerprint(source, chunk_size=4)

            self.assertEqual(source.read_bytes(), replacement)


if __name__ == "__main__":
    unittest.main()
