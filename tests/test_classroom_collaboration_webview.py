from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.classroom_collaboration import ClassroomCollaborationController
from acs.classroom_collaboration_storage import (
    ChatMessageMetadata,
    ClassroomCollaborationSQLiteStore,
)
from acs.classroom_collaboration_webview import ClassroomCollaborationWebView
from acs.full_product_ui_shell import UILanguage
from tests.test_classroom_collaboration import FakeChat, FakeFiles, FakeFileStore, FakeRoster


class ClassroomCollaborationWebViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = ClassroomCollaborationSQLiteStore(str(self.root / "collaboration.sqlite3"))
        self.roster = FakeRoster()
        self.chat = FakeChat()
        self.files = FakeFiles()
        self.file_store = FakeFileStore()
        self.controller = ClassroomCollaborationController(
            room_id="room-1",
            local_participant_id="student-1",
            roster=self.roster,
            chat=self.chat,
            files=self.files,
            store=self.store,
            file_store=self.file_store,
        )
        self.labels = {
            "teacher-1": "Teacher",
            "co-1": "Co-teacher",
            "student-1": "Oleksii",
            "student-2": "Student two",
            "observer-1": "Observer",
        }
        self.ids: dict[str, int] = {}
        self.save_calls: list[tuple[str, str]] = []
        self.open_calls: list[tuple[str, str]] = []
        self.selected_file: Path | None = None

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def next_id(self, prefix: str) -> str:
        self.ids[prefix] = self.ids.get(prefix, 0) + 1
        return f"{prefix}-ui-{self.ids[prefix]}"

    def webview(self, *, language: UILanguage = UILanguage.EN) -> ClassroomCollaborationWebView:
        return ClassroomCollaborationWebView(
            self.controller,
            self.store,
            lambda participant_id: self.labels[participant_id],
            language=language,
            file_picker=lambda: self.selected_file,
            file_saver=lambda token, name: self.save_calls.append((token, name)),
            file_opener=lambda token, name: self.open_calls.append((token, name)),
            id_factory=self.next_id,
        )

    def test_chat_send_uses_host_generated_identity_and_never_accepts_browser_identity(self) -> None:
        view = self.webview()
        event = view.dispatch("collaboration.chat.send", {"body": "Hello"})
        self.assertEqual("collaboration.chat.sent", event.kind)
        self.assertEqual("collaboration-chat-input", event.payload["focus_target"])
        messages = self.store.room_messages("room-1")
        self.assertEqual(1, len(messages))
        self.assertEqual("message-ui-1", messages[0].message_id)
        self.assertEqual("Hello", messages[0].body)

        rejected = view.dispatch(
            "collaboration.chat.send",
            {"body": "Forged", "message_id": "browser-owned"},
        )
        self.assertEqual("error", rejected.kind)
        self.assertEqual(1, len(self.store.room_messages("room-1")))
        self.assertNotIn("browser-owned", repr(rejected.payload))

    def test_sync_marks_only_new_remote_messages_unread_and_announcement_has_no_focus_request(self) -> None:
        view = self.webview()
        view.dispatch("collaboration.chat.send", {"body": "Local"})
        self.chat.ordered.append(
            ChatMessageMetadata(
                "remote-message-1",
                "room-1",
                "student-2",
                1,
                "Remote answer",
            )
        )
        event = view.dispatch("collaboration.chat.sync", {})
        self.assertEqual("collaboration.chat.synced", event.kind)
        self.assertEqual("Student two: Remote answer", event.payload["announcement"])
        self.assertNotIn("focus_target", event.payload)
        self.assertEqual(1, event.payload["collaboration"]["chat"]["unread_count"])

        read = view.dispatch("collaboration.chat.mark_read", {})
        self.assertEqual(0, read.payload["collaboration"]["chat"]["unread_count"])

    def test_snapshot_projects_safe_ordered_metadata_without_internal_ids(self) -> None:
        view = self.webview()
        view.dispatch("collaboration.chat.send", {"body": "One"})
        self.chat.ordered.append(
            ChatMessageMetadata("remote-message-2", "room-1", "teacher-1", 1, "Two")
        )
        view.dispatch("collaboration.chat.sync", {})
        snapshot = view.snapshot()
        messages = snapshot["chat"]["messages"]
        self.assertEqual(["One", "Two"], [item["body"] for item in messages])
        self.assertEqual(["Oleksii", "Teacher"], [item["sender"] for item in messages])
        exposed = repr(snapshot)
        for internal in ("student-1", "teacher-1", "message-ui-1", "remote-message-2"):
            self.assertNotIn(internal, exposed)

    def test_file_upload_and_save_keep_local_path_object_key_hash_and_token_out_of_browser(self) -> None:
        self.selected_file = self.root / "lesson notes.txt"
        self.selected_file.write_text("accessible classroom file", encoding="utf-8")
        self.files.scan_state = "clean"
        view = self.webview()

        uploaded = view.dispatch("collaboration.file.choose_upload", {})
        self.assertEqual("collaboration.file.sent", uploaded.kind)
        file_item = uploaded.payload["collaboration"]["files"]["items"][0]
        self.assertEqual("lesson notes.txt", file_item["name"])
        self.assertTrue(file_item["can_save"])
        self.assertTrue(file_item["can_open"])
        exposed = repr(uploaded.payload)
        self.assertNotIn(str(self.root), exposed)
        self.assertNotIn("rooms/room-1", exposed)
        self.assertNotIn("short-lived-read-token", exposed)
        self.assertNotIn("sha256", exposed.lower())

        saved = view.dispatch(
            "collaboration.file.save",
            {"file_key": file_item["file_key"]},
        )
        self.assertEqual("collaboration.file.saved", saved.kind)
        self.assertEqual(
            [("short-lived-read-token", "lesson notes.txt")],
            self.save_calls,
        )
        self.assertNotIn("short-lived-read-token", repr(saved.payload))

        opened = view.dispatch(
            "collaboration.file.open",
            {"file_key": file_item["file_key"]},
        )
        self.assertEqual("collaboration.file.opened", opened.kind)
        self.assertEqual(
            [("short-lived-read-token", "lesson notes.txt")],
            self.open_calls,
        )
        self.assertNotIn("short-lived-read-token", repr(opened.payload))

    def test_teacher_moderation_uses_core_permissions_without_browser_participant_ids(self) -> None:
        teacher_chat = FakeChat()
        teacher_controller = ClassroomCollaborationController(
            room_id="room-1",
            local_participant_id="teacher-1",
            roster=self.roster,
            chat=teacher_chat,
            files=FakeFiles(),
            store=self.store,
            file_store=self.file_store,
        )
        teacher_controller.receive_chat(
            ChatMessageMetadata(
                "student-message-1",
                "room-1",
                "student-2",
                0,
                "Please moderate this",
            )
        )
        view = ClassroomCollaborationWebView(
            teacher_controller,
            self.store,
            lambda participant_id: self.labels[participant_id],
            language=UILanguage.EN,
            moderation_allowed=lambda: True,
            id_factory=self.next_id,
        )
        message = view.snapshot()["chat"]["messages"][0]
        self.assertTrue(message["can_hide"])
        self.assertTrue(message["can_moderate_sender"])
        self.assertNotIn("student-2", repr(message))
        message_key = message["message_key"]

        muted = view.dispatch(
            "collaboration.chat.mute_sender",
            {"message_key": message_key},
        )
        self.assertEqual("collaboration.chat.permission", muted.kind)
        self.assertEqual("student-2", teacher_chat.moderation_calls[-1][0].target_id)
        self.assertFalse(teacher_chat.moderation_calls[-1][0].allowed)

        allowed = view.dispatch(
            "collaboration.chat.allow_sender",
            {"message_key": message_key},
        )
        self.assertEqual("collaboration.chat.permission", allowed.kind)
        self.assertTrue(teacher_chat.moderation_calls[-1][0].allowed)

        all_muted = view.dispatch("collaboration.chat.mute_all_students", {})
        self.assertEqual("collaboration.chat.permission", all_muted.kind)
        self.assertEqual(
            {"student-1", "student-2"},
            {item.target_id for item in teacher_chat.moderation_calls[-1]},
        )

        hidden = view.dispatch(
            "collaboration.chat.hide",
            {"message_key": message_key},
        )
        self.assertEqual("collaboration.chat.hidden", hidden.kind)
        self.assertEqual((), self.store.room_messages("room-1"))

    def test_non_moderator_snapshot_does_not_expose_message_action_key(self) -> None:
        view = self.webview()
        view.dispatch("collaboration.chat.send", {"body": "Local"})
        message = view.snapshot()["chat"]["messages"][0]
        self.assertFalse(message["can_hide"])
        self.assertFalse(message["can_moderate_sender"])
        self.assertNotIn("message_key", message)

    def test_failed_upload_exposes_bounded_retry_without_browser_path(self) -> None:
        self.selected_file = self.root / "retry.pgn"
        self.selected_file.write_text('[Event "Test"]\n\n1. e4 e5 *\n', encoding="utf-8")
        self.files.fail_upload = True
        view = self.webview()

        failed = view.dispatch("collaboration.file.choose_upload", {})
        self.assertEqual("error", failed.kind)
        item = failed.payload["collaboration"]["files"]["items"][0]
        self.assertTrue(item["can_retry"])
        self.assertNotIn(str(self.selected_file), repr(failed.payload))

        self.files.fail_upload = False
        retried = view.dispatch("collaboration.file.retry", {"file_key": item["file_key"]})
        self.assertEqual("collaboration.file.retried", retried.kind)
        self.assertFalse(retried.payload["collaboration"]["files"]["items"][0]["can_retry"])
        self.assertEqual(1, len(self.files.retry_calls))

    def test_file_action_key_is_room_bound_and_unknown_or_extra_payload_fails_closed(self) -> None:
        view = self.webview()
        bad = view.dispatch("collaboration.file.save", {"file_key": "0" * 64})
        self.assertEqual("error", bad.kind)
        extra = view.dispatch(
            "collaboration.file.choose_upload",
            {"path": "C:/secret/file.pgn"},
        )
        self.assertEqual("error", extra.kind)
        self.assertNotIn("C:/secret", repr(extra.payload))

    def test_language_switch_changes_presentation_without_rebuilding_core(self) -> None:
        view = self.webview(language=UILanguage.EN)
        self.assertEqual("Chat", view.snapshot()["chat"]["heading"])
        view.set_language(UILanguage.UA)
        self.assertEqual("Чат", view.snapshot()["chat"]["heading"])


if __name__ == "__main__":
    unittest.main()
