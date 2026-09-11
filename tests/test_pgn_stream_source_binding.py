from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import acs.pgn_streaming_import as streaming
from acs.acsdb import AcsDatabase
from acs.library_import_service import LibraryImportResult, LibraryImportService
from acs.pgn_streaming_import import (
    StreamingPgnErrorCode,
    StreamingPgnFailurePolicy,
    StreamingPgnImportError,
    StreamingPgnLibraryImporter,
    StreamingPgnLimits,
    StreamingPgnPhase,
)


ORIGINAL_PGN = '''[Event "Original one"]
[Result "*"]

1. e4 e5 *

[Event "Original two"]
[Result "*"]

1. d4 d5 *
'''

REPLACEMENT_PGN = '''[Event "Replacement one"]
[Result "*"]

1. c4 e5 *

[Event "Replacement two"]
[Result "*"]

1. Nf3 d5 *
'''


class _ReplaceBeforeStreamImporter(StreamingPgnLibraryImporter):
    def __init__(self, library: object, replacement: Path) -> None:
        super().__init__(library)
        self._replacement = replacement

    def _stream_source(self, source, spool, **kwargs):
        # Preliminary identity/fingerprint binding is complete, but the held
        # streaming descriptor has not yet been opened.
        self._replacement.replace(Path(source.path))
        return super()._stream_source(source, spool, **kwargs)


class _MutateBeforePublicationImporter(StreamingPgnLibraryImporter):
    def _stream_source(self, source, spool, **kwargs):
        failure = super()._stream_source(source, spool, **kwargs)
        path = Path(source.path)
        original = path.read_bytes()
        mutated = original.replace(b"Original two", b"Changed! two", 1)
        if len(mutated) != len(original) or mutated == original:
            raise AssertionError("test mutation must preserve source size")
        with path.open("r+b", buffering=0) as handle:
            handle.seek(0)
            handle.write(mutated)
            handle.flush()
            os.fsync(handle.fileno())
        return failure


class _ObservedLibraryProxy:
    """Minimal equivalent of the V2 D07 observer wrapper around Library."""

    def __init__(self, service: LibraryImportService) -> None:
        self._service = service
        self.results: list[LibraryImportResult] = []

    def import_games(self, *args, **kwargs):
        result = self._service.import_games(*args, **kwargs)
        self.results.append(result)
        return result


