from __future__ import annotations

"""Owner-bound WinForms dialogs for Version 2 trusted file workflows.

The base file-workflow classes deliberately keep filesystem selection inside the
trusted Windows host. This module adds the remaining Windows modality contract:
every Open/Save/Import/Export dialog can be bound to the real application
WinForms owner so z-order, modality and focus restoration are deterministic
instead of relying on an unowned ``ShowDialog()``.

The production owner-bound dialogs also project the current V2 UI language into
native titles, filters and destructive confirmations. The language is resolved
lazily for every invocation so a live Ukrainian/English switch does not require
recreating the native host runtime. The projection wraps the existing dialog
methods rather than copying their file/format behavior, so this module still owns
no PGN, GameTree, Library, ChessBase, export, or chess semantics.
"""

from collections.abc import Callable
import threading
from typing import Any

from .version2_windows_file_workflows import Version2WindowsFileDialogs
from .version2_windows_pgn_export import Version2WindowsPgnExportDialogs


_DIALOG_TEXT: dict[str, dict[str, str]] = {
    "en": {
        "open_pgn_title": "Open PGN",
        "save_pgn_as_title": "Save PGN As",
        "pgn_filter": "PGN files (*.pgn)|*.pgn|All files (*.*)|*.*",
        "import_library_title": "Import into Library",
        "import_library_filter": (
            "Supported chess sources (*.pgn;*.cbh;*.cbv)|*.pgn;*.cbh;*.cbv|"
            "PGN files (*.pgn)|*.pgn|ChessBase files (*.cbh;*.cbv)|*.cbh;*.cbv"
        ),
        "unsaved_pgn_title": "Unsaved PGN changes",
        "unsaved_pgn_message": (
            "The current PGN has unsaved changes. Discard those changes and open another PGN?"
        ),
        "export_pgn_title": "Export PGN selection",
        "open_book_title": "Open chess book",
        "book_filter": (
            "Supported books (*.html;*.htm;*.xhtml;*.txt;*.md;*.markdown)|"
            "*.html;*.htm;*.xhtml;*.txt;*.md;*.markdown|"
            "HTML books (*.html;*.htm;*.xhtml)|*.html;*.htm;*.xhtml|"
            "Text and Markdown (*.txt;*.md;*.markdown)|*.txt;*.md;*.markdown"
        ),
    },
    "uk": {
        "open_pgn_title": "Відкрити PGN",
        "save_pgn_as_title": "Зберегти PGN як",
        "pgn_filter": "Файли PGN (*.pgn)|*.pgn|Усі файли (*.*)|*.*",
        "import_library_title": "Імпортувати до бібліотеки",
        "import_library_filter": (
            "Підтримувані шахові джерела (*.pgn;*.cbh;*.cbv)|*.pgn;*.cbh;*.cbv|"
            "Файли PGN (*.pgn)|*.pgn|Файли ChessBase (*.cbh;*.cbv)|*.cbh;*.cbv"
        ),
        "unsaved_pgn_title": "Незбережені зміни PGN",
        "unsaved_pgn_message": (
            "Поточний PGN має незбережені зміни. Відкинути їх і відкрити інший PGN?"
        ),
        "export_pgn_title": "Експортувати вибране як PGN",
        "open_book_title": "Відкрити шахову книгу",
        "book_filter": (
            "Підтримувані книги (*.html;*.htm;*.xhtml;*.txt;*.md;*.markdown)|"
            "*.html;*.htm;*.xhtml;*.txt;*.md;*.markdown|"
            "Книги HTML (*.html;*.htm;*.xhtml)|*.html;*.htm;*.xhtml|"
            "Текст і Markdown (*.txt;*.md;*.markdown)|*.txt;*.md;*.markdown"
        ),
    },
}
_SOURCE_TEXT_KEY = {value: key for key, value in _DIALOG_TEXT["en"].items()}


