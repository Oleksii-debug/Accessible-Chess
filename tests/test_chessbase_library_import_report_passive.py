from __future__ import annotations

import unittest

from acs.chessbase_library_import import (
    ChessBaseLibraryImportReport,
    ChessBaseLibraryImportStatus,
)
from acs.library_import_service import LibraryImportResult


def _result(*, warning_count: int = 0) -> LibraryImportResult:
    return LibraryImportResult(
        attempt_id=1,
        source_id=2,
        game_count=2,
        warning_count=warning_count,
        first_game_id=10,
        last_game_id=11,
    )


def _report(**overrides: object) -> ChessBaseLibraryImportReport:
    values: dict[str, object] = {
        "status": ChessBaseLibraryImportStatus.IMPORTED,
        "source_name": "private-source.cbh",
        "source_sha256": "a" * 64,
        "backend_name": "libcbh",
        "backend_commit": "b" * 40,
        "decoded_game_count": 2,
        "warnings": (),
        "library_result": _result(),
        "source_format": "cbh",
        "archive_backend_name": None,
        "archive_backend_sha256": None,
    }
    values.update(overrides)
    return ChessBaseLibraryImportReport(**values)  # type: ignore[arg-type]


class ChessBaseLibraryImportReportPassiveTests(unittest.TestCase):
    def test_valid_imported_and_empty_reports_remain_supported(self) -> None:
        imported = _report()
        empty = _report(
            status=ChessBaseLibraryImportStatus.NO_GAMES,
            decoded_game_count=0,
            library_result=None,
        )

        self.assertEqual(imported.imported_game_count, 2)
        self.assertEqual(imported.warning_count, 0)
        self.assertEqual(empty.imported_game_count, 0)
        self.assertEqual(empty.warning_count, 0)

    def test_derived_report_rejected_before_field_hooks(self) -> None:
        touched: list[str] = []

        class ActiveReport(ChessBaseLibraryImportReport):
            def __getattribute__(self, name: str):
                if name in {
                    "status",
                    "source_name",
                    "decoded_game_count",
                    "warnings",
                    "library_result",
                }:
                    touched.append(name)
                    raise AssertionError("derived report field hook executed")
                return super().__getattribute__(name)

        with self.assertRaisesRegex(
            TypeError,
            "exact passive DTO",
        ):
            ActiveReport(
                status=ChessBaseLibraryImportStatus.IMPORTED,
                source_name="source.cbh",
                source_sha256="a" * 64,
                backend_name="libcbh",
                backend_commit="b" * 40,
                decoded_game_count=2,
                warnings=(),
                library_result=_result(),
            )

        self.assertEqual(touched, [])

    def test_active_decoded_count_rejected_without_numeric_hook(self) -> None:
        touched: list[str] = []

        class ActiveInt(int):
            def __int__(self):
                touched.append("int")
                raise AssertionError("numeric coercion executed")

            def __index__(self):
                touched.append("index")
                raise AssertionError("index coercion executed")

        with self.assertRaisesRegex(TypeError, "decoded_game_count"):
            _report(decoded_game_count=ActiveInt(2))

        self.assertEqual(touched, [])

    def test_import_report_semantics_fail_closed(self) -> None:
        cases = (
            {
                "status": ChessBaseLibraryImportStatus.NO_GAMES,
                "decoded_game_count": 2,
                "library_result": _result(),
            },
            {
                "status": ChessBaseLibraryImportStatus.IMPORTED,
                "decoded_game_count": 0,
                "library_result": None,
            },
            {
                "status": ChessBaseLibraryImportStatus.IMPORTED,
                "decoded_game_count": 3,
                "library_result": _result(),
            },
            {
                "status": ChessBaseLibraryImportStatus.IMPORTED_WITH_WARNINGS,
                "decoded_game_count": 2,
                "library_result": _result(warning_count=0),
            },
            {
                "status": ChessBaseLibraryImportStatus.IMPORTED,
                "decoded_game_count": 2,
                "library_result": _result(warning_count=1),
            },
        )

        for overrides in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaises((TypeError, ValueError)):
                    _report(**overrides)

    def test_report_rejects_noncanonical_container_and_library_result(self) -> None:
        with self.assertRaisesRegex(TypeError, "warnings"):
            _report(warnings=[])

        class DerivedResult(LibraryImportResult):
            pass

        derived = DerivedResult(
            attempt_id=1,
            source_id=2,
            game_count=2,
            warning_count=0,
            first_game_id=10,
            last_game_id=11,
        )
        with self.assertRaisesRegex(TypeError, "exact LibraryImportResult"):
            _report(library_result=derived)


if __name__ == "__main__":
    unittest.main()
