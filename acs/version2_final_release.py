from __future__ import annotations

"""Final-product release composition without mutating the frozen V2 checkpoint.

Importing this module late-binds the existing release root to the bounded
Teacher/Classes composition profile. The accepted release lifecycle, Windows
host, file dialogs, board authority, packaging entry point, and shutdown logic
remain the existing Version 2 owners.
"""

from . import version2_release_app as _release_app
from . import version2_release_ui as _release_ui
from .version2_final_product_application import Version2FinalProductApplication
from .version2_final_product_profile import (
    FINAL_PRODUCT_ACTION_IDS,
    FinalProductNativeMenuController,
)

# Late-bind only the release composition seams. The frozen checkpoint modules
# remain importable and testable as-is.
_release_app.Version2Application = Version2FinalProductApplication
_release_ui.VERSION2_FULL_PRODUCT_ACTION_IDS = FINAL_PRODUCT_ACTION_IDS
_release_ui.Version2NativeMenuController = FinalProductNativeMenuController

_BASE_LANGUAGE_SYNC = _release_ui.Version2ReleaseAccessibleChessAPI._sync_version2_language


def _sync_final_product_language(application, language) -> None:
    _BASE_LANGUAGE_SYNC(application, language)
    sync = getattr(application, "sync_composed_surfaces_language", None)
    if callable(sync):
        sync(language)


_release_ui.Version2ReleaseAccessibleChessAPI._sync_version2_language = staticmethod(
    _sync_final_product_language
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
        ("V2 final-product bootstrap", root / "version2_final_product_bootstrap.js"),
    )
    output: list[tuple[str, str]] = []
    for label, path in resources:
        if not path.exists():
            raise RuntimeError(f"{label} not found in packaged resources.")
        output.append((label, path.read_text(encoding="utf-8")))
    return tuple(output)


_release_ui._resource_sources = _final_product_resource_sources

create_version2_release_application = _release_app.create_version2_release_application
main = _release_app.main

__all__ = ["create_version2_release_application", "main"]
