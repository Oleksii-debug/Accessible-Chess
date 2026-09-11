from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from acs.full_product_ui_shell import UILanguage
import acs.version2_release_app as release_app
from acs.version2_release_app import _Version2OwnedBookDialogs
from acs.version2_windows_host_runtime import Version2WindowsFileWorkflowRuntime
from acs.version2_windows_native_dialog_ownership import (
    Version2OwnedWindowsFileDialogs,
    Version2OwnedWindowsPgnExportDialogs,
    Version2WindowsDialogText,
)


class _EventHook:
    def __init__(self) -> None:
        self.handlers: list[object] = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class _Owner:
    def __init__(self) -> None:
        self.IsDisposed = False
        self.Disposing = False
        self.InvokeRequired = False
        self.posted: list[object] = []
        self.FormClosing = _EventHook()

    def BeginInvoke(self, delegate):  # noqa: N802
        self.posted.append(delegate)
        return len(self.posted)


class _DialogResult:
    OK = "ok"
    Yes = "yes"
    No = "no"


class _NativeDialog:
    instances: list["_NativeDialog"] = []

    def __init__(self) -> None:
        self.FileName = ""
        self.Title = ""
        self.Filter = ""
        self.show_args: tuple[object, ...] | None = None
        self.disposed = False
        type(self).instances.append(self)

    def ShowDialog(self, *args):  # noqa: N802
        self.show_args = args
        if not self.FileName:
            self.FileName = "selected.pgn"
        return _DialogResult.OK

    def Dispose(self):  # noqa: N802
        self.disposed = True


class _OpenDialog(_NativeDialog):
    instances: list["_OpenDialog"] = []


class _SaveDialog(_NativeDialog):
    instances: list["_SaveDialog"] = []


class _MessageBoxButtons:
    YesNo = "yes-no"


class _MessageBoxIcon:
    Warning = "warning"


class _MessageBox:
    calls: list[tuple[object, ...]] = []

    @classmethod
    def Show(cls, *args):  # noqa: N802
        cls.calls.append(args)
        return _DialogResult.Yes


def _forms_loader():
    return _DialogResult, _OpenDialog, _SaveDialog


def _message_box_loader():
    return _MessageBox, _MessageBoxButtons, _MessageBoxIcon


