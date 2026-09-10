from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import acs.chessbase_integrity as integrity
import acs.import_contract as import_contract
from acs.chessbase_integrity import ChessBaseIntegrityIOError
from acs.import_contract import SourceFingerprint


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

            # ChessBase integrity now delegates byte identity to the canonical
            # descriptor-bound import fingerprint. Keep the adversarial oracle
            # at the authority that actually owns hashing rather than reviving a
            # second sha256 implementation in chessbase_integrity.
            with patch.object(
                import_contract.hashlib,
                "sha256",
                side_effect=lambda: MutatingDigest(),
            ):
                with self.assertRaises(ChessBaseIntegrityIOError):
                    integrity.capture_integrity_snapshot(source)

            self.assertTrue(mutated, "test must exercise an in-flight same-size source mutation")
            self.assertEqual(source.stat().st_size, len(original))

    def test_same_size_path_replacement_between_validation_and_open_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="d04-cbh-same-size-open-race-") as directory:
            root = Path(directory)
            source = root / "source.cbh"
            replacement = root / "replacement.bin"
            parked = root / "source.parked"
            original_bytes = b"authoritative-source-0001"
            replacement_bytes = b"B" * len(original_bytes)
            self.assertEqual(len(original_bytes), len(replacement_bytes))
            source.write_bytes(original_bytes)
            replacement.write_bytes(replacement_bytes)

            real_open = os.open
            swapped = False

            def swap_before_open(path, flags, *args, **kwargs):
                nonlocal swapped
                candidate = Path(os.fsdecode(path))
                if not swapped and candidate == source.absolute():
                    source.rename(parked)
                    replacement.rename(source)
                    swapped = True
                return real_open(path, flags, *args, **kwargs)

            try:
                with patch.object(import_contract.os, "open", side_effect=swap_before_open):
                    with self.assertRaises(ChessBaseIntegrityIOError):
                        integrity.capture_integrity_snapshot(source)
            finally:
                if swapped:
                    if source.exists():
                        source.rename(replacement)
                    if parked.exists():
                        parked.rename(source)

            self.assertTrue(swapped, "pathname replacement hook must execute")
            self.assertEqual(source.read_bytes(), original_bytes)
            self.assertEqual(replacement.read_bytes(), replacement_bytes)

    def test_opened_handle_must_match_the_validated_current_pathname(self) -> None:
        with tempfile.TemporaryDirectory(prefix="d04-cbh-handle-vs-path-") as directory:
            root = Path(directory)
            source = root / "source.cbh"
            foreign = root / "foreign.bin"
            source.write_bytes(b"A" * 64)
            foreign.write_bytes(b"B" * 64)

            real_open = os.open
            foreign_fd = real_open(os.fspath(foreign), os.O_RDONLY | getattr(os, "O_BINARY", 0))

            def substitute_foreign_handle(path, flags, *args, **kwargs):
                candidate = Path(os.fsdecode(path))
                if candidate == source.absolute():
                    return os.dup(foreign_fd)
                return real_open(path, flags, *args, **kwargs)

            try:
                with patch.object(import_contract.os, "open", side_effect=substitute_foreign_handle):
                    with self.assertRaises(ChessBaseIntegrityIOError):
                        integrity.capture_integrity_snapshot(source)
            finally:
                os.close(foreign_fd)

            self.assertEqual(source.read_bytes(), b"A" * 64)
            self.assertEqual(foreign.read_bytes(), b"B" * 64)

    def test_snapshot_sha_and_size_come_from_canonical_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory(prefix="d04-cbh-trusted-handle-evidence-") as directory:
            source = Path(directory) / "trusted.cbh"
            payload = b"canonical opened handle bytes"
            source.write_bytes(payload)

            canonical = import_contract.fingerprint(source)
            snapshot = integrity.capture_integrity_snapshot(source)
            evidence = snapshot.files[0]

            self.assertEqual(evidence.size_bytes, canonical.size)
            self.assertEqual(evidence.sha256, canonical.sha256)
            self.assertEqual(evidence.size_bytes, len(payload))
            self.assertEqual(evidence.sha256, hashlib.sha256(payload).hexdigest())

    @unittest.skipUnless(os.name == "nt", "Windows path-spelling contract")
    def test_windows_83_like_canonical_spelling_does_not_replace_user_provenance_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="d04-cbh-user-path-") as directory:
            source = Path(directory) / "User Submitted Name.cbh"
            payload = b"stable provenance"
            source.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            canonical_alias = SourceFingerprint(
                path=r"C:\Users\RUNNER~1\AppData\Local\User Submitted Name.cbh",
                size=len(payload),
                sha256=digest,
                suffix=".cbh",
            )

            with patch.object(integrity, "_canonical_fingerprint", return_value=canonical_alias):
                snapshot = integrity.capture_integrity_snapshot(source)

            self.assertEqual(snapshot.primary_path, source)
            self.assertEqual(snapshot.files[0].path, source)
            self.assertEqual(snapshot.files[0].size_bytes, canonical_alias.size)
            self.assertEqual(snapshot.files[0].sha256, canonical_alias.sha256)
            self.assertNotEqual(str(snapshot.files[0].path), canonical_alias.path)


if __name__ == "__main__":
    unittest.main()
