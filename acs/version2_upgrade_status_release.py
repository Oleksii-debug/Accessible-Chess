from __future__ import annotations

"""Shipping binding for bounded V1 -> V2 upgrade/recovery status.

The canonical V1 runtime bridge and :class:`Version2UpgradeCoordinator` remain the
only migration authorities.  This module only observes the already-required
pre-writer upgrade, projects its accepted bounded completion DTO, and publishes
that result into the existing Version 2 semantic ``status`` event queue after the
application is constructed on its owning UI thread.

No path, backup/journal name, upgrade identifier, raw exception text, or migration
implementation detail is exposed to the WebView/NVDA surface.
"""

from contextlib import contextmanager
from typing import Any, Iterator

from . import version2_education_mutation_release as _education_release
from . import version2_release_app as _release_app
from . import version2_release_ui as _release_ui
from .full_product_ui_shell import UILanguage
from .version2_upgrade import Version2UpgradeReport
from .version2_windows_upgrade_status import (
    UpgradeUiStatus,
    Version2WindowsUpgradeStatusRunner,
)


def final_product_resource_sources() -> tuple[tuple[str, str], ...]:
    """Keep the accepted final-product resource authority unchanged."""

    return _education_release.final_product_resource_sources()


@contextmanager
def _capture_canonical_upgrade_report(
    reports: list[Version2UpgradeReport],
) -> Iterator[None]:
    """Observe one canonical pre-writer upgrade without creating a second upgrader."""

    if reports:
        raise ValueError("upgrade report sink must start empty")
    previous_prepare = _release_app._prepare_version2_user_data

    def prepare_with_report(*args: Any, **kwargs: Any):
        source_factory = kwargs.pop(
            "coordinator_factory",
            _release_app.Version2UpgradeCoordinator,
        )
        if not callable(source_factory):
            raise TypeError("coordinator_factory must be callable")

        def recording_factory(layout: Any):
            coordinator = source_factory(layout)
            run = getattr(coordinator, "run", None)
            if not callable(run):
                raise TypeError("Version 2 upgrade coordinator must expose run()")

            class _RecordingCoordinator:
                def run(self) -> Version2UpgradeReport:
                    report = run()
                    if not isinstance(report, Version2UpgradeReport):
                        raise TypeError("canonical upgrade report is invalid")
                    if reports:
                        raise RuntimeError("Version 2 startup upgrade ran more than once")
                    reports.append(report)
                    return report

            return _RecordingCoordinator()

        return previous_prepare(
            *args,
            coordinator_factory=recording_factory,
            **kwargs,
        )

    _release_app._prepare_version2_user_data = prepare_with_report
    try:
        yield
    finally:
        _release_app._prepare_version2_user_data = previous_prepare


def _required_report(reports: list[Version2UpgradeReport]) -> Version2UpgradeReport:
    if len(reports) != 1:
        raise RuntimeError("Version 2 startup upgrade status is unavailable")
    return reports[0]


def _status_announcement(status: UpgradeUiStatus, *, recovered: bool, language: UILanguage) -> str:
    english = language is UILanguage.EN
    if recovered:
        return (
            "Version 2 data recovery completed. Data is ready."
            if english
            else "Відновлення даних Version 2 завершено. Дані готові."
        )
    if status is UpgradeUiStatus.UPGRADED:
        return (
            "Version 2 data upgrade completed."
            if english
            else "Оновлення даних до Version 2 завершено."
        )
    if status is UpgradeUiStatus.CURRENT:
        return (
            "Version 2 data is verified and ready."
            if english
            else "Дані Version 2 перевірено та готові."
        )
    raise ValueError("unsupported completed upgrade status")


def _publish_canonical_upgrade_status(application: Any, report: Version2UpgradeReport) -> None:
    """Publish only bounded semantic completion data on the owning UI thread."""

    assert_thread = getattr(application, "_assert_thread", None)
    if not callable(assert_thread):
        raise TypeError("Version 2 application thread authority is unavailable")
    assert_thread()

    shell = getattr(application, "shell", None)
    language = getattr(shell, "language", None)
    if language not in {UILanguage.UA, UILanguage.EN}:
        raise TypeError("Version 2 application language is unavailable")

    # Reuse SAME #426's accepted projection rather than creating another report
    # mapper.  The runner itself is intentionally not started here: shipping
    # recovery must finish before Settings/ACSDB writers open, while the semantic
    # application surface does not exist until after that safety boundary.
    event = Version2WindowsUpgradeStatusRunner._completion_event(report)
    payload = {
        "announcement": _status_announcement(
            event.status,
            recovered=event.recovered_interrupted_upgrade,
            language=language,
        ),
        "upgrade_status": event.status.value,
        "settings_migrated": event.settings_migrated,
        "library_migrated": event.library_migrated,
        "preserved_files": event.preserved_files,
        "recovered_interrupted_upgrade": event.recovered_interrupted_upgrade,
        "focus_target": event.focus_target,
    }
    events = getattr(application, "_events", None)
    append = getattr(events, "append", None)
    if not callable(append):
        raise TypeError("Version 2 semantic event queue is unavailable")
    append({"kind": "status", "payload": payload})


def create_version2_release_application(*args: Any, **kwargs: Any):
    """Compose the real final product and bind its already-run upgrade status."""

    reports: list[Version2UpgradeReport] = []
    with _capture_canonical_upgrade_report(reports):
        composed = _education_release.create_version2_release_application(*args, **kwargs)
    report = _required_report(reports)

    if kwargs.get("defer_ui", False) is not True:
        _publish_canonical_upgrade_status(composed[1], report)
        return composed

    api, application_factory, runtime, native_runtime_factory = composed
    if not callable(application_factory):
        raise TypeError("deferred Version 2 application factory must be callable")

    def build_status_application():
        application = application_factory()
        _publish_canonical_upgrade_status(application, report)
        return application

    return api, build_status_application, runtime, native_runtime_factory


def main() -> None:
    """Run the real final product with its final-product bindings held for UI life."""

    # The Education/final-product composition owns process-global menu/resource
    # bindings for the complete synchronous UI lifetime. Keep that proven lifetime
    # contract while replacing only its create step with the status-aware wrapper.
    with _education_release._final_product_mutation_bindings():
        api, application, runtime, native_runtime_factory = (
            create_version2_release_application(defer_ui=True)
        )
        _release_ui.run_version2_release_window(
            api,
            application,
            runtime,
            file_runtime_factory=native_runtime_factory,
        )


__all__ = [
    "create_version2_release_application",
    "final_product_resource_sources",
    "main",
]
