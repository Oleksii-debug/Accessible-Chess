from __future__ import annotations

"""Scoped final-product release composition over the accepted Version 2 root.

The final product needs the wider Teacher/Classes action profile, native menu,
language synchronization, and packaged WebView resources while it is being
composed or run.  Those seams are process-global in the accepted release root,
so importing this module must not permanently replace narrower Version 2 owners:
large in-process regression suites and tooling legitimately use both profiles.
"""

from contextlib import contextmanager
import os
import stat
from typing import Any, Callable, Iterator

from . import version2_release_app as _release_app
from . import version2_release_ui as _release_ui
from .full_product_ui_shell import UILanguage
from .version2_final_product_application import Version2FinalProductApplication
from .version2_final_product_profile import (
    FINAL_PRODUCT_ACTION_IDS,
    FinalProductNativeMenuController,
)


_MAX_FINAL_RESOURCE_BYTES = 16 * 1024 * 1024


def _resource_reparse(info: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & flag)


def _same_resource_snapshot(left: os.stat_result, right: os.stat_result) -> bool:
    try:
        same_identity = os.path.samestat(left, right)
    except (AttributeError, OSError):
        same_identity = (
            getattr(left, "st_dev", None),
            getattr(left, "st_ino", None),
        ) == (
            getattr(right, "st_dev", None),
            getattr(right, "st_ino", None),
        )
    return bool(
        same_identity
        and int(left.st_size) == int(right.st_size)
        and getattr(left, "st_mtime_ns", None) == getattr(right, "st_mtime_ns", None)
    )


def _read_resource_text(path: Any, *, label: str) -> str:
    try:
        before = path.lstat()
    except OSError as exc:
        raise RuntimeError(f"{label} not found in packaged resources.") from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or _resource_reparse(before)
        or not stat.S_ISREG(before.st_mode)
    ):
        raise RuntimeError(f"{label} resource is invalid.")
    if before.st_size <= 0 or before.st_size > _MAX_FINAL_RESOURCE_BYTES:
        raise RuntimeError(f"{label} resource size is invalid.")

    source = None
    try:
        source = path.open("rb")
        opened = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(opened.st_mode)
            or _resource_reparse(opened)
            or not _same_resource_snapshot(before, opened)
        ):
            raise RuntimeError(f"{label} changed while being opened.")
        data = source.read(_MAX_FINAL_RESOURCE_BYTES + 1)
        after_read = os.fstat(source.fileno())
        after_path = path.lstat()
        if (
            len(data) > _MAX_FINAL_RESOURCE_BYTES
            or len(data) != int(after_read.st_size)
            or stat.S_ISLNK(after_path.st_mode)
            or _resource_reparse(after_path)
            or not stat.S_ISREG(after_path.st_mode)
            or not _same_resource_snapshot(opened, after_read)
            or not _same_resource_snapshot(after_read, after_path)
        ):
            raise RuntimeError(f"{label} changed while being read.")
        try:
            return data.decode("utf-8")
        except UnicodeError as exc:
            raise RuntimeError(f"{label} resource is not UTF-8.") from exc
    except RuntimeError:
        raise
    except OSError as exc:
        raise RuntimeError(f"{label} resource cannot be read safely.") from exc
    finally:
        if source is not None:
            source.close()


def _is_link_like_resource(path: Any) -> bool:
    try:
        if path.is_symlink():
            return True
        info = path.lstat()
    except OSError:
        return True
    return _resource_reparse(info)


