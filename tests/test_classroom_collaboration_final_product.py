from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from acs.classroom_collaboration import (
    ClassroomCollaborationController,
    FileTransferProgress,
)
from acs.classroom_collaboration_storage import (
    AttachmentMetadata,
    ChatMessageMetadata,
    ClassroomCollaborationSQLiteStore,
)
from acs.classroom_collaboration_webview import (
    ClassroomCollaborationWebView,
    ClassroomCollaborationWebViewEvent,
)
from acs.full_product_ui_shell import UILanguage
from acs.version2_final_product_application import Version2FinalProductApplication
from tests.test_classroom_collaboration import FakeChat, FakeFiles, FakeFileStore, FakeRoster


class ClassroomCollaborationFinalProductTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = ClassroomCollaborationSQLiteStore(str(root / "collaboration.sqlite3"))
        self.files = FakeFiles()
        controller = ClassroomCollaborationController(
            room_id="room-1",
            local_participant_id="student-1",
            roster=FakeRoster(),
            chat=FakeChat(),
            files=self.files,
            store=self.store,
            file_store=FakeFileStore(),
        )
        self.ids = 0

        def next_id(prefix: str) -> str:
            self.ids += 1
            return f"{prefix}-composition-{self.ids}"

        labels = {
            "student-1": "Local student",
            "student-2": "Student two",
            "teacher-1": "Teacher",
            "co-1": "Co-teacher",
            "observer-1": "Observer",
        }
        self.collaboration = ClassroomCollaborationWebView(
            controller,
            self.store,
            lambda participant_id: labels.get(participant_id, "Participant"),
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
        pending_fingerprint = self.collaboration._chat_draft_fingerprint("Draft")
        self.collaboration._pending_chat = {
            pending_fingerprint: "pending-before-unbind",
        }
        self.collaboration._unread_message_ids.add("unread-before-unbind")
        with (
            mock.patch.object(Version2FinalProductApplication, "_assert_thread"),
            mock.patch.object(
                self.collaboration,
                "retire_browser_session",
                wraps=self.collaboration.retire_browser_session,
            ) as retire,
        ):
            app.bind_classroom_collaboration(self.collaboration)
            self.assertIs(app.collaboration, self.collaboration)
            with self.assertRaises(RuntimeError):
                app.bind_classroom_collaboration(self.collaboration)
            app.unbind_classroom_collaboration()
        retire.assert_called_once_with()
        self.assertIsNone(app.collaboration)
        self.assertEqual(
            {pending_fingerprint: "pending-before-unbind"},
            self.collaboration._pending_chat,
        )
        self.assertNotIn("Draft", repr(self.collaboration._pending_chat))
        self.assertEqual(set(), self.collaboration._unread_message_ids)
        self.assertEqual((), self.store.room_messages("room-1"))

    def test_binding_can_bridge_file_progress_events_to_the_trusted_host(self) -> None:
        app = self.bare_app()
        bridged = []
        with (
            mock.patch.object(Version2FinalProductApplication, "_assert_thread"),
            mock.patch.object(
                self.collaboration,
                "set_file_progress_event_sink",
            ) as set_sink,
        ):
            app.bind_classroom_collaboration(
                self.collaboration,
                file_progress_event_sink=bridged.append,
            )

        set_sink.assert_called_once()
        sink = set_sink.call_args.args[0]
        sink(
            ClassroomCollaborationWebViewEvent(
                "collaboration.file.progress",
                {
                    "file_progress": {
                        "session_key": "session",
                        "transferred_bytes": 1,
                        "total_bytes": 2,
                        "complete": False,
                    }
                },
            )
        )
        self.assertEqual("collaboration.file.progress", bridged[0]["kind"])
        self.assertEqual(1, bridged[0]["payload"]["file_progress"]["transferred_bytes"])

    def test_bound_classes_upload_streams_progress_to_trusted_host(self) -> None:
        selected = Path(self.tmp.name) / "whole-product-progress.bin"
        selected.write_bytes(b"abcdef")
        self.collaboration._file_picker = lambda: selected
        self.files.scan_state = "clean"
        self.files.progress_samples = (
            FileTransferProgress("attachment-composition-1", 6, 6),
        )
        bridged: list[dict[str, object]] = []
        app = self.bare_app()

        with mock.patch.object(Version2FinalProductApplication, "_assert_thread"):
            app.bind_classroom_collaboration(
                self.collaboration,
                file_progress_event_sink=bridged.append,
            )
            uploaded = app.browser_command(
                "classes",
                "collaboration.file.choose_upload",
                {},
            )
            app.unbind_classroom_collaboration()

        self.assertEqual("collaboration.file.sent", uploaded["kind"])
        self.assertEqual(
            [0, 6, 6],
            [
                event["payload"]["file_progress"]["transferred_bytes"]
                for event in bridged
            ],
        )
        self.assertEqual(
            [False, False, True],
            [event["payload"]["file_progress"]["complete"] for event in bridged],
        )
        self.assertEqual(
            "All bytes transferred; finalizing transfer: whole-product-progress.bin.",
            bridged[-2]["payload"]["file_progress"]["text"],
        )
        self.assertEqual(
            "Transferred 6 B of 6 B: whole-product-progress.bin.",
            bridged[-1]["payload"]["file_progress"]["text"],
        )
        transfer_keys = {
            event["payload"]["file_progress"]["transfer_key"]
            for event in bridged
        }
        self.assertEqual(1, len(transfer_keys))
        self.assertEqual(64, len(next(iter(transfer_keys))))
        exposed = repr(bridged)
        self.assertNotIn(str(selected), exposed)
        self.assertNotIn("attachment-composition-", exposed)
        self.assertNotIn("rooms/room-1", exposed)
        self.assertNotIn("sha256", exposed.lower())

    def test_host_unbind_during_progress_stops_old_channel_without_failing_upload(self) -> None:
        selected = Path(self.tmp.name) / "unbind-during-progress.bin"
        selected.write_bytes(b"abcdefghij")
        self.collaboration._file_picker = lambda: selected
        self.files.scan_state = "clean"
        self.files.progress_samples = (
            FileTransferProgress("attachment-composition-1", 4, 10),
            FileTransferProgress("attachment-composition-1", 8, 10),
        )
        bridged: list[dict[str, object]] = []
        app = self.bare_app()

        def unbind_on_first_progress(event):
            bridged.append(event)
            app.unbind_classroom_collaboration()

        with mock.patch.object(Version2FinalProductApplication, "_assert_thread"):
            app.bind_classroom_collaboration(
                self.collaboration,
                file_progress_event_sink=unbind_on_first_progress,
            )
            uploaded = app.browser_command(
                "classes",
                "collaboration.file.choose_upload",
                {},
            )

        self.assertEqual("collaboration.file.sent", uploaded["kind"])
        self.assertIsNone(app.collaboration)
        self.assertEqual(1, len(bridged))
        self.assertEqual(
            0,
            bridged[0]["payload"]["file_progress"]["transferred_bytes"],
        )
        self.assertIsNone(self.collaboration._file_progress_event_sink)
        self.assertIsNone(self.collaboration._file_progress_attempt_token)
        self.assertIsNone(self.collaboration._file_progress)
        self.assertEqual(
            "stored",
            self.store.room_attachments("room-1")[0].transfer_state,
        )
        self.assertNotIn(str(selected), repr(uploaded))

    def test_binding_without_progress_sink_clears_preexisting_observer(self) -> None:
        app = self.bare_app()
        retired_events: list[ClassroomCollaborationWebViewEvent] = []
        self.collaboration.set_file_progress_event_sink(retired_events.append)
        self.assertIsNotNone(self.collaboration._file_progress_event_sink)

        with mock.patch.object(Version2FinalProductApplication, "_assert_thread"):
            app.bind_classroom_collaboration(self.collaboration)
            self.assertIsNone(self.collaboration._file_progress_event_sink)
            app.unbind_classroom_collaboration()

        self.assertEqual([], retired_events)

    def test_rebind_without_progress_sink_does_not_reuse_retired_host_channel(self) -> None:
        app = self.bare_app()
        old_channel_events: list[dict[str, object]] = []
        with mock.patch.object(Version2FinalProductApplication, "_assert_thread"):
            app.bind_classroom_collaboration(
                self.collaboration,
                file_progress_event_sink=old_channel_events.append,
            )
            self.assertIsNotNone(self.collaboration._file_progress_event_sink)
            app.unbind_classroom_collaboration()
            self.assertIsNone(self.collaboration._file_progress_event_sink)

            # Reusing the same collaboration object without a new host observer
            # must not silently resurrect the retired browser/channel binding.
            app.bind_classroom_collaboration(self.collaboration)
            self.assertIsNone(self.collaboration._file_progress_event_sink)
            app.unbind_classroom_collaboration()

        self.assertEqual([], old_channel_events)

    def test_trusted_host_can_project_live_chat_and_file_without_browser_authority(self) -> None:
        app = self.bare_app()
        with mock.patch.object(Version2FinalProductApplication, "_assert_thread"):
            app.bind_classroom_collaboration(self.collaboration)
            chat_event = app.receive_classroom_chat(
                ChatMessageMetadata(
                    "live-final-chat",
                    "room-1",
                    "student-2",
                    0,
                    "Live final chat",
                    sent_at_unix_ms=1700000000000,
                )
            )
            file_event = app.receive_classroom_file(
                AttachmentMetadata(
                    "live-final-file",
                    "room-1",
                    "student-2",
                    0,
                    "live-final.pgn",
                    "application/x-chess-pgn",
                    4,
                    "0" * 64,
                    "rooms/room-1/live-final-file",
                    "stored",
                    scan_state="clean",
                )
            )

        self.assertEqual("collaboration.chat.received", chat_event["kind"])
        self.assertEqual("Student two: Live final chat", chat_event["payload"]["announcement"])
        self.assertEqual(
            1,
            chat_event["payload"]["collaboration"]["chat"]["unread_count"],
        )
        self.assertEqual("collaboration.file.received", file_event["kind"])
        self.assertEqual("New file: live-final.pgn.", file_event["payload"]["announcement"])
        self.assertEqual(
            "live-final.pgn",
            file_event["payload"]["collaboration"]["files"]["items"][0]["name"],
        )

    def test_trusted_live_ingress_requires_bound_collaboration(self) -> None:
        app = self.bare_app()
        message = ChatMessageMetadata(
            "unbound-live-chat",
            "room-1",
            "student-2",
            0,
            "No binding",
            sent_at_unix_ms=1700000000000,
        )
        attachment = AttachmentMetadata(
            "unbound-live-file",
            "room-1",
            "student-2",
            0,
            "unbound.pgn",
            "application/x-chess-pgn",
            4,
            "0" * 64,
            "rooms/room-1/unbound-live-file",
            "stored",
            scan_state="clean",
        )
        with mock.patch.object(Version2FinalProductApplication, "_assert_thread"):
            with self.assertRaises(RuntimeError):
                app.receive_classroom_chat(message)
            with self.assertRaises(RuntimeError):
                app.receive_classroom_file(attachment)

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

    def test_classes_browser_area_reaches_remote_file_sync(self) -> None:
        self.files.ordered.append(
            AttachmentMetadata(
                "remote-final-product-file",
                "room-1",
                "student-2",
                0,
                "shared.pgn",
                "application/x-chess-pgn",
                4,
                "0" * 64,
                "rooms/room-1/remote-final-product-file",
                "stored",
                scan_state="clean",
            )
        )
        app = self.bare_app()
        app.collaboration = self.collaboration
        with mock.patch.object(Version2FinalProductApplication, "_assert_thread"):
            event = app.browser_command("classes", "collaboration.file.sync", {})
        self.assertEqual("collaboration.files.synced", event["kind"])
        self.assertEqual(
            "shared.pgn",
            event["payload"]["collaboration"]["files"]["items"][0]["name"],
        )

    def test_classes_non_text_command_fails_closed_before_collaboration_prefix_check(self) -> None:
        app = self.bare_app()
        with (
            mock.patch.object(Version2FinalProductApplication, "_assert_thread"),
            mock.patch.object(
                Version2FinalProductApplication,
                "_error",
                return_value={"kind": "error", "payload": {"message": "safe"}},
            ),
        ):
            event = app.browser_command("classes", None, {})
        self.assertEqual("error", event["kind"])

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
