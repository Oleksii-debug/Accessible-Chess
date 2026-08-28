from __future__ import annotations

"""Trusted Windows startup seam for bounded CBZ crash-residue recovery.

This module intentionally does not implement CBZ extraction, password handling,
format decoding, or recovery semantics.  It adapts the already-qualified
``recover_stale_cbz_workspaces`` service to a small, path-free host result that
can be consumed by a future Version 2 Windows composition root.

The adapter is synchronous by design and is intended for the trusted pre-UI
startup phase only.  It is never a browser/WebView action and never discovers a
system temporary directory on its own; the application composition must supply
an explicit absolute recovery root.

CBZ semantic support remains outside this module and remains BLOCKED until the
separate real-world acceptance requirements are satisfied.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import threading
from typing import Callable

from .cbz_extractor import (
    CbzExtractError,
    CbzRecoveryReport,
    recover_stale_cbz_workspaces,
)


class WindowsCbzRecoveryStatus(str, Enum):
    CLEAN = "clean"
    RECOVERED = "recovered"
    RECOVERY_INCOMPLETE = "recovery_incomplete"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class WindowsCbzRecoveryEvent:
    status: WindowsCbzRecoveryStatus
    scanned_entries: int = 0
    candidates: int = 0
    removed: int = 0
    bytes_removed: int = 0
    skipped_active: int = 0
    skipped_fresh: int = 0
    skipped_untrusted: int = 0
    skipped_unsafe: int = 0
    skipped_oversized: int = 0
    failed: int = 0
    error_code: str | None = None


RecoveryCallable = Callable[[Path], CbzRecoveryReport]


def _validated_report(report: object) -> CbzRecoveryReport:
    if type(report) is not CbzRecoveryReport:
        raise TypeError("CBZ recovery service returned an invalid report")

    values = (
        report.scanned_entries,
        report.candidates,
        report.removed,
        report.bytes_removed,
        report.skipped_active,
        report.skipped_fresh,
        report.skipped_untrusted,
        report.skipped_unsafe,
        report.skipped_oversized,
        report.failed,
    )
    if any(type(value) is not int or value < 0 for value in values):
        raise ValueError("CBZ recovery service returned invalid aggregate counts")
    if report.candidates > report.scanned_entries or report.removed > report.candidates:
        raise ValueError("CBZ recovery service returned inconsistent aggregate counts")
    return report


def _event_from_report(report: CbzRecoveryReport) -> WindowsCbzRecoveryEvent:
    report = _validated_report(report)
    if report.failed:
        status = WindowsCbzRecoveryStatus.RECOVERY_INCOMPLETE
    elif report.removed:
        status = WindowsCbzRecoveryStatus.RECOVERED
    else:
        status = WindowsCbzRecoveryStatus.CLEAN
    return WindowsCbzRecoveryEvent(
        status=status,
        scanned_entries=report.scanned_entries,
        candidates=report.candidates,
        removed=report.removed,
        bytes_removed=report.bytes_removed,
        skipped_active=report.skipped_active,
        skipped_fresh=report.skipped_fresh,
        skipped_untrusted=report.skipped_untrusted,
        skipped_unsafe=report.skipped_unsafe,
        skipped_oversized=report.skipped_oversized,
        failed=report.failed,
    )


class Version2WindowsCbzRecoveryPreflight:
    """One-shot, trusted pre-UI adapter over canonical CBZ workspace recovery.

    ``recovery_root`` is deliberately required to be an explicit absolute
    ``Path`` supplied by application composition.  No browser payload, current
    working directory, environment variable, or implicit OS temp location is
    accepted as authority here.

    A single instance invokes the recovery service at most once, including when
    multiple startup callers race. Repeated callers receive the same cached
    path-free event and cannot trigger repeated filesystem cleanup accidentally.
    """

    def __init__(
        self,
        recovery_root: Path,
        *,
        recoverer: RecoveryCallable = recover_stale_cbz_workspaces,
    ) -> None:
        if not isinstance(recovery_root, Path) or not recovery_root.is_absolute():
            raise ValueError("CBZ recovery root must be an explicit absolute Path")
        if not callable(recoverer):
            raise TypeError("CBZ recovery service must be callable")
        self._recovery_root = recovery_root
        self._recoverer = recoverer
        self._result: WindowsCbzRecoveryEvent | None = None
        self._run_lock = threading.Lock()

    def run_once(self) -> WindowsCbzRecoveryEvent:
        with self._run_lock:
            if self._result is not None:
                return self._result

            try:
                report = self._recoverer(self._recovery_root)
                result = _event_from_report(report)
            except CbzExtractError as exc:
                result = WindowsCbzRecoveryEvent(
                    status=WindowsCbzRecoveryStatus.FAILED,
                    error_code=exc.code.value,
                )
            except Exception:
                # Never surface raw filesystem/provider exception text through
                # the host result. Diagnostic ownership remains outside
                # NVDA/WebView.
                result = WindowsCbzRecoveryEvent(
                    status=WindowsCbzRecoveryStatus.FAILED,
                    error_code="internal_error",
                )

            self._result = result
            return result
