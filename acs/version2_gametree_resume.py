from __future__ import annotations

"""Release composition for durable V2 PGN/GameTree close/reopen state.

This module does not define chess, PGN, or GameTree semantics.  It composes the
canonical :mod:`gametree_resume` store with the existing V2 document/session
surface and keeps the resume file outside browser-owned state.
"""

import os
from pathlib import Path

from .gametree_resume import (
    GameTreeResumeCode,
    GameTreeResumeError,
    GameTreeResumeStore,
    _exclusive_store_lock,
    _fsync_directory,
    _read_store_bytes,
    _token_for_bytes,
    _validate_regular_path,
)
from .pgn_document import PgnDocumentSession
from .pgn_workspace import PgnWorkspace


class Version2GameTreeResumeCoordinator:
    """Bind the canonical one-game resume envelope to the V2 release lifecycle.

    A valid stored state is restored as a clean, source-less document containing
    exactly the selected canonical game and cursor.  Clean close publishes the
    current selected game/cursor through the existing CAS store.  Dirty close is
    reached only after the native release guard has confirmed Discard; in that
    case the previous durable resume is removed with the same token discipline so
    discarded work cannot cause an older unrelated analysis session to reappear.

    Corrupt/unrestorable state is never overwritten.  Resume is disabled for the
    current process and the error is exposed on the application for diagnostics;
    the rest of Accessible Chess remains usable.
    """

    def __init__(self, path: str | Path) -> None:
        self.store = GameTreeResumeStore(path)
        self._token: str | None = None
        self._disabled = False
        self.error: GameTreeResumeError | None = None

    @property
    def token(self) -> str | None:
        return self._token

    @property
    def disabled(self) -> bool:
        return self._disabled

    def _disable(self, application: object, error: GameTreeResumeError) -> None:
        self.error = error
        self._disabled = True
        setattr(application, "_gametree_resume_error", error)

    def restore(self, application: object) -> bool:
        """Restore a valid prior selected game/cursor into a fresh V2 application."""

        if self._disabled:
            return False
        path = self.store.path
        if not path.exists():
            return False
        try:
            state = self.store.load()
        except GameTreeResumeError as error:
            self._disable(application, error)
            return False

        workspace = PgnWorkspace((state.game,))
        workspace.set_cursor(state.cursor)
        session = PgnDocumentSession(
            workspace,
            saved_digest=workspace.content_digest,
        )
        install = getattr(application, "set_document", None)
        if not callable(install):
            raise TypeError("Version 2 application does not expose set_document()")
        install(session)
        self._token = state.token
        return True

    def _clear_claimed_resume(self) -> bool:
        """CAS-delete only the exact resume generation this process observed."""

        path = self.store.path
        path.parent.mkdir(parents=True, exist_ok=True)
        with _exclusive_store_lock(path):
            exists = _validate_regular_path(path, allow_missing=True)
            if not exists:
                if self._token is not None:
                    raise GameTreeResumeError(
                        "resume store disappeared since it was observed",
                        code=GameTreeResumeCode.STALE_WRITER,
                    )
                return False

            payload = _read_store_bytes(path)
            current_token = _token_for_bytes(payload)
            if self._token is None or current_token != self._token:
                raise GameTreeResumeError(
                    "resume store changed before discard publication",
                    code=GameTreeResumeCode.STALE_WRITER,
                )
            try:
                path.unlink()
            except OSError as error:
                raise GameTreeResumeError(
                    "resume store could not be removed after confirmed discard",
                    code=GameTreeResumeCode.IO_FAILURE,
                ) from error
            _fsync_directory(path.parent)
            self._token = None
            return True

    def prepare_shutdown(self, application: object) -> None:
        """Publish clean resume or invalidate it after confirmed dirty Discard.

        The native close guard calls this only after dirty-close confirmation and
        immediately before the existing application shutdown sequence.  Any CAS or
        I/O failure propagates so the native FormClosing guard can cancel rather
        than silently losing or resurrecting state.
        """

        if self._disabled:
            return
        session = getattr(application, "session", None)
        if session is None:
            return
        if bool(getattr(session, "dirty")):
            self._clear_claimed_resume()
            return

        workspace = getattr(session, "workspace", None)
        if not isinstance(workspace, PgnWorkspace):
            raise TypeError("Version 2 PGN session has no canonical workspace")
        state = self.store.save(
            workspace.current_game(),
            workspace.cursor,
            expected_token=self._token,
        )
        self._token = state.token


__all__ = ["Version2GameTreeResumeCoordinator"]
