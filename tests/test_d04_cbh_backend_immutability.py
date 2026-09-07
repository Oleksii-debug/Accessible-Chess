from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from acs.chessbase_decoder import (
    ChessBaseDecodeCode,
    ChessBaseDecodeError,
    ExternalChessBaseDecoderConfig,
)
from acs.chessbase_integrity import capture_integrity_snapshot
from acs.chessbase_library_import import ChessBaseLibraryImportService


class D04ChessBaseBackendImmutabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="d04-cbh-backend-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source = root / "Fixture.cbh"
        self.source.write_bytes(b"CBH fixture bytes")
        self.backend = root / "libcbh-bridge"
        self.backend.write_bytes(b"trusted decoder bytes")
        self.snapshot = capture_integrity_snapshot(self.source)

        service = object.__new__(ChessBaseLibraryImportService)
        service._decoder_config = ExternalChessBaseDecoderConfig(self.backend)
        service._cbv_extractor_config = None
        self.service = service

    def _decoded(self):
        return SimpleNamespace(source=self.snapshot)

    def test_unchanged_backend_allows_cbh_decode_result_to_continue(self) -> None:
        with mock.patch(
            "acs.chessbase_library_import.decode_chessbase_external",
            return_value=self._decoded(),
        ) as decoder:
            result = self.service._decode_source(self.source)
        decoder.assert_called_once()
        self.assertEqual(result[3], "cbh")
        self.assertEqual(result[1], "Fixture.cbh")

    def test_backend_byte_mutation_discards_decoder_output(self) -> None:
        def mutate_backend(*_args, **_kwargs):
            self.backend.write_bytes(b"replacement decoder bytes")
            return self._decoded()

        with mock.patch(
            "acs.chessbase_library_import.decode_chessbase_external",
            side_effect=mutate_backend,
        ):
            with self.assertRaises(ChessBaseDecodeError) as caught:
                self.service._decode_source(self.source)
        self.assertEqual(caught.exception.code, ChessBaseDecodeCode.BACKEND_INVALID)
        self.assertNotIn(str(self.backend.parent), str(caught.exception))

    def test_backend_disappearance_discards_decoder_output(self) -> None:
        def remove_backend(*_args, **_kwargs):
            self.backend.unlink()
            return self._decoded()

        with mock.patch(
            "acs.chessbase_library_import.decode_chessbase_external",
            side_effect=remove_backend,
        ):
            with self.assertRaises(ChessBaseDecodeError) as caught:
                self.service._decode_source(self.source)
        self.assertEqual(caught.exception.code, ChessBaseDecodeCode.BACKEND_INVALID)
        self.assertNotIn(str(self.backend.parent), str(caught.exception))


if __name__ == "__main__":
    unittest.main()
