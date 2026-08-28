from __future__ import annotations

from pathlib import Path
import threading
import unittest

from acs.version2_windows_native_dialog_ownership import (
    Version2OwnedWindowsFileDialogs,
    Version2OwnedWindowsPgnExportDialogs,
    Version2WinFormsDialogOwner,
)


class _Owner:
    def __init__(self) -> None:
        self.IsDisposed = False
        self.Disposing = False
        self.InvokeRequired = False


class _DialogResult:
    OK = "ok"


class _NativeDialog:
    instances: list["_NativeDialog"] = []

    def __init__(self) -> None:
        self.FileName = ""
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


def _forms_loader():
    return _DialogResult, _OpenDialog, _SaveDialog


class Version2WindowsNativeDialogOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        _OpenDialog.instances.clear()
        _SaveDialog.instances.clear()

    def test_file_dialogs_supply_exact_owner_for_open_save_and_import(self) -> None:
        owner = _Owner()
        dialogs = Version2OwnedWindowsFileDialogs(
            lambda: owner,
            forms_loader=_forms_loader,
        )

        opened = dialogs.open_pgn()
        saved = dialogs.save_pgn_as("private-source.pgn")
        imported = dialogs.select_library_import()

        self.assertEqual(opened, Path("selected.pgn"))
        self.assertEqual(saved, Path("selected.pgn"))
        self.assertEqual(imported, Path("selected.pgn"))
        self.assertEqual(len(_OpenDialog.instances), 2)
        self.assertEqual(len(_SaveDialog.instances), 1)
        for dialog in (*_OpenDialog.instances, *_SaveDialog.instances):
            self.assertEqual(dialog.show_args, (owner,))
            self.assertTrue(dialog.disposed)

    def test_export_dialog_uses_same_exact_owner_contract(self) -> None:
        owner = _Owner()
        dialogs = Version2OwnedWindowsPgnExportDialogs(
            lambda: owner,
            forms_loader=_forms_loader,
        )

        destination = dialogs.export_selection("selection.pgn")

        self.assertEqual(destination, Path("selected.pgn"))
        self.assertEqual(len(_SaveDialog.instances), 1)
        self.assertEqual(_SaveDialog.instances[0].show_args, (owner,))
        self.assertTrue(_SaveDialog.instances[0].disposed)

    def test_owner_provider_failure_never_falls_back_to_unowned_dialog(self) -> None:
        def broken_owner():
            raise RuntimeError("private host detail")

        dialogs = Version2OwnedWindowsFileDialogs(
            broken_owner,
            forms_loader=_forms_loader,
        )

        with self.assertRaisesRegex(RuntimeError, "owner is unavailable") as captured:
            dialogs.open_pgn()
        self.assertNotIn("private host detail", str(captured.exception))
        self.assertEqual(len(_OpenDialog.instances), 1)
        self.assertIsNone(_OpenDialog.instances[0].show_args)
        self.assertTrue(_OpenDialog.instances[0].disposed)

    def test_disposed_or_disposing_owner_fails_closed(self) -> None:
        for attribute in ("IsDisposed", "Disposing"):
            with self.subTest(attribute=attribute):
                owner = _Owner()
                setattr(owner, attribute, True)
                binding = Version2WinFormsDialogOwner(lambda: owner)
                with self.assertRaisesRegex(RuntimeError, "owner is unavailable"):
                    binding.resolve()

    def test_owner_binding_is_ui_thread_affine(self) -> None:
        owner = _Owner()
        binding = Version2WinFormsDialogOwner(lambda: owner)
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                binding.resolve()
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=worker, name="dialog-owner-wrong-thread")
        thread.start()
        thread.join(5.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertIn("UI thread", str(errors[0]))

    def test_owner_reporting_invoke_required_is_rejected(self) -> None:
        owner = _Owner()
        owner.InvokeRequired = True
        binding = Version2WinFormsDialogOwner(lambda: owner)

        with self.assertRaisesRegex(RuntimeError, "UI thread"):
            binding.resolve()


if __name__ == "__main__":
    unittest.main()
