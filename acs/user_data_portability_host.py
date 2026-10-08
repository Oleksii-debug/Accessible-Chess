from __future__ import annotations

"""Trusted Section 37 native file boundary: never accepts browser-provided paths.

This module does not own user-data schemas or live database state. DomainAdapter
owners and a separately verified startup restore scheduler are injected.
Restore/import NEVER mutate an open product's durable stores.
"""

from collections.abc import Callable, Mapping
from pathlib import Path
import hashlib
import os
import stat
from typing import Any

from .user_data_portability import (
    BundleKind, MAX_BUNDLE_BYTES, UserDataPortabilityCoordinator,
    UserDataPortabilityError,
)
from .version2_windows_native_dialog_ownership import (
    Version2OwnedWindowsFileDialogs, Version2WinFormsDialogOwner,
)


class Version2OwnedUserDataDialogs(Version2OwnedWindowsFileDialogs):
    """Exact native WinForms owner is checked on every file chooser call."""

    def _choose(self, *, action: str, save: bool) -> Path | None:
        DialogResult, OpenFileDialog, SaveFileDialog = self._load_forms()
        dialog = SaveFileDialog() if save else OpenFileDialog()
        try:
            suffix = "acbackup" if action in {"data.backup", "data.restore"} else "acexport"
            english = str(self._dialog_text._language()).lower().startswith("en")
            dialog.Title = (
                ("Save user-data backup" if save else "Open user-data backup")
                if english and suffix == "acbackup" else
                ("Export user data" if save else "Import user data")
                if english else
                ("Зберегти резервну копію" if save else "Відкрити резервну копію")
                if suffix == "acbackup" else
                ("Експорт користувацьких даних" if save else "Імпорт користувацьких даних")
            )
            dialog.Filter = f"Accessible Chess (*.{suffix})|*.{suffix}"
            dialog.DefaultExt = suffix
            dialog.AddExtension = True
            if save:
                dialog.OverwritePrompt = True
            else:
                dialog.CheckFileExists = True
                dialog.CheckPathExists = True
                dialog.Multiselect = False
            return self._selected(dialog, dialog.ShowDialog(), DialogResult.OK)
        finally:
            dialog.Dispose()

    def save_bundle(self, action: str) -> Path | None:
        return self._choose(action=action, save=True)

    def open_bundle(self, action: str) -> Path | None:
        return self._choose(action=action, save=False)


def _safe_read(path: Path) -> bytes:
    """Read only one stable regular file, never a symlink/reparse point."""
    try:
        before = path.lstat()
    except OSError as exc:
        raise UserDataPortabilityError("selected archive is unavailable") from exc
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BUNDLE_BYTES:
        raise UserDataPortabilityError("selected archive is not a bounded regular file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        current = os.fstat(fd)
        if not stat.S_ISREG(current.st_mode) or current.st_size > MAX_BUNDLE_BYTES:
            raise UserDataPortabilityError("archive changed during open")
        if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
            raise UserDataPortabilityError("archive identity changed")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(MAX_BUNDLE_BYTES + 1)
        if len(raw) > MAX_BUNDLE_BYTES:
            raise UserDataPortabilityError("archive exceeds byte limit")
        after = os.fstat(fd)
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
            current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns
        ):
            raise UserDataPortabilityError("archive changed while reading")
        return raw
    finally:
        os.close(fd)


def _write_new_verified(path: Path, raw: bytes) -> None:
    """Fail closed on existing files; no overwrite of user-selected documents."""
    if not path.is_absolute() or not path.parent.is_dir():
        raise UserDataPortabilityError("archive destination is invalid")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    owned: tuple[int, int] | None = None
    try:
        info = os.fstat(fd)
        owned = (info.st_dev, info.st_ino)
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)
    try:
        if hashlib.sha256(_safe_read(path)).digest() != hashlib.sha256(raw).digest():
            raise UserDataPortabilityError("archive publication verification failed")
    except BaseException:
        # Unlink only a file still owned by this exact exclusive creation.
        try:
            now = path.lstat()
            if owned is not None and (now.st_dev, now.st_ino) == owned:
                path.unlink()
        except OSError:
            pass
        raise


class UserDataPortabilityHost:
    """One native-owner-affine action dispatcher for a typed portability coordinator."""

    def __init__(
        self,
        coordinator: UserDataPortabilityCoordinator,
        *,
        owner: Callable[[], object],
        dialogs: object,
        stage_for_restart: Callable[[BundleKind, bytes], bool] | None = None,
    ) -> None:
        if not isinstance(coordinator, UserDataPortabilityCoordinator):
            raise TypeError("canonical portability coordinator required")
        if not callable(owner):
            raise TypeError("native owner callback required")
        for name in ("save_bundle", "open_bundle"):
            if not callable(getattr(dialogs, name, None)):
                raise TypeError("owner-bound archive dialogs required")
        self._coordinator = coordinator
        self._owner = Version2WinFormsDialogOwner(owner)
        self._dialogs = dialogs
        self._stage = stage_for_restart

    def __call__(self, action: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if type(action) is not str or action not in {
            "data.backup", "data.restore", "data.export", "data.import"
        }:
            raise UserDataPortabilityError("unknown user-data operation")
        if type(payload) is not dict or payload:
            raise UserDataPortabilityError("user-data actions accept no paths or payload")
        self._owner.resolve()
        if action in {"data.backup", "data.export"}:
            if action == "data.backup":
                raw, receipt = self._coordinator.create_backup()
            else:
                raw, receipt = self._coordinator.export_user_data()
            path = self._dialogs.save_bundle(action)
            if path is None:
                return {"ok": False, "cancelled": True, "announcement": "Операцію скасовано."}
            _write_new_verified(Path(path), raw)
            return {
                "ok": True, "cancelled": False,
                "announcement": "Користувацькі дані збережено.",
                "sha256": receipt.sha256, "bytes": receipt.byte_size,
                "domains": receipt.domains,
            }

        # Import/restore is deliberately deferred: live SQLite, Settings and
        # Book/Training owners MUST NOT be mutated during the active session.
        if self._stage is None:
            raise UserDataPortabilityError(
                "safe offline restore is not configured; no user data was changed"
            )
        path = self._dialogs.open_bundle(action)
        if path is None:
            return {"ok": False, "cancelled": True, "announcement": "Операцію скасовано."}
        raw = _safe_read(Path(path))
        receipt = self._coordinator.inspect(raw)
        expected = BundleKind.BACKUP if action == "data.restore" else BundleKind.PORTABLE
        if receipt.kind is not expected:
            raise UserDataPortabilityError("selected archive has the wrong kind")
        if self._stage(receipt.kind, raw) is not True:
            raise UserDataPortabilityError("archive could not be staged for safe restart")
        return {
            "ok": True, "restart_required": True,
            "announcement": "Архів перевірено. Для безпечного відновлення потрібен перезапуск.",
            "sha256": receipt.sha256, "bytes": receipt.byte_size,
            "domains": receipt.domains,
        }


__all__ = ["Version2OwnedUserDataDialogs", "UserDataPortabilityHost"]
