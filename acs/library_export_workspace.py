from __future__ import annotations

"""Canonical composition for the end-user Library/Search/export WebView seam."""

from collections.abc import Callable, Mapping
from typing import Any

from .acsdb import AcsDatabase
from .full_product_presenters import LibraryPresenter
from .full_product_ui_shell import UILanguage
from .library_export_webview_projection import LibraryExportWebViewProjection
from .library_webview_bridge import LibraryWebViewBridge
from .search_service import GameSearchService


def build_library_export_webview(
    database: AcsDatabase,
    dispatch: Callable[[str, Mapping[str, object]], Any],
    *,
    language: UILanguage = UILanguage.UA,
) -> LibraryWebViewBridge:
    """Compose one canonical Search service with the export-aware UI adapter."""

    if not isinstance(database, AcsDatabase):
        raise TypeError("database must be AcsDatabase")
    if not callable(dispatch):
        raise TypeError("dispatch must be callable")
    if not isinstance(language, UILanguage):
        raise TypeError("language must be UILanguage")
    search = GameSearchService(database)
    presenter = LibraryPresenter(search, language=language)
    projection = LibraryExportWebViewProjection(
        presenter,
        dispatch,
        language=language,
    )
    return LibraryWebViewBridge(projection)


__all__ = ["build_library_export_webview"]
