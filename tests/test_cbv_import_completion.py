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


class CbvImportCompletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "archive.cbv"
        self.source.write_bytes(b"0123456789")
        self.uncbv = self.root / "uncbv"
        self.uncbv.write_bytes(b"pinned-uncbv")
        self.uncbv_sha = sha256(self.uncbv.read_bytes()).hexdigest()
        self.output = self.root / "output"
        self.output.mkdir()

    def _config(self, **values) -> ExternalCbvExtractorConfig:
        options = {
            "timeout_seconds": 3,
            "max_expansion_ratio": 1024,
        }
        options.update(values)
        return ExternalCbvExtractorConfig(
            self.uncbv,
            expected_backend_sha256=self.uncbv_sha,
            **options,
        )

    def test_expansion_ratio_is_a_second_limit_beside_absolute_bytes(self) -> None:
        config = self._config(max_expansion_ratio=2, max_extracted_bytes=1024 * 1024)
        observed_extract_limit: list[int] = []

        def runner(_executable, arguments, run_config, *, cwd, monitor_directory=None):
            if arguments[0] == "list":
                return b"archive.cbh\n"
            observed_extract_limit.append(run_config.max_extracted_bytes)
            Path(cwd, "archive.cbh").write_bytes(b"x" * 21)
            return b""

        with mock.patch("acs.cbv_extractor._run_uncbv", side_effect=runner):
            with self.assertRaises(CbvExtractError) as caught:
                extract_cbv_external(self.source, self.output, config)

        self.assertEqual(caught.exception.code, CbvExtractCode.RESOURCE_LIMIT)
        self.assertEqual(observed_extract_limit, [20])

    def test_expansion_ratio_configuration_rejects_bool_and_zero(self) -> None:
        for value in (True, 0):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self._config(max_expansion_ratio=value)

    def test_cancel_before_backend_start_is_fail_closed(self) -> None:
        with mock.patch("acs.cbv_extractor._run_uncbv") as runner:
            with self.assertRaises(CbvExtractError) as caught:
                extract_cbv_external(
                    self.source,
                    self.output,
                    self._config(),
                    cancel_check=lambda: True,
                )
        self.assertEqual(caught.exception.code, CbvExtractCode.CANCELLED)
        runner.assert_not_called()

    def test_midprocess_cancel_kills_real_child_process(self) -> None:
        calls = 0

        def cancelled() -> bool:
            nonlocal calls
            calls += 1
            return calls >= 3

        started = time.monotonic()
        with self.assertRaises(CbvExtractError) as caught:
            _run_uncbv(
                Path(sys.executable),
                ["-c", "import time; time.sleep(30)"],
                self._config(timeout_seconds=10),
                cwd=self.root,
                cancel_check=cancelled,
            )
        elapsed = time.monotonic() - started

        self.assertEqual(caught.exception.code, CbvExtractCode.CANCELLED)
        self.assertLess(elapsed, 5.0)
        self.assertGreaterEqual(calls, 3)

    def test_library_maps_extractor_cancel_to_canonical_import_cancel(self) -> None:
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
            self._config(),
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

        self.assertIs(extractor.call_args.kwargs["cancel_check"], cancel_check)
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
            self._config(),
        )
        real_temporary_directory = tempfile.TemporaryDirectory
        workspaces: list[Path] = []

        def temporary_directory(*, prefix: str):
            context = real_temporary_directory(prefix=prefix, dir=self.root)
            workspaces.append(Path(context.name))
            return context

        def fail_after_partial_output(_source, output, _config, **_kwargs):
            Path(output, "partial.cbh").write_bytes(b"proprietary partial data")
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
