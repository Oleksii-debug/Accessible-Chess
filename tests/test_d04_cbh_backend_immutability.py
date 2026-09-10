from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

import acs.chessbase_library_import as chessbase_library_import
from acs.chessbase_decoder import (
    ChessBaseDecodeCode,
    ChessBaseDecodeError,
    ExternalChessBaseDecoderConfig,
)
from acs.import_contract import SourceFingerprint, fingerprint as canonical_fingerprint
from acs.chessbase_integrity import capture_integrity_snapshot
from acs.chessbase_library_import import ChessBaseLibraryImportService


class D04ChessBaseBackendImmutabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="d04-cbh-backend-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "Fixture.cbh"
        self.source.write_bytes(b"CBH fixture bytes")
        self.backend = self.root / "libcbh-bridge"
        self.trusted_backend_bytes = b"trusted decoder bytes"
        self.backend.write_bytes(self.trusted_backend_bytes)

        service = object.__new__(ChessBaseLibraryImportService)
        service._decoder_config = ExternalChessBaseDecoderConfig(self.backend)
        service._cbv_extractor_config = None
        service._library = mock.Mock()
        service._library.import_games.return_value = SimpleNamespace(
            warning_count=0,
            game_count=1,
        )
        self.service = service

    def _decoded(self, source_path: str | Path):
        return SimpleNamespace(
            source=capture_integrity_snapshot(source_path),
            backend_name="libcbh",
            backend_commit="1" * 40,
            games=(object(),),
            warnings=(),
        )

    def _good_decoder(self, source_path, _config):
        return self._decoded(source_path)

    def _assert_direct_attack_blocks_publication(self, decoder_side_effect) -> None:
        with mock.patch.object(
            chessbase_library_import,
            "decode_chessbase_external",
            side_effect=decoder_side_effect,
        ):
            with self.assertRaises(ChessBaseDecodeError) as caught:
                self.service.import_database(self.source)
        self.assertEqual(caught.exception.code, ChessBaseDecodeCode.BACKEND_INVALID)
        self.assertNotIn(str(self.backend.parent), str(caught.exception))
        self.service._library.import_games.assert_not_called()

    def _prepare_cbv(self):
        cbv = self.root / "Fixture.cbv"
        cbv.write_bytes(b"CBV fixture bytes")
        source = canonical_fingerprint(cbv)
        self.service._cbv_extractor_config = object()

        def extract(_source_path, output_directory, _config, **_kwargs):
            primary = Path(output_directory) / "FromArchive.cbh"
            primary.write_bytes(b"CBH extracted fixture bytes")
            return SimpleNamespace(
                source=source,
                primary_path=primary,
                entry_count=1,
                extracted_bytes=primary.stat().st_size,
                backend_name="uncbv",
                backend_sha256="2" * 64,
            )

        return cbv, extract

    def test_unchanged_backend_allows_library_publication_without_commit_pin(self) -> None:
        self.assertIsNone(self.service._decoder_config.expected_backend_commit)
        with mock.patch.object(
            chessbase_library_import,
            "decode_chessbase_external",
            side_effect=self._good_decoder,
        ) as decoder:
            report = self.service.import_database(self.source)

        decoder.assert_called_once()
        executed_config = decoder.call_args.args[1]
        self.assertEqual(Path(executed_config.executable), self.backend.resolve())
        self.assertEqual(report.imported_game_count, 1)
        self.service._library.import_games.assert_called_once()

    def test_backend_deletion_discards_output_before_library_publication(self) -> None:
        def delete_backend(source_path, _config):
            decoded = self._decoded(source_path)
            self.backend.unlink()
            return decoded

        self._assert_direct_attack_blocks_publication(delete_backend)

    def test_backend_replacement_discards_output_before_library_publication(self) -> None:
        def replace_backend(source_path, _config):
            decoded = self._decoded(source_path)
            replacement = self.root / "replacement-backend"
            replacement.write_bytes(b"foreign decoder replacement")
            os.replace(replacement, self.backend)
            return decoded

        self._assert_direct_attack_blocks_publication(replace_backend)

    def test_same_size_backend_mutation_discards_output_before_library_publication(self) -> None:
        def mutate_same_size(source_path, _config):
            decoded = self._decoded(source_path)
            self.backend.write_bytes(b"X" * len(self.trusted_backend_bytes))
            self.assertEqual(self.backend.stat().st_size, len(self.trusted_backend_bytes))
            return decoded

        self._assert_direct_attack_blocks_publication(mutate_same_size)

    def test_mutation_immediately_after_fingerprint_is_rejected(self) -> None:
        original_capture = chessbase_library_import._capture_decoder_backend

        def capture_then_mutate(config):
            snapshot = original_capture(config)
            self.backend.write_bytes(b"Y" * len(self.trusted_backend_bytes))
            return snapshot

        with mock.patch.object(
            chessbase_library_import,
            "_capture_decoder_backend",
            side_effect=capture_then_mutate,
        ), mock.patch.object(
            chessbase_library_import,
            "decode_chessbase_external",
            side_effect=self._good_decoder,
        ):
            with self.assertRaises(ChessBaseDecodeError) as caught:
                self.service.import_database(self.source)

        self.assertEqual(caught.exception.code, ChessBaseDecodeCode.BACKEND_INVALID)
        self.service._library.import_games.assert_not_called()

    def test_mutation_during_decode_is_rejected(self) -> None:
        def mutate_during_decode(source_path, _config):
            decoded = self._decoded(source_path)
            self.backend.write_bytes(b"Z" * len(self.trusted_backend_bytes))
            return decoded

        self._assert_direct_attack_blocks_publication(mutate_during_decode)

    def test_configured_alias_rebind_is_rejected_even_with_identical_bytes(self) -> None:
        alias = self.root / "libcbh-alias"
        os.link(self.backend, alias)
        self.service._decoder_config = ExternalChessBaseDecoderConfig(alias)

        def canonicalize_alias(path):
            observed = canonical_fingerprint(path)
            submitted = Path(os.path.abspath(os.fspath(path)))
            alias_absolute = Path(os.path.abspath(os.fspath(alias)))
            if submitted == alias_absolute:
                return SourceFingerprint(
                    path=str(self.backend.resolve()),
                    size=observed.size,
                    sha256=observed.sha256,
                    suffix=observed.suffix,
                )
            return observed

        def rebind_alias(source_path, config):
            self.assertEqual(Path(config.executable), self.backend.resolve())
            decoded = self._decoded(source_path)
            replacement = self.root / "alias-replacement"
            replacement.write_bytes(self.trusted_backend_bytes)
            os.replace(replacement, alias)
            return decoded

        with mock.patch.object(
            chessbase_library_import,
            "fingerprint",
            side_effect=canonicalize_alias,
        ), mock.patch.object(
            chessbase_library_import,
            "decode_chessbase_external",
            side_effect=rebind_alias,
        ):
            with self.assertRaises(ChessBaseDecodeError) as caught:
                self.service.import_database(self.source)

        self.assertEqual(caught.exception.code, ChessBaseDecodeCode.BACKEND_INVALID)
        self.service._library.import_games.assert_not_called()

    def test_direct_cbh_and_cbv_to_cbh_share_one_backend_integrity_wrapper(self) -> None:
        cbv, extract = self._prepare_cbv()
        original_wrapper = self.service._decode_with_immutable_backend

        with mock.patch.object(
            self.service,
            "_decode_with_immutable_backend",
            wraps=original_wrapper,
        ) as wrapper, mock.patch.object(
            chessbase_library_import,
            "decode_chessbase_external",
            side_effect=self._good_decoder,
        ), mock.patch.object(
            chessbase_library_import,
            "extract_cbv_external",
            side_effect=extract,
        ):
            direct = self.service._decode_source(self.source)
            archived = self.service._decode_source(cbv)

        self.assertEqual(wrapper.call_count, 2)
        self.assertEqual(wrapper.call_args_list[0].args[0], self.source)
        self.assertEqual(wrapper.call_args_list[1].args[0].suffix.lower(), ".cbh")
        self.assertEqual(direct[3], "cbh")
        self.assertEqual(archived[3], "cbv")

    def test_cbv_to_cbh_backend_mutation_blocks_library_publication(self) -> None:
        cbv, extract = self._prepare_cbv()

        def mutate_backend(source_path, _config):
            decoded = self._decoded(source_path)
            self.backend.write_bytes(b"Q" * len(self.trusted_backend_bytes))
            return decoded

        with mock.patch.object(
            chessbase_library_import,
            "extract_cbv_external",
            side_effect=extract,
        ), mock.patch.object(
            chessbase_library_import,
            "decode_chessbase_external",
            side_effect=mutate_backend,
        ):
            with self.assertRaises(ChessBaseDecodeError) as caught:
                self.service.import_database(cbv)

        self.assertEqual(caught.exception.code, ChessBaseDecodeCode.BACKEND_INVALID)
        self.service._library.import_games.assert_not_called()


if __name__ == "__main__":
    unittest.main()
