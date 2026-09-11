from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.library_import_service import LibraryImportResult, LibraryImportService
from acs.pgn_streaming_import import (
    StreamingPgnErrorCode,
    StreamingPgnFailurePolicy,
    StreamingPgnImportError,
    StreamingPgnLibraryImporter,
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
        # This is the exact historical gap: the preliminary fingerprint is done,
        # but the streaming descriptor has not yet been opened. Replace the path
        # atomically with a different valid regular PGN before delegating.
        self._replacement.replace(Path(source.path))
        return super()._stream_source(source, spool, **kwargs)


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
            # A path swap must be rejected at descriptor binding, not after the
            # replacement has already been parsed into canonical frames.
            self.assertEqual(
                [item for item in progress if item.phase is StreamingPgnPhase.PARSING],
                [],
            )
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
