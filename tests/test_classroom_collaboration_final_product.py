from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from acs.classroom_collaboration import ClassroomCollaborationController
from acs.classroom_collaboration_storage import ClassroomCollaborationSQLiteStore
from acs.classroom_collaboration_webview import ClassroomCollaborationWebView
from acs.full_product_ui_shell import UILanguage
from acs.version2_final_product_application import Version2FinalProductApplication
from tests.test_classroom_collaboration import FakeChat, FakeFiles, FakeFileStore, FakeRoster


class ClassroomCollaborationFinalProductTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = ClassroomCollaborationSQLiteStore(str(root / "collaboration.sqlite3"))
        controller = ClassroomCollaborationController(
            room_id="room-1",
            local_participant_id="student-1",
            roster=FakeRoster(),
            chat=FakeChat(),
            files=FakeFiles(),
            store=self.store,
            file_store=FakeFileStore(),
        )
        self.ids = 0

        def next_id(prefix: str) -> str:
            self.ids += 1
            return f"{prefix}-composition-{self.ids}"

        self.collaboration = ClassroomCollaborationWebView(
            controller,
            self.store,
            lambda participant_id: "Local student",
            language=UILanguage.EN,
            id_factory=next_id,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def bare_app() -> Version2FinalProductApplication:
        app = object.__new__(Version2FinalProductApplication)
        app.collaboration = None
        app.education = None
        app.teacher = None
        app.shell = SimpleNamespace(language=UILanguage.EN)
        return app

    def test_trusted_binding_is_single_owner_and_unbind_does_not_mutate_store(self) -> None:
        app = self.bare_app()
        with mock.patch.object(Version2FinalProductApplication, "_assert_thread"):
            app.bind_classroom_collaboration(self.collaboration)
            self.assertIs(app.collaboration, self.collaboration)
            with self.assertRaises(RuntimeError):
                app.bind_classroom_collaboration(self.collaboration)
            app.unbind_classroom_collaboration()
        self.assertIsNone(app.collaboration)
        self.assertEqual((), self.store.room_messages("room-1"))

    def test_classes_browser_area_routes_only_collaboration_prefix_to_collaboration_boundary(self) -> None:
        app = self.bare_app()
        app.collaboration = self.collaboration
        with mock.patch.object(Version2FinalProductApplication, "_assert_thread"):
            event = app.browser_command(
                "classes",
                "collaboration.chat.send",
                {"body": "Reachable from final Classes"},
            )
        self.assertEqual("collaboration.chat.sent", event["kind"])
        self.assertEqual(
            "Reachable from final Classes",
            self.store.room_messages("room-1")[0].body,
        )

    def test_education_snapshot_nests_collaboration_without_replacing_d10_projection(self) -> None:
        app = self.bare_app()
        app.collaboration = self.collaboration
        app.education = SimpleNamespace(
            projection=SimpleNamespace(
                snapshot=lambda: {
                    "document": {"lang": "en", "heading": "Classes"},
                    "sections": ({"kind": "class", "items": ()},),
                    "detail": None,
                }
            )
        )
        snapshot = app._education_browser_snapshot()
        self.assertEqual("Classes", snapshot["document"]["heading"])
        self.assertEqual("Chat", snapshot["collaboration"]["chat"]["heading"])
        self.assertEqual("class", snapshot["sections"][0]["kind"])


if __name__ == "__main__":
    unittest.main()