class Version2WindowsDialogText:
    """Resolve path-free native-dialog copy from the live V2 language owner."""

    def __init__(self, language_provider: Callable[[], object] | None = None) -> None:
        if language_provider is not None and not callable(language_provider):
            raise TypeError("dialog language provider must be callable")
        self._language_provider = language_provider

    def _language(self) -> str:
        if self._language_provider is None:
            return "en"
        try:
            value = self._language_provider()
        except Exception:
            return "en"
        value = getattr(value, "value", value)
        return "uk" if value == "uk" else "en"

    def get(self, key: str) -> str:
        if type(key) is not str or key not in _DIALOG_TEXT["en"]:
            raise KeyError("unknown Version 2 native dialog text key")
        return _DIALOG_TEXT[self._language()][key]

    def localize(self, value: str) -> str:
        """Translate known presentation copy while preserving unknown host values."""

        if type(value) is not str:
            raise TypeError("native dialog presentation text must be text")
        key = _SOURCE_TEXT_KEY.get(value)
        return value if key is None else self.get(key)


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
    """Transparent CommonDialog proxy that supplies the owner and localized copy."""

    __slots__ = ("_dialog", "_owner", "_text")

    def __init__(
        self,
        dialog: object,
        owner: Version2WinFormsDialogOwner,
        text: Version2WindowsDialogText,
    ) -> None:
        object.__setattr__(self, "_dialog", dialog)
        object.__setattr__(self, "_owner", owner)
        object.__setattr__(self, "_text", text)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._dialog, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self.__slots__:
            object.__setattr__(self, name, value)
            return
        if name in {"Title", "Filter"} and type(value) is str:
            value = self._text.localize(value)
        setattr(self._dialog, name, value)

    def ShowDialog(self):  # noqa: N802 - mirrors the WinForms API
        return self._dialog.ShowDialog(self._owner.resolve())

    def Dispose(self):  # noqa: N802 - mirrors the WinForms API
        return self._dialog.Dispose()


def _owned_dialog_factory(
    native_dialog_type: Callable[[], object],
    owner: Version2WinFormsDialogOwner,
    text: Version2WindowsDialogText,
):
    class OwnedDialog:
        def __new__(cls):
            return _OwnedDialogProxy(native_dialog_type(), owner, text)

    return OwnedDialog


class _OwnedDialogMixin:
    def _configure_owned_dialogs(
        self,
        owner_provider: Callable[[], object],
        forms_loader: Callable[[], tuple[object, Callable[[], object], Callable[[], object]]],
        language_provider: Callable[[], object] | None = None,
    ) -> None:
        self._dialog_owner = Version2WinFormsDialogOwner(owner_provider)
        self._forms_loader = forms_loader
        self._dialog_text = Version2WindowsDialogText(language_provider)

    @property
    def dialog_owner(self) -> Version2WinFormsDialogOwner:
        return self._dialog_owner

    def dialog_text(self, key: str) -> str:
        return self._dialog_text.get(key)

    def _load_forms(self):
        DialogResult, OpenFileDialog, SaveFileDialog = self._forms_loader()
        return (
            DialogResult,
            _owned_dialog_factory(OpenFileDialog, self._dialog_owner, self._dialog_text),
            _owned_dialog_factory(SaveFileDialog, self._dialog_owner, self._dialog_text),
        )


class Version2OwnedWindowsFileDialogs(_OwnedDialogMixin, Version2WindowsFileDialogs):
    """Owner-bound localized Open/Save/Import dialogs for the trusted Windows host."""

    def __init__(
        self,
        owner_provider: Callable[[], object],
        *,
        forms_loader: Callable[
            [], tuple[object, Callable[[], object], Callable[[], object]]
        ]
        | None = None,
        message_box_loader: Callable[[], tuple[object, object, object]] | None = None,
        language_provider: Callable[[], object] | None = None,
    ) -> None:
        self._configure_owned_dialogs(
            owner_provider,
            forms_loader or Version2WindowsFileDialogs._load_forms,
            language_provider,
        )
        self._message_box_loader = message_box_loader or self._load_message_box

    @staticmethod
    def _load_message_box() -> tuple[object, object, object]:
        import clr  # type: ignore

        clr.AddReference("System.Windows.Forms")
        from System.Windows.Forms import MessageBox, MessageBoxButtons, MessageBoxIcon  # type: ignore

        return MessageBox, MessageBoxButtons, MessageBoxIcon

    def confirm_discard_unsaved_pgn(self) -> bool:
        """Show the destructive confirmation modally owned by the application window."""

        owner = self._dialog_owner.resolve()
        DialogResult, _, _ = self._forms_loader()
        MessageBox, MessageBoxButtons, MessageBoxIcon = self._message_box_loader()
        result = MessageBox.Show(
            owner,
            self.dialog_text("unsaved_pgn_message"),
            self.dialog_text("unsaved_pgn_title"),
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Warning,
        )
        return result == DialogResult.Yes


class Version2OwnedWindowsPgnExportDialogs(
    _OwnedDialogMixin,
    Version2WindowsPgnExportDialogs,
):
    """Owner-bound localized Save dialog for canonical PGN selection export."""

    def __init__(
        self,
        owner_provider: Callable[[], object],
        *,
        forms_loader: Callable[
            [], tuple[object, Callable[[], object], Callable[[], object]]
        ]
        | None = None,
        language_provider: Callable[[], object] | None = None,
    ) -> None:
        self._configure_owned_dialogs(
            owner_provider,
            forms_loader or Version2WindowsPgnExportDialogs._load_forms,
            language_provider,
        )


__all__ = [
    "Version2WindowsDialogText",
    "Version2WinFormsDialogOwner",
    "Version2OwnedWindowsFileDialogs",
    "Version2OwnedWindowsPgnExportDialogs",
]
