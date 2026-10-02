from __future__ import annotations

"""Post-#645 final-product composition with Education mutation and starter content.

The accepted #645 release adapter uses import-time late binding because it is a
standalone post-freeze composition root. This stacked child is also exercised in
large in-process regression suites, so importing it must not permanently replace
any narrower Version 2 release owner. Apply every #645 release seam only while
this child is composing/running, then restore the exact previous objects.
"""

from contextlib import contextmanager
from typing import Any, Callable, Iterator

from . import version2_final_release as _final_release
from . import version2_release_app as _release_app
from . import version2_release_ui as _release_ui
from .full_product_ui_shell import UILanguage
from .version2_final_product_profile import (
    FINAL_PRODUCT_ACTION_IDS,
    FinalProductNativeMenuController,
)
from .version2_packaged_starter_application import Version2PackagedStarterApplication


def final_product_resource_sources() -> tuple[tuple[str, str], ...]:
    """Return the canonical final-product resources under the #645 label contract."""

    sources = _final_release.final_product_resource_sources()
    return tuple(
        (
            "P0 accessibility runtime"
            if label == "P0 event-aware accessibility runtime"
            else label,
            source,
        )
        for label, source in sources
    )

def _composed_language_sync(
    base_sync: Callable[[Any, UILanguage], None],
) -> Callable[[Any, UILanguage], None]:
    def sync(application: Any, language: UILanguage) -> None:
        base_sync(application, language)
        composed_sync = getattr(application, "sync_composed_surfaces_language", None)
        if callable(composed_sync):
            composed_sync(language)

    return sync


@contextmanager
def _final_product_mutation_bindings() -> Iterator[Callable[[Any, UILanguage], None]]:
    """Temporarily install the complete #645 release profile plus this child app."""

    api_type = _release_ui.Version2ReleaseAccessibleChessAPI
    previous_application = _release_app.Version2Application
    previous_action_ids = _release_ui.VERSION2_FULL_PRODUCT_ACTION_IDS
    previous_controller = _release_ui.Version2NativeMenuController
    previous_sync_descriptor = api_type.__dict__["_sync_version2_language"]
    previous_sync = getattr(api_type, "_sync_version2_language")
    previous_resources = _release_ui._resource_sources

    _release_app.Version2Application = Version2PackagedStarterApplication
    _release_ui.VERSION2_FULL_PRODUCT_ACTION_IDS = FINAL_PRODUCT_ACTION_IDS
    _release_ui.Version2NativeMenuController = FinalProductNativeMenuController
    setattr(
        api_type,
        "_sync_version2_language",
        staticmethod(_composed_language_sync(previous_sync)),
    )
    _release_ui._resource_sources = final_product_resource_sources
    try:
        yield previous_sync
    finally:
        _release_ui._resource_sources = previous_resources
        setattr(api_type, "_sync_version2_language", previous_sync_descriptor)
        _release_ui.Version2NativeMenuController = previous_controller
        _release_ui.VERSION2_FULL_PRODUCT_ACTION_IDS = previous_action_ids
        _release_app.Version2Application = previous_application


def _bind_api_language_sync(
    api: Any,
    base_sync: Callable[[Any, UILanguage], None],
) -> None:
    """Keep composed-surface language sync on a returned API without global state."""

    setattr(api, "_sync_version2_language", _composed_language_sync(base_sync))


def create_version2_release_application(*args: Any, **kwargs: Any):
    """Compose through the existing release root without leaking global ownership.

    ``version2_release_app`` defers application construction onto the native UI
    thread when ``defer_ui=True``. In that mode the returned one-shot builder
    reacquires the same bounded bindings at invocation time. The returned API
    receives an instance-local language synchronizer so later language changes do
    not depend on process-global class mutation.
    """

    defer_ui = kwargs.get("defer_ui", False) is True
    with _final_product_mutation_bindings() as base_sync:
        composed = _release_app.create_version2_release_application(*args, **kwargs)
        api = composed[0]
        _bind_api_language_sync(api, base_sync)

    if not defer_ui:
        return composed

    api, application_factory, runtime, native_runtime_factory = composed
    if not callable(application_factory):
        raise TypeError("deferred Version 2 application factory must be callable")

    def build_mutation_application():
        with _final_product_mutation_bindings():
            return application_factory()

    return api, build_mutation_application, runtime, native_runtime_factory


def main() -> None:
    # The existing main() owns the complete synchronous UI lifetime. Keep all
    # final-product seams installed for that lifetime, including the deferred
    # native UI-thread construction, then restore prior process state on exit.
    with _final_product_mutation_bindings():
        _release_app.main()


__all__ = [
    "create_version2_release_application",
    "final_product_resource_sources",
    "main",
]
