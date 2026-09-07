from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.library_import_service import LibraryImportService
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
    def __init__(self, library: LibraryImportService, replacement: Path) -> None:
        super().__init__(library)
        self._replacement = replacement

    def _stream_source(self, source, spool, **kwargs):
        # This is the exact historical gap: the preliminary fingerprint is done,
        # but the streaming descriptor has not yet been opened.  Replace the path
        # atomically with a different valid regular PGN before delegating.
        self._replacement.replace(Path(source.path))
        return super()._stream_source(source, spool, **kwargs)


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


if __name__ == "__main__":
    unittest.main()
