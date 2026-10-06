from __future__ import annotations

"""Release composition for durable V2 PGN/GameTree close/reopen state.

This module does not define chess, PGN, or GameTree semantics.  It composes the
canonical :mod:`gametree_resume` store with the existing V2 document/session
surface and keeps the resume file outside browser-owned state.
"""

import os
import secrets
from pathlib import Path
import stat

from .gametree_resume import (
    GameTreeResumeCode,
    GameTreeResumeDurabilityUnknownError,
    GameTreeResumeError,
    GameTreeResumeStore,
    _exclusive_store_lock,
    _fsync_directory,
    _is_reparse_point,
    _read_store_bytes,
    _token_for_bytes,
    _validate_regular_path,
)
from .pgn_document import PgnDocumentSession
from .pgn_workspace import PgnWorkspace


_DISCARD_GUARD_DIRECTORY = ".gametree-resume-discard"
_DISCARD_GUARD_SUFFIX = ".guard"
_DISCARD_TOMBSTONE_SUFFIX = ".discarding"
_DISCARD_TOMBSTONE_NONCE_HEX = 24
_DISCARD_GUARD_RESERVATION = b"AccessibleChess GameTree discard reservation\n"


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

    @property
    def _discard_guard_directory(self) -> Path:
        return self.store.path.parent / _DISCARD_GUARD_DIRECTORY

    @staticmethod
    def _validate_discard_token(token: str) -> str:
        if (
            len(token) != 64
            or any(character not in "0123456789abcdef" for character in token)
        ):
            raise GameTreeResumeError(
                "resume discard guard token is invalid",
                code=GameTreeResumeCode.IO_FAILURE,
            )
        return token

    @classmethod
    def _discard_guard_token(cls, path: Path) -> str:
        name = path.name
        if not name.endswith(_DISCARD_GUARD_SUFFIX):
            raise GameTreeResumeError(
                "resume discard guard name is invalid",
                code=GameTreeResumeCode.IO_FAILURE,
            )
        return cls._validate_discard_token(name[: -len(_DISCARD_GUARD_SUFFIX)])

    @classmethod
    def _discard_tombstone_token(cls, path: Path) -> str:
        name = path.name
        if not name.endswith(_DISCARD_TOMBSTONE_SUFFIX):
            raise GameTreeResumeError(
                "resume discard tombstone name is invalid",
                code=GameTreeResumeCode.IO_FAILURE,
            )
        stem = name[: -len(_DISCARD_TOMBSTONE_SUFFIX)]
        try:
            token, nonce = stem.rsplit(".", 1)
        except ValueError as error:
            raise GameTreeResumeError(
                "resume discard tombstone name is invalid",
                code=GameTreeResumeCode.IO_FAILURE,
            ) from error
        cls._validate_discard_token(token)
        if (
            len(nonce) != _DISCARD_TOMBSTONE_NONCE_HEX
            or any(character not in "0123456789abcdef" for character in nonce)
        ):
            raise GameTreeResumeError(
                "resume discard tombstone nonce is invalid",
                code=GameTreeResumeCode.IO_FAILURE,
            )
        return token

    @classmethod
    def _discard_entry_token(cls, path: Path) -> str:
        if path.name.endswith(_DISCARD_GUARD_SUFFIX):
            return cls._discard_guard_token(path)
        if path.name.endswith(_DISCARD_TOMBSTONE_SUFFIX):
            return cls._discard_tombstone_token(path)
        raise GameTreeResumeError(
            "resume discard control entry name is invalid",
            code=GameTreeResumeCode.IO_FAILURE,
        )

    def _require_discard_guard_directory(self, *, create: bool) -> Path | None:
        directory = self._discard_guard_directory
        try:
            metadata = directory.lstat()
        except FileNotFoundError:
            if not create:
                return None
            try:
                directory.mkdir()
            except FileExistsError:
                pass
            except OSError as error:
                raise GameTreeResumeError(
                    "resume discard guard directory could not be created",
                    code=GameTreeResumeCode.IO_FAILURE,
                ) from error
            try:
                metadata = directory.lstat()
            except OSError as error:
                raise GameTreeResumeError(
                    "resume discard guard directory could not be verified",
                    code=GameTreeResumeCode.IO_FAILURE,
                ) from error
        except OSError as error:
            raise GameTreeResumeError(
                "resume discard guard directory could not be inspected",
                code=GameTreeResumeCode.IO_FAILURE,
            ) from error

        if (
            stat.S_ISLNK(metadata.st_mode)
            or _is_reparse_point(metadata)
            or not stat.S_ISDIR(metadata.st_mode)
        ):
            raise GameTreeResumeError(
                "resume discard guard root must be a real directory",
                code=GameTreeResumeCode.IO_FAILURE,
            )
        return directory

    def _discard_guard_entries_locked(self) -> tuple[Path, ...]:
        directory = self._require_discard_guard_directory(create=False)
        if directory is None:
            return ()
        try:
            before = directory.lstat()
            entries = tuple(sorted(directory.iterdir(), key=lambda item: item.name))
            after = directory.lstat()
        except OSError as error:
            raise GameTreeResumeError(
                "resume discard guard directory changed while being inspected",
                code=GameTreeResumeCode.IO_FAILURE,
            ) from error
        if (
            stat.S_ISLNK(after.st_mode)
            or _is_reparse_point(after)
            or not stat.S_ISDIR(after.st_mode)
            or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
        ):
            raise GameTreeResumeError(
                "resume discard guard directory changed while being inspected",
                code=GameTreeResumeCode.IO_FAILURE,
            )
        if len(entries) > 1:
            raise GameTreeResumeError(
                "multiple resume discard guards are ambiguous",
                code=GameTreeResumeCode.STALE_WRITER,
            )
        if entries:
            self._discard_entry_token(entries[0])
        return entries

    def _cleanup_discard_guard_directory_locked(self) -> None:
        directory = self._require_discard_guard_directory(create=False)
        if directory is None:
            return
        try:
            before = directory.lstat()
            entries = tuple(directory.iterdir())
            after = directory.lstat()
        except OSError as error:
            raise GameTreeResumeError(
                "resume discard guard directory could not be cleaned up",
                code=GameTreeResumeCode.IO_FAILURE,
            ) from error
        if (
            stat.S_ISLNK(after.st_mode)
            or _is_reparse_point(after)
            or not stat.S_ISDIR(after.st_mode)
            or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
        ):
            raise GameTreeResumeError(
                "resume discard guard directory changed during cleanup",
                code=GameTreeResumeCode.IO_FAILURE,
            )
        if entries:
            raise GameTreeResumeError(
                "resume discard guard state appeared during cleanup",
                code=GameTreeResumeCode.STALE_WRITER,
            )
        try:
            directory.rmdir()
            _fsync_directory(directory.parent)
        except OSError as error:
            raise GameTreeResumeError(
                "resume discard guard directory could not be cleaned up",
                code=GameTreeResumeCode.IO_FAILURE,
            ) from error

    def _remove_discard_tombstone_locked(
        self,
        tombstone: Path,
        *,
        expected_payload: bytes,
    ) -> None:
        moved_payload = _read_store_bytes(tombstone)
        if moved_payload != expected_payload:
            raise GameTreeResumeError(
                "resume discard control state changed before deletion",
                code=GameTreeResumeCode.STALE_WRITER,
            )
        try:
            tombstone.unlink()
        except OSError as error:
            raise GameTreeResumeError(
                "resume discard tombstone could not be removed",
                code=GameTreeResumeCode.IO_FAILURE,
            ) from error
        _fsync_directory(tombstone.parent)
        self._cleanup_discard_guard_directory_locked()

    def _remove_discard_guard_locked(
        self,
        guard: Path,
        *,
        expected_payload: bytes,
    ) -> None:
        intended_token = self._discard_guard_token(guard)
        _read_store_bytes(guard)
        tombstone = guard.parent / (
            f"{intended_token}.{secrets.token_hex(_DISCARD_TOMBSTONE_NONCE_HEX // 2)}"
            f"{_DISCARD_TOMBSTONE_SUFFIX}"
        )
        try:
            os.replace(guard, tombstone)
        except OSError as error:
            raise GameTreeResumeError(
                "resume discard guard could not enter deletion quarantine",
                code=GameTreeResumeCode.IO_FAILURE,
            ) from error
        _fsync_directory(guard.parent)
        self._remove_discard_tombstone_locked(
            tombstone,
            expected_payload=expected_payload,
        )

    def _reserve_discard_guard_locked(self, guard: Path) -> None:
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = -1
        try:
            descriptor = os.open(guard, flags, 0o600)
            offset = 0
            while offset < len(_DISCARD_GUARD_RESERVATION):
                written = os.write(
                    descriptor,
                    _DISCARD_GUARD_RESERVATION[offset:],
                )
                if written <= 0:
                    raise OSError("resume discard guard reservation write stalled")
                offset += written
            os.fsync(descriptor)
        except FileExistsError as error:
            raise GameTreeResumeError(
                "resume discard guard already exists",
                code=GameTreeResumeCode.STALE_WRITER,
            ) from error
        except OSError as error:
            raise GameTreeResumeError(
                "resume discard guard could not be reserved",
                code=GameTreeResumeCode.IO_FAILURE,
            ) from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        _fsync_directory(guard.parent)

    def _restore_guard_to_canonical_locked(
        self,
        guard: Path,
        *,
        expected_token: str,
    ) -> None:
        path = self.store.path
        try:
            os.link(guard, path)
        except FileExistsError as error:
            raise GameTreeResumeError(
                "resume discard recovery found a competing canonical state",
                code=GameTreeResumeCode.STALE_WRITER,
            ) from error
        except OSError as error:
            raise GameTreeResumeError(
                "resume discard recovery could not restore the raced state",
                code=GameTreeResumeCode.IO_FAILURE,
            ) from error

        _fsync_directory(path.parent)
        try:
            canonical_payload = _read_store_bytes(path)
            guard_payload = _read_store_bytes(guard)
            canonical_token = _token_for_bytes(canonical_payload)
            guard_token = _token_for_bytes(guard_payload)
        except GameTreeResumeError:
            raise
        if canonical_token != expected_token or guard_token != expected_token:
            raise GameTreeResumeError(
                "resume discard recovery readback mismatch",
                code=GameTreeResumeCode.STALE_WRITER,
            )
        self._remove_discard_guard_locked(
            guard,
            expected_payload=guard_payload,
        )

    def _reconcile_discard_tombstone_locked(
        self,
        tombstone: Path,
        *,
        intended_token: str,
        tombstone_payload: bytes,
    ) -> None:
        path = self.store.path
        canonical_exists = _validate_regular_path(path, allow_missing=True)

        if tombstone_payload == _DISCARD_GUARD_RESERVATION:
            if not canonical_exists:
                raise GameTreeResumeError(
                    "resume discard reservation tombstone exists without canonical state",
                    code=GameTreeResumeCode.IO_FAILURE,
                )
            self._remove_discard_tombstone_locked(
                tombstone,
                expected_payload=tombstone_payload,
            )
            return

        tombstone_token = _token_for_bytes(tombstone_payload)
        if tombstone_token == intended_token:
            self._remove_discard_tombstone_locked(
                tombstone,
                expected_payload=tombstone_payload,
            )
            return

        if not canonical_exists:
            try:
                os.link(tombstone, path)
            except FileExistsError as error:
                raise GameTreeResumeError(
                    "resume discard tombstone recovery found a competing canonical state",
                    code=GameTreeResumeCode.STALE_WRITER,
                ) from error
            except OSError as error:
                raise GameTreeResumeError(
                    "resume discard tombstone recovery could not preserve raced state",
                    code=GameTreeResumeCode.IO_FAILURE,
                ) from error
            _fsync_directory(path.parent)
            canonical_payload = _read_store_bytes(path)
            if canonical_payload != tombstone_payload:
                raise GameTreeResumeError(
                    "resume discard tombstone recovery readback mismatch",
                    code=GameTreeResumeCode.STALE_WRITER,
                )
            self._remove_discard_tombstone_locked(
                tombstone,
                expected_payload=tombstone_payload,
            )
            return

        canonical_payload = _read_store_bytes(path)
        if canonical_payload == tombstone_payload:
            self._remove_discard_tombstone_locked(
                tombstone,
                expected_payload=tombstone_payload,
            )
            return

        raise GameTreeResumeError(
            "resume discard tombstone recovery found divergent durable states",
            code=GameTreeResumeCode.STALE_WRITER,
        )

    def _reconcile_discard_guard_locked(self) -> None:
        entries = self._discard_guard_entries_locked()
        if not entries:
            self._cleanup_discard_guard_directory_locked()
            return

        guard = entries[0]
        intended_token = self._discard_entry_token(guard)
        guard_payload = _read_store_bytes(guard)
        if guard.name.endswith(_DISCARD_TOMBSTONE_SUFFIX):
            self._reconcile_discard_tombstone_locked(
                guard,
                intended_token=intended_token,
                tombstone_payload=guard_payload,
            )
            return
        path = self.store.path
        canonical_exists = _validate_regular_path(path, allow_missing=True)

        if guard_payload == _DISCARD_GUARD_RESERVATION:
            # Crash before the canonical->guard atomic move: the reservation has
            # no user state. It is removable only while canonical state remains.
            if not canonical_exists:
                raise GameTreeResumeError(
                    "resume discard reservation exists without canonical state",
                    code=GameTreeResumeCode.IO_FAILURE,
                )
            self._remove_discard_guard_locked(
                guard,
                expected_payload=guard_payload,
            )
            return

        guard_token = _token_for_bytes(guard_payload)
        if guard_token == intended_token:
            # The exact state whose Discard was already confirmed reached the
            # guard. A concurrently published *different* canonical generation
            # is preserved. An identical claimed generation at both names is
            # ambiguous rather than silently resurrected.
            if canonical_exists:
                canonical_token = _token_for_bytes(_read_store_bytes(path))
                if canonical_token == intended_token:
                    raise GameTreeResumeError(
                        "resume discard recovery found duplicate claimed state",
                        code=GameTreeResumeCode.STALE_WRITER,
                    )
            self._remove_discard_guard_locked(
                guard,
                expected_payload=guard_payload,
            )
            return

        if not canonical_exists:
            # The atomic move captured a raced newer state. Restore that exact
            # state to the canonical name without clobbering a concurrent writer.
            self._restore_guard_to_canonical_locked(
                guard,
                expected_token=guard_token,
            )
            return

        canonical_token = _token_for_bytes(_read_store_bytes(path))
        if canonical_token == guard_token:
            # Crash after no-clobber restoration but before guard cleanup.
            self._remove_discard_guard_locked(
                guard,
                expected_payload=guard_payload,
            )
            return

        # Two different valid pathnames are safer than choosing a winner. Leave
        # both byte sets intact and disable resume until the ambiguity is resolved.
        raise GameTreeResumeError(
            "resume discard recovery found divergent durable states",
            code=GameTreeResumeCode.STALE_WRITER,
        )

    def _reconcile_discard_guard(self) -> None:
        path = self.store.path
        path.parent.mkdir(parents=True, exist_ok=True)
        with _exclusive_store_lock(path):
            self._reconcile_discard_guard_locked()

    def restore(self, application: object) -> bool:
        """Restore a valid prior selected game/cursor into a fresh V2 application."""

        if self._disabled:
            return False
        path = self.store.path
        guard_directory = self._discard_guard_directory
        if not os.path.lexists(path) and not os.path.lexists(guard_directory):
            return False
        try:
            self._reconcile_discard_guard()
            if not _validate_regular_path(path, allow_missing=True):
                return False
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
            self._reconcile_discard_guard_locked()
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
            claimed_token = self._token
            if claimed_token is None or current_token != claimed_token:
                raise GameTreeResumeError(
                    "resume store changed before discard publication",
                    code=GameTreeResumeCode.STALE_WRITER,
                )

            directory = self._require_discard_guard_directory(create=True)
            assert directory is not None
            guard = directory / f"{claimed_token}{_DISCARD_GUARD_SUFFIX}"
            self._reserve_discard_guard_locked(guard)
            try:
                os.replace(path, guard)
            except OSError as error:
                raise GameTreeResumeError(
                    "resume store could not enter discard guard",
                    code=GameTreeResumeCode.IO_FAILURE,
                ) from error
            _fsync_directory(path.parent)
            _fsync_directory(directory)

            moved_payload = _read_store_bytes(guard)
            moved_token = _token_for_bytes(moved_payload)
            if moved_token != claimed_token:
                # The canonical pathname changed after authentication but before
                # the atomic move. Never discard those newer bytes.
                if not _validate_regular_path(path, allow_missing=True):
                    self._restore_guard_to_canonical_locked(
                        guard,
                        expected_token=moved_token,
                    )
                else:
                    canonical_token = _token_for_bytes(_read_store_bytes(path))
                    if canonical_token == moved_token:
                        self._remove_discard_guard_locked(
                guard,
                expected_payload=moved_payload,
            )
                raise GameTreeResumeError(
                    "resume store changed during discard publication",
                    code=GameTreeResumeCode.STALE_WRITER,
                )

            # Only the exact claimed bytes are now in the reserved guard. Their
            # deletion cannot target a concurrently recreated canonical pathname.
            self._remove_discard_guard_locked(
                            guard,
                            expected_payload=moved_payload,
                        )
            self._token = None
            if _validate_regular_path(path, allow_missing=True):
                raise GameTreeResumeError(
                    "a newer resume store appeared during discard publication",
                    code=GameTreeResumeCode.STALE_WRITER,
                )
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
        self._reconcile_discard_guard()
        if bool(getattr(session, "dirty")):
            self._clear_claimed_resume()
            return

        workspace = getattr(session, "workspace", None)
        if not isinstance(workspace, PgnWorkspace):
            raise TypeError("Version 2 PGN session has no canonical workspace")
        try:
            state = self.store.save(
                workspace.current_game(),
                workspace.cursor,
                expected_token=self._token,
            )
        except GameTreeResumeDurabilityUnknownError as error:
            # Atomic publication already happened. Preserve the exact published
            # CAS token so a user retry can reconcile/update that generation
            # instead of falsely acting as the stale pre-publication writer.
            self._token = error.published_token
            raise
        self._token = state.token


__all__ = ["Version2GameTreeResumeCoordinator"]
