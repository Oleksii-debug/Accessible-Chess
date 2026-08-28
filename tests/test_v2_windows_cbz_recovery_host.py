from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.cbz_extractor import CbzExtractCode, CbzExtractError, CbzRecoveryReport
from acs.version2_windows_cbz_recovery_host import (
    Version2WindowsCbzRecoveryPreflight,
    WindowsCbzRecoveryStatus,
)


def _report(**overrides: int) -> CbzRecoveryReport:
    values = {
        "scanned_entries": 4,
        "candidates": 3,
        "removed": 1,
        "bytes_removed": 8192,
        "skipped_active": 1,
        "skipped_fresh": 1,
        "skipped_untrusted": 0,
        "skipped_unsafe": 0,
        "skipped_oversized": 0,
        "failed": 0,
    }
    values.update(overrides)
    return CbzRecoveryReport(**values)


class Version2WindowsCbzRecoveryHostTests(unittest.TestCase):
    def test_requires_explicit_absolute_path_authority(self) -> None:
        with self.assertRaises(ValueError):
            Version2WindowsCbzRecoveryPreflight(Path("relative-cache"))
        with self.assertRaises(ValueError):
            Version2WindowsCbzRecoveryPreflight("C:/not-a-Path")  # type: ignore[arg-type]

    def test_real_public_recovery_api_accepts_clean_explicit_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            event = Version2WindowsCbzRecoveryPreflight(root).run_once()
        self.assertEqual(event.status, WindowsCbzRecoveryStatus.CLEAN)
        self.assertEqual(event.scanned_entries, 0)
        self.assertEqual(event.candidates, 0)
        self.assertEqual(event.removed, 0)
        self.assertIsNone(event.error_code)
        self.assertNotIn(str(root), repr(event))

    def test_aggregate_report_maps_without_filesystem_identity(self) -> None:
        private_root = Path(tempfile.gettempdir()).resolve() / "private-user-cache"
        calls: list[Path] = []

        def recoverer(root: Path) -> CbzRecoveryReport:
            calls.append(root)
            return _report()

        event = Version2WindowsCbzRecoveryPreflight(
            private_root,
            recoverer=recoverer,
        ).run_once()
        self.assertEqual(calls, [private_root])
        self.assertEqual(event.status, WindowsCbzRecoveryStatus.RECOVERED)
        self.assertEqual(event.removed, 1)
        self.assertEqual(event.bytes_removed, 8192)
        self.assertEqual(event.skipped_active, 1)
        self.assertEqual(event.skipped_fresh, 1)
        self.assertNotIn(str(private_root), repr(event))

    def test_failed_deletions_are_not_misreported_as_complete(self) -> None:
        root = Path(tempfile.gettempdir()).resolve()
        event = Version2WindowsCbzRecoveryPreflight(
            root,
            recoverer=lambda _root: _report(removed=1, failed=1),
        ).run_once()
        self.assertEqual(event.status, WindowsCbzRecoveryStatus.RECOVERY_INCOMPLETE)
        self.assertEqual(event.removed, 1)
        self.assertEqual(event.failed, 1)

    def test_typed_backend_error_preserves_only_stable_code(self) -> None:
        root = Path(tempfile.gettempdir()).resolve() / "secret-parent"

        def recoverer(_root: Path) -> CbzRecoveryReport:
            raise CbzExtractError(
                f"private path leaked here: {root}",
                code=CbzExtractCode.RECOVERY_ROOT_INVALID,
            )

        event = Version2WindowsCbzRecoveryPreflight(
            root,
            recoverer=recoverer,
        ).run_once()
        self.assertEqual(event.status, WindowsCbzRecoveryStatus.FAILED)
        self.assertEqual(event.error_code, "recovery_root_invalid")
        self.assertNotIn(str(root), repr(event))
        self.assertNotIn("private path", repr(event))

    def test_unexpected_exception_is_redacted(self) -> None:
        root = Path(tempfile.gettempdir()).resolve() / "top-secret"

        def recoverer(_root: Path) -> CbzRecoveryReport:
            raise RuntimeError(f"traceback provider failure at {root}")

        event = Version2WindowsCbzRecoveryPreflight(
            root,
            recoverer=recoverer,
        ).run_once()
        self.assertEqual(event.status, WindowsCbzRecoveryStatus.FAILED)
        self.assertEqual(event.error_code, "internal_error")
        self.assertNotIn(str(root), repr(event))
        self.assertNotIn("traceback", repr(event).lower())
        self.assertNotIn("provider", repr(event).lower())

    def test_invalid_service_report_fails_closed(self) -> None:
        root = Path(tempfile.gettempdir()).resolve()
        event = Version2WindowsCbzRecoveryPreflight(
            root,
            recoverer=lambda _root: _report(scanned_entries=1, candidates=2),
        ).run_once()
        self.assertEqual(event.status, WindowsCbzRecoveryStatus.FAILED)
        self.assertEqual(event.error_code, "internal_error")
        self.assertEqual(event.scanned_entries, 0)

    def test_repeated_call_returns_cached_result_without_second_cleanup(self) -> None:
        root = Path(tempfile.gettempdir()).resolve()
        calls = 0

        def recoverer(_root: Path) -> CbzRecoveryReport:
            nonlocal calls
            calls += 1
            return _report(removed=0, bytes_removed=0, candidates=0, scanned_entries=0,
                           skipped_active=0, skipped_fresh=0)

        preflight = Version2WindowsCbzRecoveryPreflight(root, recoverer=recoverer)
        first = preflight.run_once()
        second = preflight.run_once()
        self.assertIs(first, second)
        self.assertEqual(calls, 1)
        self.assertEqual(first.status, WindowsCbzRecoveryStatus.CLEAN)


if __name__ == "__main__":
    unittest.main()
