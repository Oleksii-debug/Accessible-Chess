from __future__ import annotations

"""Document-aware accessible PGN WebView composition.

This adapter adds document-level recovery warnings to the existing PGN warning
surface without becoming a parser, GameTree, or chess-rules authority.  All
workspace semantics remain delegated to the current PgnDocumentSession workspace
and all user-visible warning text reuses the canonical PGN presentation
sanitization policy.
"""

from .full_product_actions import FullProductActionRouter
from .full_product_ui_shell import UILanguage
from .pgn_document import PgnDocumentSession, PgnDocumentView
from .pgn_webview_projection import _bounded_text
from .pgn_workspace_webview_adapter import PgnWorkspaceWebViewProjection


class _SessionWorkspacePort:
    """Late-bound workspace port so session workspace replacement cannot stale the UI."""

    def __init__(self, session: PgnDocumentSession) -> None:
        self._session = session

    def games(self) -> tuple[object, ...]:
        return self._session.workspace.games()

    def view(self) -> object:
        return self._session.workspace.view()


class PgnDocumentWebViewProjection(PgnWorkspaceWebViewProjection):
    """Existing PGN WebView projection plus canonical document-level warnings."""

    def __init__(
        self,
        session: PgnDocumentSession,
        router: FullProductActionRouter,
        *,
        language: UILanguage = UILanguage.UA,
    ) -> None:
        if not isinstance(session, PgnDocumentSession):
            raise TypeError("session must be PgnDocumentSession")
        self._session = session
        self._document_view: PgnDocumentView | None = None
        super().__init__(_SessionWorkspacePort(session), router, language=language)
        # Bind document provenance to the same initial workspace presentation.
        self._refresh()

    def _refresh(self) -> None:
        before = self._session.view()
        if not isinstance(before, PgnDocumentView):
            raise ValueError("PGN document returned an invalid presentation view")
        super()._refresh()
        after = self._session.view()
        if not isinstance(after, PgnDocumentView) or after != before:
            raise ValueError("PGN document changed while creating a presentation snapshot")
        self._document_view = after

    def _snapshot_current(self) -> dict[str, object]:
        snapshot = super()._snapshot_current()
        document_view = self._document_view
        if document_view is None:
            raise ValueError("PGN document presentation is not initialized")

        document_warnings = tuple(
            _bounded_text(warning, language=self._language, limit=720)
            for warning in document_view.global_warnings
            if warning.strip()
        )
        if not document_warnings:
            return snapshot

        game = snapshot.get("game")
        if not isinstance(game, dict) or not game:
            raise ValueError("PGN document warnings require an active game presentation")
        existing = game.get("warnings")
        if not isinstance(existing, tuple):
            raise ValueError("PGN warning presentation is invalid")

        safe_game = dict(game)
        safe_game["warnings"] = document_warnings + existing
        safe_snapshot = dict(snapshot)
        safe_snapshot["game"] = safe_game
        return safe_snapshot


__all__ = ["PgnDocumentWebViewProjection"]
