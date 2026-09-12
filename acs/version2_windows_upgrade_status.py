from __future__ import annotations

"""Windows/NVDA-safe status adapter for the canonical V1 -> V2 upgrade.

This module does not migrate data.  It runs the existing
``Version2UpgradeCoordinator`` away from the UI thread and projects only bounded
semantic status.  Local paths, backup/journal names, upgrade identifiers and raw
exception text never cross this presentation boundary.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
import logging
import threading
from typing import Any

from .version2_upgrade import (
    Version2UpgradeBusy,
    Version2UpgradeCoordinator,
    Version2UpgradeError,
    Version2UpgradeRecoveryError,
    Version2UpgradeReport,
)


_LOG = logging.getLogger(__name__)


class UpgradeUiEventKind(str, Enum):
    STARTED = "started"
    PHASE = "phase"
    COMPLETED = "completed"
    FAILED = "failed"


class UpgradeUiPhase(str, Enum):
    BACKUP_READY = "backup_ready"
    MIGRATING = "migrating"
    SETTINGS_UPDATED = "settings_updated"
    LIBRARY_UPDATED = "library_updated"
    VERIFYING = "verifying"
    COMMITTED = "committed"
    RESTORED = "restored"


class UpgradeUiStatus(str, Enum):
    RUNNING = "running"
    CURRENT = "current"
    UPGRADED = "upgraded"
    FAILED = "failed"


_PHASES = {
    "prepared": UpgradeUiPhase.BACKUP_READY,
    "migrating": UpgradeUiPhase.MIGRATING,
    "settings-migrated": UpgradeUiPhase.SETTINGS_UPDATED,
    "library-migrated": UpgradeUiPhase.LIBRARY_UPDATED,
    "verifying": UpgradeUiPhase.VERIFYING,
    "committed": UpgradeUiPhase.COMMITTED,
    "rolled_back": UpgradeUiPhase.RESTORED,
}


@dataclass(frozen=True, slots=True)
class UpgradeUiEvent:
    kind: UpgradeUiEventKind
    status: UpgradeUiStatus
    phase: UpgradeUiPhase | None = None
    settings_migrated: bool = False
    library_migrated: bool = False
    preserved_files: int = 0
    target_settings_schema: int | None = None
    target_acsdb_schema: int | None = None
    recovered_interrupted_upgrade: bool = False
    focus_target: str = "upgrade-status"
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, UpgradeUiEventKind):
            raise TypeError("kind must be UpgradeUiEventKind")
        if not isinstance(self.status, UpgradeUiStatus):
            raise TypeError("status must be UpgradeUiStatus")
        if self.phase is not None and not isinstance(self.phase, UpgradeUiPhase):
            raise TypeError("phase must be UpgradeUiPhase or None")
        if type(self.settings_migrated) is not bool or type(self.library_migrated) is not bool:
            raise TypeError("migration flags must be bool")
        if type(self.preserved_files) is not int or self.preserved_files < 0:
            raise ValueError("preserved_files must be a non-negative integer")
        for value, label in (
            (self.target_settings_schema, "target_settings_schema"),
            (self.target_acsdb_schema, "target_acsdb_schema"),
        ):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{label} must be a non-negative integer or None")
        if type(self.recovered_interrupted_upgrade) is not bool:
            raise TypeError("recovered_interrupted_upgrade must be bool")
        if not isinstance(self.focus_target, str) or not self.focus_target:
            raise ValueError("focus_target must be non-empty text")
        if self.error_code is not None and (
            not isinstance(self.error_code, str) or not self.error_code
        ):
            raise ValueError("error_code must be non-empty text or None")


UpgradeCoordinatorFactory = Callable[[Callable[[str], None]], Version2UpgradeCoordinator]
UpgradeEventSink = Callable[[UpgradeUiEvent], Any]
UiPoster = Callable[[Callable[[], None]], Any]


class Version2WindowsUpgradeStatusRunner:
    """Execute the canonical upgrade once while keeping UI presentation responsive.

    ``post_to_ui`` is the only cross-thread presentation port.  A WinForms
    composition can map it to ``Control.BeginInvoke``; tests may supply a
    deterministic queue.  No cancellation method is exposed because the
    canonical upgrade contract has no safe cooperative-cancellation primitive.
    """

    def __init__(
        self,
        coordinator_factory: UpgradeCoordinatorFactory,
        *,
        event_sink: UpgradeEventSink,
        post_to_ui: UiPoster,
    ) -> None:
        if not callable(coordinator_factory):
            raise TypeError("coordinator_factory must be callable")
        if not callable(event_sink):
            raise TypeError("event_sink must be callable")
        if not callable(post_to_ui):
            raise TypeError("post_to_ui must be callable")
        self._coordinator_factory = coordinator_factory
        self._event_sink = event_sink
        self._post_to_ui = post_to_ui
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._done = threading.Event()
        self._result: Version2UpgradeReport | None = None
        self._error_code: str | None = None

    @property
    def running(self) -> bool:
        with self._lock:
            worker = self._worker
            return worker is not None and worker.is_alive()

    @property
    def result(self) -> Version2UpgradeReport | None:
        with self._lock:
            return self._result

    @property
    def error_code(self) -> str | None:
        with self._lock:
            return self._error_code

    def _deliver(self, event: UpgradeUiEvent) -> None:
        def invoke() -> None:
            try:
                self._event_sink(event)
            except Exception:
                _LOG.warning("Version 2 upgrade status observer failed")

        try:
            self._post_to_ui(invoke)
        except Exception:
            _LOG.warning("Version 2 upgrade UI posting failed")

    def _phase_hook(self, phase: str) -> None:
        mapped = _PHASES.get(phase)
        if mapped is None:
            _LOG.warning("Version 2 upgrade emitted an unrecognized phase")
            return
        self._deliver(
            UpgradeUiEvent(
                UpgradeUiEventKind.PHASE,
                UpgradeUiStatus.RUNNING,
                phase=mapped,
            )
        )

    @staticmethod
    def _completion_event(report: Version2UpgradeReport) -> UpgradeUiEvent:
        if not isinstance(report, Version2UpgradeReport):
            raise TypeError("canonical upgrade report is invalid")
        if report.status == "already_current":
            status = UpgradeUiStatus.CURRENT
        elif report.status == "upgraded":
            status = UpgradeUiStatus.UPGRADED
        else:
            raise ValueError("canonical upgrade report status is unsupported")
        return UpgradeUiEvent(
            UpgradeUiEventKind.COMPLETED,
            status,
            settings_migrated=report.settings_migrated,
            library_migrated=report.library_migrated,
            preserved_files=report.preserved_files,
            target_settings_schema=report.target_settings_schema,
            target_acsdb_schema=report.target_acsdb_schema,
            recovered_interrupted_upgrade=report.recovered_interrupted_upgrade,
            focus_target="app-root",
        )

    @staticmethod
    def _failure_event(error_code: str) -> UpgradeUiEvent:
        return UpgradeUiEvent(
            UpgradeUiEventKind.FAILED,
            UpgradeUiStatus.FAILED,
            focus_target="upgrade-status",
            error_code=error_code,
        )

    def start(self) -> bool:
        with self._lock:
            if self._worker is not None:
                return False
            self._done.clear()
            self._result = None
            self._error_code = None
            worker = threading.Thread(
                target=self._run,
                name="AccessibleChess-V2-Upgrade",
                daemon=False,
            )
            self._worker = worker
        self._deliver(
            UpgradeUiEvent(
                UpgradeUiEventKind.STARTED,
                UpgradeUiStatus.RUNNING,
            )
        )
        worker.start()
        return True

    def _run(self) -> None:
        try:
            coordinator = self._coordinator_factory(self._phase_hook)
            if not isinstance(coordinator, Version2UpgradeCoordinator):
                raise TypeError("coordinator_factory returned an invalid coordinator")
            report = coordinator.run()
            event = self._completion_event(report)
            with self._lock:
                self._result = report
            self._deliver(event)
        except Version2UpgradeBusy:
            with self._lock:
                self._error_code = "UPGRADE_BUSY"
            self._deliver(self._failure_event("UPGRADE_BUSY"))
        except Version2UpgradeRecoveryError:
            with self._lock:
                self._error_code = "UPGRADE_RECOVERY_FAILED"
            self._deliver(self._failure_event("UPGRADE_RECOVERY_FAILED"))
        except Version2UpgradeError:
            with self._lock:
                self._error_code = "UPGRADE_FAILED"
            self._deliver(self._failure_event("UPGRADE_FAILED"))
        except Exception:
            with self._lock:
                self._error_code = "UPGRADE_UNAVAILABLE"
            self._deliver(self._failure_event("UPGRADE_UNAVAILABLE"))
        finally:
            self._done.set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)

    def join(self, timeout: float | None = None) -> bool:
        with self._lock:
            worker = self._worker
        if worker is None:
            return True
        worker.join(timeout)
        return not worker.is_alive()


__all__ = [
    "UpgradeUiEvent",
    "UpgradeUiEventKind",
    "UpgradeUiPhase",
    "UpgradeUiStatus",
    "Version2WindowsUpgradeStatusRunner",
]