class Version2NativeDialogLanguageTests(unittest.TestCase):
    def setUp(self) -> None:
        _OpenDialog.instances.clear()
        _SaveDialog.instances.clear()
        _MessageBox.calls.clear()

    def test_file_dialogs_follow_live_language_without_runtime_recreation(self) -> None:
        owner = _Owner()
        language = {"value": UILanguage.UA}
        dialogs = Version2OwnedWindowsFileDialogs(
            lambda: owner,
            forms_loader=_forms_loader,
            message_box_loader=_message_box_loader,
            language_provider=lambda: language["value"],
        )

        self.assertEqual(dialogs.open_pgn(), Path("selected.pgn"))
        self.assertEqual(_OpenDialog.instances[-1].Title, "Відкрити PGN")
        self.assertIn("Усі файли", _OpenDialog.instances[-1].Filter)

        self.assertEqual(dialogs.save_pgn_as("private.pgn"), Path("private.pgn"))
        self.assertEqual(_SaveDialog.instances[-1].Title, "Зберегти PGN як")
        self.assertEqual(_SaveDialog.instances[-1].show_args, (owner,))

        self.assertEqual(dialogs.select_library_import(), Path("selected.pgn"))
        self.assertEqual(_OpenDialog.instances[-1].Title, "Імпортувати до бібліотеки")
        self.assertIn("Підтримувані шахові джерела", _OpenDialog.instances[-1].Filter)

        self.assertTrue(dialogs.confirm_discard_unsaved_pgn())
        self.assertEqual(_MessageBox.calls[-1][0], owner)
        self.assertIn("незбережені зміни", _MessageBox.calls[-1][1].casefold())
        self.assertEqual(_MessageBox.calls[-1][2], "Незбережені зміни PGN")

        language["value"] = UILanguage.EN
        self.assertEqual(dialogs.open_pgn(), Path("selected.pgn"))
        self.assertEqual(_OpenDialog.instances[-1].Title, "Open PGN")
        self.assertIn("All files", _OpenDialog.instances[-1].Filter)
        self.assertEqual(dialogs.save_pgn_as("private.pgn"), Path("private.pgn"))
        self.assertEqual(_SaveDialog.instances[-1].Title, "Save PGN As")
        self.assertEqual(dialogs.select_library_import(), Path("selected.pgn"))
        self.assertEqual(_OpenDialog.instances[-1].Title, "Import into Library")
        self.assertTrue(dialogs.confirm_discard_unsaved_pgn())
        self.assertEqual(_MessageBox.calls[-1][2], "Unsaved PGN changes")

    def test_export_and_book_dialogs_share_same_dynamic_language_owner(self) -> None:
        owner = _Owner()
        language = {"value": UILanguage.UA}
        provider = lambda: language["value"]
        exports = Version2OwnedWindowsPgnExportDialogs(
            lambda: owner,
            forms_loader=_forms_loader,
            language_provider=provider,
        )
        books = _Version2OwnedBookDialogs(
            lambda: owner,
            forms_loader=_forms_loader,
            language_provider=provider,
        )

        self.assertEqual(exports.export_selection(), Path("selection.pgn"))
        self.assertEqual(_SaveDialog.instances[-1].Title, "Експортувати вибране як PGN")
        self.assertEqual(books.open_book(), Path("selected.pgn"))
        self.assertEqual(_OpenDialog.instances[-1].Title, "Відкрити шахову книгу")
        self.assertIn("Підтримувані книги", _OpenDialog.instances[-1].Filter)

        language["value"] = UILanguage.EN
        self.assertEqual(exports.export_selection(), Path("selection.pgn"))
        self.assertEqual(_SaveDialog.instances[-1].Title, "Export PGN selection")
        self.assertEqual(books.open_book(), Path("selected.pgn"))
        self.assertEqual(_OpenDialog.instances[-1].Title, "Open chess book")

    def test_dirty_exit_confirmation_uses_same_live_language_owner(self) -> None:
        owner = _Owner()
        language = {"value": UILanguage.UA}
        books = _Version2OwnedBookDialogs(
            lambda: owner,
            forms_loader=_forms_loader,
            message_box_loader=_message_box_loader,
            language_provider=lambda: language["value"],
        )

        self.assertTrue(books.confirm_discard_unsaved_pgn_on_exit())
        self.assertEqual(_MessageBox.calls[-1][0], owner)
        self.assertEqual(
            _MessageBox.calls[-1][1],
            "Поточний PGN має незбережені зміни. Вийти без збереження цих змін?",
        )
        self.assertEqual(_MessageBox.calls[-1][2], "Незбережені зміни PGN")

        language["value"] = UILanguage.EN
        self.assertTrue(books.confirm_discard_unsaved_pgn_on_exit())
        self.assertEqual(
            _MessageBox.calls[-1][1],
            "The current PGN has unsaved changes. Exit without saving these changes?",
        )
        self.assertEqual(_MessageBox.calls[-1][2], "Unsaved PGN changes")

    def test_host_runtime_projects_one_live_language_provider_to_both_dialog_ports(self) -> None:
        owner = _Owner()
        language = {"value": UILanguage.UA}
        runtime = Version2WindowsFileWorkflowRuntime(
            owner_control=owner,
            get_pgn_session=lambda: None,
            set_pgn_session=lambda session: None,
            import_services_factory=lambda: None,
            export_selected=lambda request, destination: None,
            import_ui_ready=lambda mailbox: None,
            pgn_export_event_sink=lambda event: None,
            next_delegate=lambda action_id, payload: None,
            current_focus_provider=lambda: "stable-focus",
            dialog_language_provider=lambda: language["value"],
            ui_delegate_factory=lambda callback: callback,
            file_forms_loader=_forms_loader,
            export_forms_loader=_forms_loader,
        )

        self.assertEqual(runtime.file_dialogs.open_pgn(), Path("selected.pgn"))
        self.assertEqual(_OpenDialog.instances[-1].Title, "Відкрити PGN")
        self.assertEqual(runtime.export_dialogs.export_selection(), Path("selection.pgn"))
        self.assertEqual(_SaveDialog.instances[-1].Title, "Експортувати вибране як PGN")

        language["value"] = UILanguage.EN
        self.assertEqual(runtime.file_dialogs.open_pgn(), Path("selected.pgn"))
        self.assertEqual(_OpenDialog.instances[-1].Title, "Open PGN")
        self.assertTrue(runtime.shutdown())

    def test_production_factory_binds_native_dialogs_to_live_v2_shell_language(self) -> None:
        """Lock the real composition seam, not only a synthetic provider contract."""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            layout = SimpleNamespace(
                root=root,
                settings_path=root / "settings.json",
                library_path=root / "library.acsdb",
            )
            settings = mock.Mock()
            settings.data = {"language": "uk"}
            settings.get.side_effect = lambda key, default=None: settings.data.get(key, default)
            engine_runtime = mock.Mock()
            engine_runtime.provider = mock.Mock()
            api = mock.MagicMock()
            application = mock.MagicMock()
            application.shell.language = UILanguage.UA
            application._native_unsaved_close_guard = None
            database = mock.MagicMock()
            native_runtime = mock.MagicMock()
            native_runtime.shutdown.return_value = True

            with (
                mock.patch.object(release_app, "_prepare_version2_user_data", return_value=layout),
                mock.patch.object(release_app, "Settings", return_value=settings),
                mock.patch.object(release_app, "AnalysisService", return_value=mock.MagicMock()),
                mock.patch.object(
                    release_app,
                    "EngineAssistedWorkflowService",
                    return_value=mock.MagicMock(),
                ),
                mock.patch.object(release_app, "ContinuousAnalysisService", return_value=mock.MagicMock()),
                mock.patch.object(release_app, "EnginePlayService", return_value=mock.MagicMock()),
                mock.patch.object(release_app, "SoundRuntime", return_value=mock.MagicMock()),
                mock.patch.object(release_app, "GameSoundRuntime", return_value=mock.MagicMock()),
                mock.patch.object(release_app, "Version2ReleaseAccessibleChessAPI", return_value=api),
                mock.patch.object(release_app, "AcsDatabase", return_value=database),
                mock.patch.object(release_app, "Version2Application", return_value=application),
                mock.patch.object(release_app, "_share_v2_action_registry"),
                mock.patch.object(
                    release_app,
                    "Version2WindowsFileWorkflowRuntime",
                    return_value=native_runtime,
                ) as runtime_class,
            ):
                _, returned_application, _, native_runtime_factory = (
                    release_app.create_version2_release_application(
                        runtime_factory=lambda _config: engine_runtime,
                        sound_playback=object(),
                    )
                )
                self.assertIs(returned_application, application)
                owner = _Owner()
                self.assertIs(native_runtime_factory(owner), native_runtime)
                self.assertEqual(len(owner.FormClosing.handlers), 1)

            provider = runtime_class.call_args.kwargs["dialog_language_provider"]
            self.assertEqual(provider(), UILanguage.UA)
            application.shell.language = UILanguage.EN
            self.assertEqual(provider(), UILanguage.EN)

    def test_language_projection_fails_safe_without_exposing_provider_exception(self) -> None:
        def broken_provider():
            raise RuntimeError("private language provider detail")

        owner = _Owner()
        dialogs = Version2OwnedWindowsFileDialogs(
            lambda: owner,
            forms_loader=_forms_loader,
            message_box_loader=_message_box_loader,
            language_provider=broken_provider,
        )
        exports = Version2OwnedWindowsPgnExportDialogs(
            lambda: owner,
            forms_loader=_forms_loader,
            language_provider=broken_provider,
        )
        books = _Version2OwnedBookDialogs(
            lambda: owner,
            forms_loader=_forms_loader,
            message_box_loader=_message_box_loader,
            language_provider=broken_provider,
        )

        self.assertEqual(dialogs.open_pgn(), Path("selected.pgn"))
        self.assertEqual(_OpenDialog.instances[-1].Title, "Open PGN")
        self.assertEqual(dialogs.save_pgn_as("game.pgn"), Path("game.pgn"))
        self.assertEqual(_SaveDialog.instances[-1].Title, "Save PGN As")
        self.assertEqual(dialogs.select_library_import(), Path("selected.pgn"))
        self.assertEqual(_OpenDialog.instances[-1].Title, "Import into Library")
        self.assertTrue(dialogs.confirm_discard_unsaved_pgn())
        self.assertEqual(_MessageBox.calls[-1][2], "Unsaved PGN changes")
        self.assertEqual(exports.export_selection(), Path("selection.pgn"))
        self.assertEqual(_SaveDialog.instances[-1].Title, "Export PGN selection")
        self.assertEqual(books.open_book(), Path("selected.pgn"))
        self.assertEqual(_OpenDialog.instances[-1].Title, "Open chess book")
        self.assertTrue(books.confirm_discard_unsaved_pgn_on_exit())
        self.assertEqual(_MessageBox.calls[-1][2], "Unsaved PGN changes")

        projected = "\n".join(
            [
                *[dialog.Title for dialog in _OpenDialog.instances],
                *[dialog.Filter for dialog in _OpenDialog.instances],
                *[dialog.Title for dialog in _SaveDialog.instances],
                *[dialog.Filter for dialog in _SaveDialog.instances],
                *[str(value) for call in _MessageBox.calls for value in call],
            ]
        )
        self.assertNotIn("private language provider detail", projected)

    def test_invalid_language_provider_contract_is_rejected(self) -> None:
        with self.assertRaisesRegex(TypeError, "language provider"):
            Version2WindowsDialogText("uk")  # type: ignore[arg-type]

        with self.assertRaisesRegex(TypeError, "dialog_language_provider"):
            Version2WindowsFileWorkflowRuntime(
                owner_control=_Owner(),
                get_pgn_session=lambda: None,
                set_pgn_session=lambda session: None,
                import_services_factory=lambda: None,
                export_selected=lambda request, destination: None,
                import_ui_ready=lambda mailbox: None,
                pgn_export_event_sink=lambda event: None,
                next_delegate=lambda action_id, payload: None,
                dialog_language_provider="uk",  # type: ignore[arg-type]
                ui_delegate_factory=lambda callback: callback,
            )


if __name__ == "__main__":
    unittest.main()
