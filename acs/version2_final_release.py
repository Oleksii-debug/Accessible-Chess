from __future__ import annotations

"""Scoped final-product release composition over the accepted Version 2 root.

The final product needs the wider Teacher/Classes action profile, native menu,
language synchronization, and packaged WebView resources while it is being
composed or run.  Those seams are process-global in the accepted release root,
so importing this module must not permanently replace narrower Version 2 owners:
large in-process regression suites and tooling legitimately use both profiles.
"""

from contextlib import contextmanager
from types import MethodType
from typing import Any, Callable, Iterator

from . import version2_release_app as _release_app
from . import version2_release_ui as _release_ui
from .full_product_ui_shell import UILanguage
from .media_accessibility import MediaAccessibilityBridge
from .media_application import MediaApplicationService
from .version2_final_product_application import Version2FinalProductApplication
from .version2_final_product_profile import (
    FINAL_PRODUCT_ACTION_IDS,
    FinalProductNativeMenuController,
)


def _final_product_resource_sources() -> tuple[tuple[str, str], ...]:
    root = _release_ui._asset_root() / "web"
    resources = (
        ("Stage 1 WebView bootstrap", root / "stage1_release_bootstrap.js"),
        ("Stage 1 board action bridge", root / "stage1_board_actions.js"),
        ("V2 PGN surface", root / "full_product_pgn.js"),
        ("V2 Library surface", root / "full_product_library.js"),
        ("V2 Books surface", root / "full_product_books_training.js"),
        ("V2 Teacher surface", root / "full_product_teacher.js"),
        ("V2 Education surface", root / "full_product_education.js"),
        ("Media accessible Restore Position surface", root / "media_accessible_restore.js"),
        ("V2 final-product bootstrap", root / "version2_final_product_bootstrap.js"),
        ("V2 Media Restore Position bootstrap", root / "version2_media_restore_bootstrap.js"),
        # The final bootstrap creates #v2-workspace synchronously, then starts an
        # asynchronous snapshot refresh. Load P0 after that DOM owner exists so
        # selection retention observes the real workspace, while surface wrappers
        # still bind before a user can interact with the composed routes.
        ("P0 event-aware accessibility runtime", root / "p0_accessibility_runtime.js"),
    )
    output: list[tuple[str, str]] = []
    for label, path in resources:
        if not path.exists():
            raise RuntimeError(f"{label} not found in packaged resources.")
        output.append((label, path.read_text(encoding="utf-8")))
    return tuple(output)


def _composed_language_sync(
    base_sync: Callable[[Any, UILanguage], None],
) -> Callable[[Any, UILanguage], None]:
    def sync(application: Any, language: UILanguage) -> None:
        base_sync(application, language)
        composed_sync = getattr(application, "sync_composed_surfaces_language", None)
        if callable(composed_sync):
            composed_sync(language)

    return sync


def _media_unavailable_state(language: str) -> dict[str, object]:
    uk = language == "uk"
    return {
        "ok": False,
        "revision": None,
        "positionMs": None,
        "positionText": "",
        "qualification": "unavailable",
        "restoreEnabled": False,
        "restoreLabel": "Відновити позицію медіа" if uk else "Restore Media Position",
        "restoreDescription": (
            "Відновлює підтверджену шахову позицію, синхронізовану з поточним часом медіа."
            if uk
            else "Restores the confirmed chess position synchronized with the current media time."
        ),
        "statusText": (
            "Синхронізація медіа зараз недоступна. Шахову позицію не змінено."
            if uk
            else "Media synchronization is currently unavailable. The chess position was not changed."
        ),
        "announcement": "",
        "focusTarget": "media-sync-status",
    }


def _media_bridge(api: Any) -> MediaAccessibilityBridge | None:
    bridge = getattr(api, "_final_product_media_accessibility", None)
    if bridge is None:
        return None
    if not isinstance(bridge, MediaAccessibilityBridge):
        raise TypeError("final Product Media accessibility bridge is invalid")
    language = getattr(api, "lang", "en")
    if bridge.language != language:
        bridge.set_language(language)
    return bridge


def _media_restore_snapshot_api(api: Any) -> dict[str, object]:
    def read() -> dict[str, object]:
        bridge = _media_bridge(api)
        if bridge is None:
            return _media_unavailable_state(getattr(api, "lang", "en"))
        return dict(bridge.snapshot())

    return api._invoke_ui(read)


def _media_restore_position_api(api: Any) -> dict[str, object]:
    def restore() -> dict[str, object]:
        bridge = _media_bridge(api)
        if bridge is None:
            state = _media_unavailable_state(getattr(api, "lang", "en"))
            state["announcement"] = state["statusText"]
            return state
        return dict(bridge.restore_position())

    return api._invoke_ui(restore)