class StreamingPgnSourceBindingTests(unittest.TestCase):
    def test_replacement_between_fingerprint_and_stream_is_rejected_before_parse(self) -> None:
        with tempfile.TemporaryDirectory() as directory, AcsDatabase() as database:
            root = Path(directory)
            source = root / "source.pgn"
            replacement = root / "replacement.pgn"
            source.write_text(ORIGINAL_PGN, encoding="utf-8", newline="")
            replacement.write_text(REPLACEMENT_PGN, encoding="utf-8", newline="")
            progress = []

            importer = _ReplaceBeforeStreamImporter(
                LibraryImportService(database),
                replacement,
            )
            with self.assertRaises(StreamingPgnImportError) as caught:
                importer.import_file(
                    source,
                    failure_policy=StreamingPgnFailurePolicy.SOURCE_ATOMIC,
                    progress_callback=progress.append,
                )

            self.assertEqual(caught.exception.code, StreamingPgnErrorCode.SOURCE_CHANGED)
            self.assertEqual(
                [item for item in progress if item.phase is StreamingPgnPhase.PARSING],
                [],
            )
            self.assertEqual(database.search_games(limit=100), [])

    def test_byte_identical_replacement_before_stream_open_is_rejected_by_object_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory, AcsDatabase() as database:
            root = Path(directory)
            source = root / "source.pgn"
            replacement = root / "replacement.pgn"
            source.write_text(ORIGINAL_PGN, encoding="utf-8", newline="")
            replacement.write_text(ORIGINAL_PGN, encoding="utf-8", newline="")
            original_identity = (source.stat().st_dev, source.stat().st_ino)
            progress = []

            importer = _ReplaceBeforeStreamImporter(
                LibraryImportService(database),
                replacement,
            )
            with self.assertRaises(StreamingPgnImportError) as caught:
                importer.import_file(
                    source,
                    failure_policy=StreamingPgnFailurePolicy.SOURCE_ATOMIC,
                    progress_callback=progress.append,
                )

            self.assertEqual(caught.exception.code, StreamingPgnErrorCode.SOURCE_CHANGED)
            self.assertNotEqual((source.stat().st_dev, source.stat().st_ino), original_identity)
            self.assertEqual(source.read_text(encoding="utf-8"), ORIGINAL_PGN)
            self.assertEqual(
                [item for item in progress if item.phase is StreamingPgnPhase.PARSING],
                [],
            )
            self.assertEqual(database.search_games(limit=100), [])

    def test_path_swap_after_descriptor_open_never_redirects_parse_or_publishes(self) -> None:
        with tempfile.TemporaryDirectory() as directory, AcsDatabase() as database:
            root = Path(directory)
            source = root / "source.pgn"
            replacement = root / "replacement.pgn"
            source.write_text(ORIGINAL_PGN, encoding="utf-8", newline="")
            replacement.write_bytes(b"\xffreplacement bytes must never be parsed\n")
            progress = []
            original_open = streaming._open_bound_source_fd
            swapped = False
            swap_blocked = False

            def open_then_swap(*args, **kwargs):
                nonlocal swapped, swap_blocked
                fd = original_open(*args, **kwargs)
                try:
                    replacement.replace(source)
                except PermissionError:
                    # Windows opens this descriptor without delete sharing, so NT
                    # itself prevents the path replacement while the trusted fd is
                    # held. That is a valid stronger form of the same invariant.
                    swap_blocked = True
                else:
                    swapped = True
                return fd

            caught = None
            result = None
            with patch.object(streaming, "_open_bound_source_fd", side_effect=open_then_swap):
                try:
                    result = StreamingPgnLibraryImporter(
                        LibraryImportService(database)
                    ).import_file(
                        source,
                        failure_policy=StreamingPgnFailurePolicy.SOURCE_ATOMIC,
                        progress_callback=progress.append,
                    )
                except StreamingPgnImportError as exc:
                    caught = exc

            self.assertNotEqual(swapped, swap_blocked)
            self.assertTrue(
                any(
                    item.phase is StreamingPgnPhase.PARSING and item.accepted_games == 2
                    for item in progress
                )
            )

            if swapped:
                self.assertIsNotNone(caught)
                self.assertEqual(caught.code, StreamingPgnErrorCode.SOURCE_CHANGED)
                self.assertEqual(
                    source.read_bytes(),
                    b"\xffreplacement bytes must never be parsed\n",
                )
                self.assertEqual(database.search_games(limit=100), [])
            else:
                self.assertTrue(swap_blocked)
                self.assertIsNone(caught)
                self.assertIsNotNone(result)
                self.assertTrue(result.complete)
                self.assertEqual(source.read_text(encoding="utf-8"), ORIGINAL_PGN)
                self.assertEqual(len(database.search_games(limit=100)), 2)

    def test_same_inode_mutation_during_read_is_rejected_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory, AcsDatabase() as database:
            source = Path(directory) / "source.pgn"
            source.write_text(ORIGINAL_PGN, encoding="utf-8", newline="")
            original = source.read_bytes()
            mutated = original.replace(b"Original two", b"Changed! two", 1)
            self.assertEqual(len(mutated), len(original))
            self.assertNotEqual(mutated, original)
            identity = (source.stat().st_dev, source.stat().st_ino)
            did_mutate = False
            progress = []

            def mutate_after_first_read(item):
                nonlocal did_mutate
                progress.append(item)
                if did_mutate or item.phase is not StreamingPgnPhase.PARSING:
                    return
                with source.open("r+b", buffering=0) as handle:
                    handle.seek(0)
                    handle.write(mutated)
                    handle.flush()
                    os.fsync(handle.fileno())
                did_mutate = True

            with self.assertRaises(StreamingPgnImportError) as caught:
                StreamingPgnLibraryImporter(LibraryImportService(database)).import_file(
                    source,
                    failure_policy=StreamingPgnFailurePolicy.SOURCE_ATOMIC,
                    limits=StreamingPgnLimits(read_chunk_bytes=16),
                    progress_callback=mutate_after_first_read,
                )

            self.assertTrue(did_mutate)
            self.assertEqual(caught.exception.code, StreamingPgnErrorCode.SOURCE_CHANGED)
            self.assertEqual((source.stat().st_dev, source.stat().st_ino), identity)
            self.assertEqual(source.read_bytes(), mutated)
            self.assertEqual(database.search_games(limit=100), [])

    def test_same_inode_mutation_after_parse_before_publication_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory, AcsDatabase() as database:
            source = Path(directory) / "source.pgn"
            source.write_text(ORIGINAL_PGN, encoding="utf-8", newline="")
            identity = (source.stat().st_dev, source.stat().st_ino)

            with self.assertRaises(StreamingPgnImportError) as caught:
                _MutateBeforePublicationImporter(LibraryImportService(database)).import_file(
                    source,
                    failure_policy=StreamingPgnFailurePolicy.SOURCE_ATOMIC,
                )

            self.assertEqual(caught.exception.code, StreamingPgnErrorCode.SOURCE_CHANGED)
            self.assertEqual((source.stat().st_dev, source.stat().st_ino), identity)
            self.assertIn(b"Changed! two", source.read_bytes())
            self.assertEqual(database.search_games(limit=100), [])

    def test_streaming_accepts_v2_observer_wrapped_canonical_library_service(self) -> None:
        with tempfile.TemporaryDirectory() as directory, AcsDatabase() as database:
            source = Path(directory) / "observed.pgn"
            source.write_text(ORIGINAL_PGN, encoding="utf-8", newline="")
            observed = _ObservedLibraryProxy(LibraryImportService(database))

            result = StreamingPgnLibraryImporter(observed).import_file(
                source,
                failure_policy=StreamingPgnFailurePolicy.SOURCE_ATOMIC,
            )

            self.assertTrue(result.complete)
            self.assertEqual(result.accepted_games, 2)
            self.assertEqual(result.library.game_count, 2)
            self.assertEqual(observed.results, [result.library])
            self.assertEqual(len(database.search_games(limit=100)), 2)

    def test_streaming_rejects_non_library_result_from_structural_port(self) -> None:
        class InvalidLibrary:
            def import_games(self, *args, **kwargs):
                return object()

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "invalid-result.pgn"
            source.write_text(ORIGINAL_PGN, encoding="utf-8", newline="")
            importer = StreamingPgnLibraryImporter(InvalidLibrary())

            with self.assertRaises(StreamingPgnImportError) as caught:
                importer.import_file(
                    source,
                    failure_policy=StreamingPgnFailurePolicy.SOURCE_ATOMIC,
                )

            self.assertEqual(caught.exception.code, StreamingPgnErrorCode.LIBRARY_ERROR)


if __name__ == "__main__":
    unittest.main()