def _final_product_resource_sources() -> tuple[tuple[str, str], ...]:
    root = _release_ui._asset_root() / "web"
    livekit_root = root / "vendor" / "livekit"
    livekit_resources: tuple[tuple[str, Any], ...] = ()
    if os.path.lexists(livekit_root):
        if _is_link_like_resource(livekit_root) or not livekit_root.is_dir():
            raise RuntimeError("LiveKit browser SDK resource root is invalid.")
        livekit_evidence = (
            ("LiveKit browser SDK", livekit_root / "livekit-client.umd.js"),
            ("LiveKit browser SDK license", livekit_root / "LICENSE"),
            ("LiveKit browser SDK notice", livekit_root / "NOTICE"),
            ("LiveKit browser SDK provenance", livekit_root / "provenance.json"),
            ("Classroom LiveKit media adapter", root / "livekit_classroom_media.js"),
            (
                "Classroom LiveKit transactional runtime",
                root / "livekit_classroom_media_runtime.js",
            ),
        )
        for label, path in livekit_evidence:
            if not os.path.lexists(path):
                raise RuntimeError(f"{label} not found in packaged resources.")
            if _is_link_like_resource(path) or not path.is_file():
                raise RuntimeError(f"{label} resource is invalid.")
        livekit_resources = (
            livekit_evidence[0],
            livekit_evidence[-2],
            livekit_evidence[-1],
        )

    resources = (
        ("Stage 1 WebView bootstrap", root / "stage1_release_bootstrap.js"),
        ("Stage 1 board action bridge", root / "stage1_board_actions.js"),
        *livekit_resources,
        ("V2 PGN surface", root / "full_product_pgn.js"),
        ("V2 Library surface", root / "full_product_library.js"),
        ("V2 Books surface", root / "full_product_books_training.js"),
        ("V2 Teacher surface", root / "full_product_teacher.js"),
        ("V2 Education surface", root / "full_product_education.js"),
        ("V2 Classroom media surface", root / "full_product_classroom_media.js"),
        ("V2 final-product bootstrap", root / "version2_final_product_bootstrap.js"),
        # The final bootstrap creates #v2-workspace synchronously, then starts an
        # asynchronous snapshot refresh. Load P0 after that DOM owner exists so
        # selection retention observes the real workspace, while surface wrappers
        # still bind before a user can interact with the composed routes.
        ("P0 event-aware accessibility runtime", root / "p0_accessibility_runtime.js"),
    )
    output: list[tuple[str, str]] = []
    seen_labels: set[str] = set()
    for label, path in resources:
        if label in seen_labels:
            raise RuntimeError("Final-product WebView resource label is duplicated.")
        seen_labels.add(label)
        if not path.exists():
            raise RuntimeError(f"{label} not found in packaged resources.")
        source = _read_resource_text(path, label=label)
        if not source.strip():
            raise RuntimeError(f"{label} is empty in packaged resources.")
        output.append((label, source))
    return tuple(output)


def final_product_resource_sources() -> tuple[tuple[str, str], ...]:
    """Return the canonical final-product WebView resource sequence."""

    return _final_product_resource_sources()


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
def _final_product_bindings() -> Iterator[Callable[[Any, UILanguage], None]]:
    """Install final-product release seams only for one bounded composition lifetime."""

    api_type = _release_ui.Version2ReleaseAccessibleChessAPI
    previous_application = _release_app.Version2Application
    previous_action_ids = _release_ui.VERSION2_FULL_PRODUCT_ACTION_IDS
    previous_controller = _release_ui.Version2NativeMenuController
    previous_sync_descriptor = api_type.__dict__["_sync_version2_language"]
    previous_sync = getattr(api_type, "_sync_version2_language")
    previous_resources = _release_ui._resource_sources

    _release_app.Version2Application = Version2FinalProductApplication
    _release_ui.VERSION2_FULL_PRODUCT_ACTION_IDS = FINAL_PRODUCT_ACTION_IDS
    _release_ui.Version2NativeMenuController = FinalProductNativeMenuController
    setattr(
        api_type,
        "_sync_version2_language",
        staticmethod(_composed_language_sync(previous_sync)),
    )
    _release_ui._resource_sources = _final_product_resource_sources
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
    setattr(api, "_sync_version2_language", _composed_language_sync(base_sync))


def create_version2_release_application(*args: Any, **kwargs: Any):
    """Create the final product without leaking its process-global release seams."""

    defer_ui = kwargs.get("defer_ui", False) is True
    with _final_product_bindings() as base_sync:
        composed = _release_app.create_version2_release_application(*args, **kwargs)
        api = composed[0]
        _bind_api_language_sync(api, base_sync)

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
    # The accepted main() owns the complete synchronous native UI lifetime.
    # Keep final-product seams installed only for that lifetime and restore even
    # when startup or shutdown raises.
    with _final_product_bindings():
        _release_app.main()


__all__ = [
    "create_version2_release_application",
    "final_product_resource_sources",
    "main",
]