def _bind_api_media(
    api: Any,
    service: MediaApplicationService | None,
) -> None:
    if service is not None and not isinstance(service, MediaApplicationService):
        raise TypeError("media_application_service must be MediaApplicationService or None")
    bridge = (
        MediaAccessibilityBridge(service, language=getattr(api, "lang", "en"))
        if service is not None
        else None
    )
    setattr(api, "_final_product_media_accessibility", bridge)
    # Keep the canonical service on the concrete API instance after the bounded
    # final-product class bindings are restored. No second host API or Media
    # service is created; both commands still use the accepted native UI serializer.
    setattr(api, "media_restore_snapshot", MethodType(_media_restore_snapshot_api, api))
    setattr(api, "media_restore_position", MethodType(_media_restore_position_api, api))


@contextmanager
def _final_product_bindings() -> Iterator[Callable[[Any, UILanguage], None]]:
    """Install final-product release seams only for one bounded composition lifetime."""

    api_type = _release_ui.Version2ReleaseAccessibleChessAPI
    previous_application = _release_app.Version2Application
    previous_action_ids = _release_ui.VERSION2_FULL_PRODUCT_ACTION_IDS
    previous_controller = _release_ui.Version2NativeMenuController
    previous_sync_descriptor = api_type.__dict__["_sync_version2_language"]
    previous_sync = getattr(api_type, "_sync_version2_language")
    previous_resources = _release_ui._resource_sources
    had_media_snapshot = "media_restore_snapshot" in api_type.__dict__
    had_media_restore = "media_restore_position" in api_type.__dict__
    previous_media_snapshot = api_type.__dict__.get("media_restore_snapshot")
    previous_media_restore = api_type.__dict__.get("media_restore_position")

    _release_app.Version2Application = Version2FinalProductApplication
    _release_ui.VERSION2_FULL_PRODUCT_ACTION_IDS = FINAL_PRODUCT_ACTION_IDS
    _release_ui.Version2NativeMenuController = FinalProductNativeMenuController
    setattr(
        api_type,
        "_sync_version2_language",
        staticmethod(_composed_language_sync(previous_sync)),
    )
    # The accepted release main() creates the pywebview API itself. Install the
    # two fail-closed Media methods on that existing API type only for the final
    # Product lifetime so pywebview sees them at window creation without replacing
    # the accepted main lifecycle. Explicit service composition later overrides
    # these methods on that one API instance through _bind_api_media().
    setattr(api_type, "media_restore_snapshot", _media_restore_snapshot_api)
    setattr(api_type, "media_restore_position", _media_restore_position_api)
    _release_ui._resource_sources = _final_product_resource_sources
    try:
        yield previous_sync
    finally:
        _release_ui._resource_sources = previous_resources
        if had_media_restore:
            setattr(api_type, "media_restore_position", previous_media_restore)
        else:
            delattr(api_type, "media_restore_position")
        if had_media_snapshot:
            setattr(api_type, "media_restore_snapshot", previous_media_snapshot)
        else:
            delattr(api_type, "media_restore_snapshot")
        setattr(api_type, "_sync_version2_language", previous_sync_descriptor)
        _release_ui.Version2NativeMenuController = previous_controller
        _release_ui.VERSION2_FULL_PRODUCT_ACTION_IDS = previous_action_ids
        _release_app.Version2Application = previous_application


def _bind_api_language_sync(
    api: Any,
    base_sync: Callable[[Any, UILanguage], None],
) -> None:
    setattr(api, "_sync_version2_language", _composed_language_sync(base_sync))


def create_version2_release_application(*args: Any, **kwargs: Any):
    """Create the final product without leaking its process-global release seams.

    ``media_application_service`` is an optional trusted composition input. When it
    is absent the Product still exposes a truthful disabled Media status. When it
    is supplied, Restore Media Position delegates only to that canonical service.
    """

    media_service = kwargs.pop("media_application_service", None)
    if media_service is not None and not isinstance(media_service, MediaApplicationService):
        raise TypeError("media_application_service must be MediaApplicationService or None")

    defer_ui = kwargs.get("defer_ui", False) is True
    with _final_product_bindings() as base_sync:
        composed = _release_app.create_version2_release_application(*args, **kwargs)
        api = composed[0]
        _bind_api_language_sync(api, base_sync)
        _bind_api_media(api, media_service)

    if not defer_ui:
        return composed

    api, application_factory, runtime, native_runtime_factory = composed
    if not callable(application_factory):
        raise TypeError("deferred Version 2 application factory must be callable")

    def build_final_product_application():
        with _final_product_bindings():
            return application_factory()

    return api, build_final_product_application, runtime, native_runtime_factory


def main() -> None:
    # Preserve the accepted complete synchronous native UI lifecycle. The bounded
    # final-product bindings add the fail-closed Media API/resources before that
    # lifecycle constructs pywebview and restore every process-global seam on exit.
    with _final_product_bindings():
        _release_app.main()


__all__ = ["create_version2_release_application", "main"]
