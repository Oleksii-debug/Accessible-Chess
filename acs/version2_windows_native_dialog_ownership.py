from __future__ import annotations

"""Owner-bound WinForms dialogs for Version 2 trusted file workflows.

The base file-workflow classes deliberately keep filesystem selection inside the
trusted Windows host. This module adds the remaining Windows modality contract:
every Open/Save/Import/Export dialog can be bound to the real application
WinForms owner so z-order, modality and focus restoration are deterministic
instead of relying on an unowned ``ShowDialog()``.

No PGN, GameTree, Library, ChessBase, or export semantics live here.
"""

from collections.abc import Callable
import threading
from typing import Any

from .version2_windows_file_workflows import Version2WindowsFileDialogs
from .version2_windows_pgn_export import Version2WindowsPgnExportDialogs


class Version2WinFormsDialogOwner:
    """Resolve one UI-thread WinForms owner for native file dialogs."""

    def __init__(self, owner_provider: Callable[[], object]) -> None:
        if not callable(owner_provider):
            raise TypeError("dialog owner provider must be callable")
        self._owner_provider = owner_provider
        self._ui_thread_id = threading.get_ident()

    @property
    def ui_thread_id(self) -> int:
        return self._ui_thread_id

    def resolve(self) -> object:
        if threading.get_ident() != self._ui_thread_id:
            raise RuntimeError("native file dialogs must be opened on the UI thread")
        try:
            owner = self._owner_provider()
        except Exception:
            raise RuntimeError("native file dialog owner is unavailable") from None
        if owner is None:
            raise RuntimeError("native file dialog owner is unavailable")
        try:
            disposed = bool(getattr(owner, "IsDisposed", False))
            disposing = bool(getattr(owner, "Disposing", False))
            invoke_required = bool(getattr(owner, "InvokeRequired", False))
        except Exception:
            raise RuntimeError("native file dialog owner is unavailable") from None
        if disposed or disposing:
            raise RuntimeError("native file dialog owner is unavailable")
        if invoke_required:
            raise RuntimeError("native file dialogs must be opened on the UI thread")
        return owner


class _OwnedDialogProxy:
    """Transparent CommonDialog proxy that always supplies the validated owner."""

    __slots__ = ("_dialog", "_owner")

    def __init__(self, dialog: object, owner: Version2WinFormsDialogOwner) -> None:
        object.__setattr__(self, "_dialog", dialog)
        object.__setattr__(self, "_owner", owner)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._dialog, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self.__slots__:
            object.__setattr__(self, name, value)
            return
        setattr(self._dialog, name, value)

    def ShowDialog(self):  # noqa: N802 - mirrors the WinForms API
        return self._dialog.ShowDialog(self._owner.resolve())

    def Dispose(self):  # noqa: N802 - mirrors the WinForms API
        return self._dialog.Dispose()


def _owned_dialog_factory(
    native_dialog_type: Callable[[], object],
    owner: Version2WinFormsDialogOwner,
):
    class OwnedDialog:
        def __new__(cls):
            return _OwnedDialogProxy(native_dialog_type(), owner)

    return OwnedDialog


class _OwnedDialogMixin:
    def _configure_owned_dialogs(
        self,
        owner_provider: Callable[[], object],
        forms_loader: Callable[[], tuple[object, Callable[[], object], Callable[[], object]]],
    ) -> None:
        self._dialog_owner = Version2WinFormsDialogOwner(owner_provider)
        self._forms_loader = forms_loader

    @property
    def dialog_owner(self) -> Version2WinFormsDialogOwner:
        return self._dialog_owner

    def _load_forms(self):
        DialogResult, OpenFileDialog, SaveFileDialog = self._forms_loader()
        return (
            DialogResult,
            _owned_dialog_factory(OpenFileDialog, self._dialog_owner),
            _owned_dialog_factory(SaveFileDialog, self._dialog_owner),
        )


class Version2OwnedWindowsFileDialogs(_OwnedDialogMixin, Version2WindowsFileDialogs):
    """Owner-bound Open/Save/Import dialogs for the trusted Windows host."""

    def __init__(
        self,
        owner_provider: Callable[[], object],
        *,
        forms_loader: Callable[
            [], tuple[object, Callable[[], object], Callable[[], object]]
        ]
        | None = None,
    ) -> None:
        self._configure_owned_dialogs(
            owner_provider,
            forms_loader or Version2WindowsFileDialogs._load_forms,
        )


class Version2OwnedWindowsPgnExportDialogs(
    _OwnedDialogMixin,
    Version2WindowsPgnExportDialogs,
):
    """Owner-bound Save dialog for canonical PGN selection export."""

    def __init__(
        self,
        owner_provider: Callable[[], object],
        *,
        forms_loader: Callable[
            [], tuple[object, Callable[[], object], Callable[[], object]]
        ]
        | None = None,
    ) -> None:
        self._configure_owned_dialogs(
            owner_provider,
            forms_loader or Version2WindowsPgnExportDialogs._load_forms,
        )


__all__ = [
    "Version2WinFormsDialogOwner",
    "Version2OwnedWindowsFileDialogs",
    "Version2OwnedWindowsPgnExportDialogs",
]
