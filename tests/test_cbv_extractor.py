from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

from acs.acsdb import AcsDatabase
from acs.cbv_extractor import (
    CbvExtractCode,
    CbvExtractError,
    ExternalCbvExtractorConfig,
    _run_uncbv,
    extract_cbv_external,
)
from acs.chessbase_decoder import ExternalChessBaseDecoderConfig
from acs.chessbase_library_import import ChessBaseLibraryImportService
from acs.library_import_service import LibraryImportCancelledError


BACKEND_COMMIT = "9641c5c3949d8fb210b17dd9aa54455645843696"


class CbvExternalExtractorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "Archive.cbv"
        self.source.write_bytes(b"immutable CBV archive")
        self.backend = self.root / "uncbv"
        self.backend.write_bytes(b"pinned external backend")
        self.backend_sha256 = sha256(self.backend.read_bytes()).hexdigest()
        self.config = ExternalCbvExtractorConfig(
            self.backend,
            expected_backend_sha256=self.backend_sha256,
            timeout_seconds=3,
        )
        self.output = self.root / "output"
        self.output.mkdir()

    def _successful_runner(
        self,
        _executable,
        arguments,
        _config,
        *,
        cwd,
        monitor_directory=None,
    ):
        if arguments[0] == "list":
            return b"nested/Training.cbh\nnested/Training.cbg\nnested/Training.cba\n"
        self.assertEqual(arguments[0], "extract")
        self.assertEqual(Path(cwd), self.output)
        self.assertEqual(Path(monitor_directory), self.output)
        nested = self.output / "nested"
        nested.mkdir()
        (nested / "Training.cbh").write_bytes(b"header")
        (nested / "Training.cbg").write_bytes(b"moves")
        (nested / "Training.cba").write_bytes(b"annotations")
        return b""

    def test_validated_archive_extracts_one_classic_cbh_family(self) -> None:
        with mock.patch(
            "acs.cbv_extractor._run_uncbv",
            side_effect=self._successful_runner,
        ):
            result = extract_cbv_external(self.source, self.output, self.config)

        self.assertEqual(
            result.source.sha256,
            sha256(self.source.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            result.primary_path,
            self.output / "nested" / "Training.cbh",
        )
        self.assertEqual(result.entry_count, 3)
        self.assertEqual(result.extracted_bytes, len(b"headermovesannotations"))
        self.assertEqual(result.backend_name, "uncbv")
        self.assertEqual(result.backend_sha256, self.backend_sha256)

    def test_traversal_absolute_drive_and_case_collisions_fail_before_extraction(
        self,
    ) -> None:
        unsafe_lists = (
            b"../escape.cbh\n",
            b"/absolute.cbh\n",
            b"C:\\private\\database.cbh\n",
            b"same.cbh\nSAME.CBH\n",
            b"folder/../../escape.cbh\n",
        )
        for payload in unsafe_lists:
            with self.subTest(payload=payload):
                with mock.patch(
                    "acs.cbv_extractor._run_uncbv",
                    return_value=payload,
                ) as runner:
                    with self.assertRaises(CbvExtractError) as caught:
                        extract_cbv_external(
                            self.source,
                            self.output,
                            self.config,
                        )
                self.assertEqual(
                    caught.exception.code,
                    CbvExtractCode.INVALID_ENTRY,
                )
                self.assertEqual(runner.call_count, 1)

    def test_output_must_match_prevalidated_entry_inventory_exactly(self) -> None:
        def runner(_executable, arguments, _config, **_kwargs):
            if arguments[0] == "list":
                return b"Archive.cbh\nArchive.cbg\n"
            (self.output / "Archive.cbh").write_bytes(b"header")
            (self.output / "unexpected.cbg").write_bytes(b"unexpected")
            return b""

        with mock.patch("acs.cbv_extractor._run_uncbv", side_effect=runner):
            with self.assertRaises(CbvExtractError) as caught:
                extract_cbv_external(self.source, self.output, self.config)
        self.assertEqual(caught.exception.code, CbvExtractCode.OUTPUT_INVALID)

    def test_exactly_one_cbh_primary_is_required(self) -> None:
        for names in (b"Archive.cbg\n", b"A.cbh\nB.cbh\n"):
            with self.subTest(names=names):

                def runner(_executable, arguments, _config, **_kwargs):
                    if arguments[0] == "list":
                        return names
                    for name in names.decode().splitlines():
                        (self.output / name).write_bytes(b"fixture")
                    return b""

                with mock.patch(
                    "acs.cbv_extractor._run_uncbv",
                    side_effect=runner,
                ):
                    with self.assertRaises(CbvExtractError) as caught:
                        extract_cbv_external(
                            self.source,
                            self.output,
                            self.config,
                        )
                self.assertEqual(
                    caught.exception.code,
                    CbvExtractCode.OUTPUT_INVALID,
                )
                for child in tuple(self.output.iterdir()):
                    child.unlink()

    def test_source_mutation_invalidates_all_extracted_output(self) -> None:
        def runner(_executable, arguments, _config, **_kwargs):
            if arguments[0] == "list":
                return b"Archive.cbh\n"
            (self.output / "Archive.cbh").write_bytes(b"header")
            self.source.write_bytes(b"mutated archive bytes")
            return b""

        with mock.patch("acs.cbv_extractor._run_uncbv", side_effect=runner):
            with self.assertRaises(CbvExtractError) as caught:
                extract_cbv_external(self.source, self.output, self.config)
        self.assertEqual(caught.exception.code, CbvExtractCode.SOURCE_CHANGED)

    def test_backend_mutation_invalidates_all_extracted_output(self) -> None:
        def runner(_executable, arguments, _config, **_kwargs):
            if arguments[0] == "list":
                return b"Archive.cbh\n"
            (self.output / "Archive.cbh").write_bytes(b"header")
            self.backend.write_bytes(b"mutated backend while running")
            return b""

        with mock.patch("acs.cbv_extractor._run_uncbv", side_effect=runner):
            with self.assertRaises(CbvExtractError) as caught:
                extract_cbv_external(self.source, self.output, self.config)
        self.assertEqual(caught.exception.code, CbvExtractCode.BACKEND_INVALID)

    def test_backend_binary_is_sha256_pinned(self) -> None:
        config = ExternalCbvExtractorConfig(
            self.backend,
            expected_backend_sha256="0" * 64,
        )
        with mock.patch("acs.cbv_extractor._run_uncbv") as runner:
            with self.assertRaises(CbvExtractError) as caught:
                extract_cbv_external(self.source, self.output, config)
        self.assertEqual(caught.exception.code, CbvExtractCode.BACKEND_INVALID)
        runner.assert_not_called()

    def test_resource_limits_and_non_cbv_sources_fail_closed(self) -> None:
        too_small = ExternalCbvExtractorConfig(
            self.backend,
            expected_backend_sha256=self.backend_sha256,
            max_source_bytes=1,
        )
        with self.assertRaises(CbvExtractError) as caught:
            extract_cbv_external(self.source, self.output, too_small)
        self.assertEqual(caught.exception.code, CbvExtractCode.RESOURCE_LIMIT)

        other = self.root / "old.cbf"
        other.write_bytes(b"legacy")
        with self.assertRaises(CbvExtractError) as caught:
            extract_cbv_external(other, self.output, self.config)
        self.assertEqual(
            caught.exception.code,
            CbvExtractCode.UNSUPPORTED_SOURCE,
        )

    def test_expansion_ratio_is_independent_of_absolute_byte_limit(self) -> None:
        source_bytes = self.source.stat().st_size
        config = ExternalCbvExtractorConfig(
            self.backend,
            expected_backend_sha256=self.backend_sha256,
            timeout_seconds=3,
            max_extracted_bytes=1024 * 1024,
            max_expansion_ratio=2,
        )
        observed_limits: list[int] = []

        def runner(
            _executable,
            arguments,
            run_config,
            *,
            cwd,
            monitor_directory=None,
        ):
            if arguments[0] == "list":
                return b"Archive.cbh\n"
            observed_limits.append(run_config.max_extracted_bytes)
            Path(cwd, "Archive.cbh").write_bytes(
                b"x" * (source_bytes * 2 + 1)
            )
            return b""

        with mock.patch("acs.cbv_extractor._run_uncbv", side_effect=runner):
            with self.assertRaises(CbvExtractError) as caught:
                extract_cbv_external(self.source, self.output, config)

        self.assertEqual(caught.exception.code, CbvExtractCode.RESOURCE_LIMIT)
        self.assertEqual(observed_limits, [source_bytes * 2])

    def test_expansion_ratio_rejects_bool_and_zero(self) -> None:
        for ratio in (True, 0):
            with self.subTest(ratio=ratio):
                with self.assertRaises(ValueError):
                    ExternalCbvExtractorConfig(
                        self.backend,
                        expected_backend_sha256=self.backend_sha256,
                        max_expansion_ratio=ratio,
                    )

    def test_cancel_before_backend_start_is_fail_closed(self) -> None:
        with mock.patch("acs.cbv_extractor._run_uncbv") as runner:
            with self.assertRaises(CbvExtractError) as caught:
                extract_cbv_external(
                    self.source,
                    self.output,
                    self.config,
                    cancel_check=lambda: True,
                )
        self.assertEqual(caught.exception.code, CbvExtractCode.CANCELLED)
        runner.assert_not_called()

    def test_midprocess_cancel_kills_real_child_process(self) -> None:
        checks = 0

        def cancel_check() -> bool:
            nonlocal checks
            checks += 1
            return checks >= 3

        started = time.monotonic()
        with self.assertRaises(CbvExtractError) as caught:
            _run_uncbv(
                Path(sys.executable),
                ["-c", "import time; time.sleep(30)"],
                self.config,
                cwd=self.root,
                cancel_check=cancel_check,
            )
        elapsed = time.monotonic() - started

        self.assertEqual(caught.exception.code, CbvExtractCode.CANCELLED)
        self.assertGreaterEqual(checks, 3)
        self.assertLess(elapsed, 5.0)

    def test_library_maps_midextract_cancel_to_canonical_cancel(self) -> None:
        database = AcsDatabase(self.root / "cancel.acsdb")
        self.addCleanup(database.close)
        decoder = self.root / "libcbh-json-bridge"
        decoder.write_bytes(b"decoder")
        service = ChessBaseLibraryImportService(
            database,
            ExternalChessBaseDecoderConfig(
                decoder,
                expected_backend_commit=BACKEND_COMMIT,
            ),
            self.config,
        )
        cancel_check = mock.Mock(return_value=False)

        with mock.patch(
            "acs.chessbase_library_import.extract_cbv_external",
            side_effect=CbvExtractError(
                "CBV extraction cancelled",
                code=CbvExtractCode.CANCELLED,
            ),
        ) as extractor:
            with self.assertRaises(LibraryImportCancelledError):
                service.import_database(
                    self.source,
                    cancel_check=cancel_check,
                )

        self.assertIs(
            extractor.call_args.kwargs["cancel_check"],
            cancel_check,
        )
        for table in ("import_attempts", "sources", "games"):
            count = database.conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            self.assertEqual(count, 0, table)

    def test_backend_failure_removes_partial_temporary_family(self) -> None:
        database = AcsDatabase(self.root / "cleanup.acsdb")
        self.addCleanup(database.close)
        decoder = self.root / "libcbh-json-bridge"
        decoder.write_bytes(b"decoder")
        service = ChessBaseLibraryImportService(
            database,
            ExternalChessBaseDecoderConfig(
                decoder,
                expected_backend_commit=BACKEND_COMMIT,
            ),
            self.config,
        )
        real_temporary_directory = tempfile.TemporaryDirectory
        workspaces: list[Path] = []

        def temporary_directory(*, prefix: str):
            context = real_temporary_directory(prefix=prefix, dir=self.root)
            workspaces.append(Path(context.name))
            return context

        def fail_after_partial_output(_source, output, _config, **_kwargs):
            Path(output, "partial.cbh").write_bytes(b"partial proprietary data")
            raise CbvExtractError(
                "backend failed",
                code=CbvExtractCode.BACKEND_FAILED,
            )

        with (
            mock.patch(
                "acs.chessbase_library_import.tempfile.TemporaryDirectory",
                side_effect=temporary_directory,
            ),
            mock.patch(
                "acs.chessbase_library_import.extract_cbv_external",
                side_effect=fail_after_partial_output,
            ),
        ):
            with self.assertRaises(CbvExtractError):
                service.import_database(self.source)

        self.assertEqual(len(workspaces), 1)
        self.assertFalse(workspaces[0].exists())
        for table in ("import_attempts", "sources", "games"):
            count = database.conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            self.assertEqual(count, 0, table)


if __name__ == "__main__":
    unittest.main()
