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

    def test_same_size_backend_mutation_is_rejected_by_hash_not_only_size(self) -> None:
        original = self.backend.read_bytes()
        replacement = b"altered decoder bytes"
        self.assertEqual(len(replacement), len(original))

        def mutate_backend(*_args, **_kwargs):
            self.backend.write_bytes(replacement)
            return self._decoded()

        with mock.patch(
            "acs.chessbase_library_import.decode_chessbase_external",
            side_effect=mutate_backend,
        ):
            with self.assertRaises(ChessBaseDecodeError) as caught:
                self.service._decode_source(self.source)

        self.assertEqual(caught.exception.code, ChessBaseDecodeCode.BACKEND_INVALID)
        self.assertNotIn(str(self.backend.parent), str(caught.exception))

    def test_backend_replaced_by_directory_discards_decoder_output(self) -> None:
        def replace_backend(*_args, **_kwargs):
            self.backend.unlink()
            self.backend.mkdir()
            return self._decoded()

        with mock.patch(
            "acs.chessbase_library_import.decode_chessbase_external",
            side_effect=replace_backend,
        ):
            with self.assertRaises(ChessBaseDecodeError) as caught:
                self.service._decode_source(self.source)

        self.assertEqual(caught.exception.code, ChessBaseDecodeCode.BACKEND_INVALID)
        self.assertNotIn(str(self.backend.parent), str(caught.exception))

    def test_control_checkpoint_is_forwarded_and_polled_around_backend_hashing(self) -> None:
        checkpoints = []
        count_at_decode = []

        def checkpoint():
            checkpoints.append("checked")

        def decoded_with_control(_path, _config, *, control_checkpoint=None):
            self.assertIs(control_checkpoint, checkpoint)
            count_at_decode.append(len(checkpoints))
            control_checkpoint()
            return self._decoded()

        with mock.patch(
            "acs.chessbase_library_import.decode_chessbase_external",
            side_effect=decoded_with_control,
        ):
            result = self.service._decode_with_immutable_backend(
                self.source,
                control_checkpoint=checkpoint,
            )

        self.assertEqual(result.source, self.snapshot)
        self.assertGreater(count_at_decode[0], 0)
        self.assertGreater(len(checkpoints), count_at_decode[0] + 1)

    def test_cancellation_during_backend_fingerprint_prevents_decoder_start(self) -> None:
        class Cancelled(RuntimeError):
            pass

        def checkpoint():
            raise Cancelled("cancel before decoder")

        with mock.patch(
            "acs.chessbase_library_import.decode_chessbase_external",
        ) as decoder:
            with self.assertRaisesRegex(Cancelled, "cancel before decoder"):
                self.service._decode_with_immutable_backend(
                    self.source,
                    control_checkpoint=checkpoint,
                )

        decoder.assert_not_called()

    def test_cancellation_after_decode_discards_output_during_backend_recheck(self) -> None:
        class Cancelled(RuntimeError):
            pass

        state = {"decoded": False}

        def checkpoint():
            if state["decoded"]:
                raise Cancelled("cancel after decoder")

        def decoded_with_control(_path, _config, *, control_checkpoint=None):
            self.assertIs(control_checkpoint, checkpoint)
            state["decoded"] = True
            return self._decoded()

        with mock.patch(
            "acs.chessbase_library_import.decode_chessbase_external",
            side_effect=decoded_with_control,
        ):
            with self.assertRaisesRegex(Cancelled, "cancel after decoder"):
                self.service._decode_with_immutable_backend(
                    self.source,
                    control_checkpoint=checkpoint,
                )

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
