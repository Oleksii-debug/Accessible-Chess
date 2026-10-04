from __future__ import annotations

import unittest
from unittest import mock

from acs.acsdb import AcsDatabase
from acs.full_product_ui_shell import UILanguage
from acs.library_export_service import LibraryExportService
import acs.version2_windows_library_export as library_export_host


class Version2LibraryExportDialogLanguageTests(unittest.TestCase):
    def test_builder_forwards_one_live_language_provider_to_all_native_dialogs(self) -> None:
        database = AcsDatabase()
        try:
            service = LibraryExportService(database)
            language = {"value": UILanguage.UA}
            provider = lambda: language["value"]
            dialogs = mock.MagicMock()
            runtime = mock.MagicMock()

            with (
                mock.patch.object(
                    library_export_host,
                    "Version2OwnedWindowsPgnExportDialogs",
                    return_value=dialogs,
                ) as dialog_class,
                mock.patch.object(
                    library_export_host,
                    "Version2WindowsFileWorkflowRuntime",
                    return_value=runtime,
                ) as runtime_class,
            ):
                result = library_export_host.build_version2_windows_library_file_runtime(
                    owner_control=object(),
                    library_service=service,
                    library_export_event_sink=lambda event: None,
                    get_pgn_session=lambda: None,
                    set_pgn_session=lambda session: None,
                    import_services_factory=lambda: None,
                    export_selected=lambda request, destination: None,
                    import_ui_ready=lambda mailbox: None,
                    pgn_export_event_sink=lambda event: None,
                    next_delegate=lambda action_id, payload: None,
                    dialog_language_provider=provider,
                )

            self.assertIs(result, runtime)
            self.assertIs(dialog_class.call_args.kwargs["language_provider"], provider)
            self.assertIs(runtime_class.call_args.kwargs["dialog_language_provider"], provider)
            self.assertEqual(provider(), UILanguage.UA)
            language["value"] = UILanguage.EN
            self.assertEqual(provider(), UILanguage.EN)
        finally:
            database.close()

    def test_builder_rejects_non_callable_language_provider_before_host_construction(self) -> None:
        database = AcsDatabase()
        try:
            service = LibraryExportService(database)
            with self.assertRaisesRegex(TypeError, "dialog_language_provider"):
                library_export_host.build_version2_windows_library_file_runtime(
                    owner_control=object(),
                    library_service=service,
                    library_export_event_sink=lambda event: None,
                    get_pgn_session=lambda: None,
                    set_pgn_session=lambda session: None,
                    import_services_factory=lambda: None,
                    export_selected=lambda request, destination: None,
                    import_ui_ready=lambda mailbox: None,
                    pgn_export_event_sink=lambda event: None,
                    next_delegate=lambda action_id, payload: None,
                    dialog_language_provider="uk",  # type: ignore[arg-type]
                )
        finally:
            database.close()


if __name__ == "__main__":
    unittest.main()
