from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.classroom_collaboration import ClassroomCollaborationController
from acs.classroom_collaboration_storage import (
    AttachmentMetadata,
    ChatMessageMetadata,
    ClassroomCollaborationSQLiteStore,
)
from acs.classroom_collaboration_webview import ClassroomCollaborationWebView
from acs.classroom_realtime_media import ClassroomMediaController
from acs.full_product_ui_shell import UILanguage
from tests.test_classroom_collaboration import FakeChat, FakeFiles, FakeFileStore, FakeRoster
from tests.test_classroom_realtime_media import FakeMedia


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
                sent_at_unix_ms=1700000001000,
            )
        )
        event = view.dispatch("collaboration.chat.sync", {})
        self.assertEqual("collaboration.chat.synced", event.kind)
        self.assertEqual("Student two: Remote answer", event.payload["announcement"])
        self.assertNotIn("UTC", event.payload["announcement"])
        self.assertNotIn("focus_target", event.payload)
        self.assertEqual(1, event.payload["collaboration"]["chat"]["unread_count"])

        read = view.dispatch("collaboration.chat.mark_read", {})
        self.assertEqual(0, read.payload["collaboration"]["chat"]["unread_count"])
        self.assertEqual("collaboration-chat-sync", read.payload["focus_target"])

    def test_sync_sanitizes_controls_only_in_live_announcement(self) -> None:
        view = self.webview()
        view.dispatch("collaboration.chat.send", {"body": "Local"})
        body = "Visible\u202Egnp\u200b\n next"
        self.chat.ordered.append(
            ChatMessageMetadata(
                "remote-announcement-control",
                "room-1",
                "student-2",
                1,
                body,
                sent_at_unix_ms=1700000001000,
            )
        )

        event = view.dispatch("collaboration.chat.sync", {})

        self.assertEqual(
            "Student two: Visiblegnp next",
            event.payload["announcement"],
        )
        messages = event.payload["collaboration"]["chat"]["messages"]
        self.assertEqual(body, messages[-1]["body"])
        self.assertNotIn("\u202E", event.payload["announcement"])
        self.assertNotIn("\u200b", event.payload["announcement"])

    def test_snapshot_projects_safe_ordered_metadata_without_internal_ids(self) -> None:
        view = self.webview()
        view.dispatch("collaboration.chat.send", {"body": "One"})
        self.chat.ordered.append(
            ChatMessageMetadata(
                "remote-message-2",
                "room-1",
                "teacher-1",
                1,
                "Two",
                sent_at_unix_ms=1700000001000,
            )
        )
        view.dispatch("collaboration.chat.sync", {})
        snapshot = view.snapshot()
        messages = snapshot["chat"]["messages"]
        self.assertEqual(["One", "Two"], [item["body"] for item in messages])
        self.assertEqual(["Oleksii", "Teacher"], [item["sender"] for item in messages])
        self.assertEqual(
            ["2023-11-14 22:13:20 UTC", "2023-11-14 22:13:21 UTC"],
            [item["timestamp_text"] for item in messages],
        )
        self.assertEqual(
            ["2023-11-14T22:13:20Z", "2023-11-14T22:13:21Z"],
            [item["timestamp_datetime"] for item in messages],
        )
        self.assertEqual("Message time", snapshot["chat"]["timestamp_label"])
        exposed = repr(snapshot)
        for internal in ("student-1", "teacher-1", "message-ui-1", "remote-message-2"):
            self.assertNotIn(internal, exposed)

    def test_participant_label_strips_bidi_and_control_formatting(self) -> None:
        self.labels["student-2"] = "Stu\u202Edent\u200b\n Name"
        self.store.append_message(
            ChatMessageMetadata(
                "remote-label-message",
                "room-1",
                "student-2",
                0,
                "Visible body",
                sent_at_unix_ms=1700000000000,
            )
        )

        message = self.webview().snapshot()["chat"]["messages"][0]
        self.assertEqual("Student Name", message["sender"])
        self.assertNotIn("\u202E", repr(message))
        self.assertNotIn("\u200b", repr(message))

    def test_legacy_persisted_message_does_not_invent_timestamp(self) -> None:
        self.store.append_message(
            ChatMessageMetadata("legacy-message", "room-1", "teacher-1", 0, "Legacy")
        )
        message = self.webview().snapshot()["chat"]["messages"][0]
        self.assertNotIn("timestamp_text", message)
        self.assertNotIn("timestamp_datetime", message)

    def test_file_sync_surfaces_new_remote_file_once_without_focus_request(self) -> None:
        remote = AttachmentMetadata(
            "remote-clean-file",
            "room-1",
            "student-2",
            0,
            "lesson.pgn",
            "application/x-chess-pgn",
            4,
            "0" * 64,
            "rooms/room-1/remote-clean-file",
            "stored",
            scan_state="clean",
        )
        self.files.ordered.append(remote)
        view = self.webview()

        event = view.dispatch("collaboration.file.sync", {})
        self.assertEqual("collaboration.files.synced", event.kind)
        self.assertEqual("New file: lesson.pgn.", event.payload["announcement"])
        self.assertNotIn("focus_target", event.payload)
        files = event.payload["collaboration"]["files"]["items"]
        self.assertEqual(1, len(files))
        self.assertEqual("lesson.pgn", files[0]["name"])
        self.assertTrue(files[0]["can_save"])
        self.assertTrue(files[0]["can_open"])
        self.assertIn("file_key", files[0])

        repeated = view.dispatch("collaboration.file.sync", {})
        self.assertEqual("collaboration.files.synced", repeated.kind)
        self.assertNotIn("announcement", repeated.payload)
        self.assertEqual(1, len(repeated.payload["collaboration"]["files"]["items"]))

    def test_file_sync_announces_existing_file_state_change_without_focus_request(self) -> None:
        self.store.register_attachment(
            AttachmentMetadata(
                "remote-scanning-file",
                "room-1",
                "student-2",
                0,
                "scanning.pgn",
                "application/x-chess-pgn",
                4,
                "0" * 64,
                "rooms/room-1/remote-scanning-file",
                "stored",
                scan_state="pending",
            )
        )
        view = self.webview()

        def complete_scan():
            self.store.update_attachment_state(
                "remote-scanning-file",
                scan_state="clean",
            )
            return ()

        with mock.patch.object(self.controller, "sync_files", side_effect=complete_scan):
            event = view.dispatch("collaboration.file.sync", {})

        self.assertEqual("collaboration.files.synced", event.kind)
        self.assertEqual(
            "File status updated: scanning.pgn.",
            event.payload["announcement"],
        )
        self.assertNotIn("focus_target", event.payload)
        item = event.payload["collaboration"]["files"]["items"][0]
        self.assertEqual("Scan: clean", item["scan_label"])
        self.assertTrue(item["can_save"])
        self.assertTrue(item["can_open"])

    def test_file_sync_rejects_browser_fields_without_transport_call(self) -> None:
        view = self.webview()
        event = view.dispatch("collaboration.file.sync", {"after": 0})
        self.assertEqual("error", event.kind)
        self.assertEqual([], self.files.ordered)

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

    def test_nonretriable_upload_failure_does_not_retain_local_source_path(self) -> None:
        self.selected_file = self.root / "nonretriable.pgn"
        self.selected_file.write_text('[Event "No retry"]\n\n1. e4 e5 *\n', encoding="utf-8")
        view = self.webview()

        with mock.patch.object(
            self.controller,
            "upload_file",
            side_effect=RuntimeError("failed before canonical attachment registration"),
        ):
            event = view.dispatch("collaboration.file.choose_upload", {})

        self.assertEqual("error", event.kind)
        self.assertEqual({}, view._prepared)
        self.assertEqual((), self.store.room_attachments("room-1"))
        self.assertNotIn(str(self.selected_file), repr(event.payload))

    def test_teacher_moderation_uses_core_permissions_without_browser_participant_ids(self) -> None:
        teacher_chat = FakeChat()
        teacher_media = FakeMedia()
        participant_moderation = ClassroomMediaController(
            local_participant_id="teacher-1",
            roster=self.roster,
            media=teacher_media,
        )
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
                sent_at_unix_ms=1700000000000,
            )
        )
        view = ClassroomCollaborationWebView(
            teacher_controller,
            self.store,
            lambda participant_id: self.labels[participant_id],
            language=UILanguage.EN,
            moderation_allowed=lambda: True,
            participant_moderation=participant_moderation,
            id_factory=self.next_id,
        )
        message = view.snapshot()["chat"]["messages"][0]
        self.assertTrue(message["can_hide"])
        self.assertTrue(message["can_moderate_sender"])
        self.assertTrue(message["can_remove_sender"])
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

        blocked = view.dispatch(
            "collaboration.participant.block_sender",
            {"message_key": message_key},
        )
        self.assertEqual("collaboration.participant.removed", blocked.kind)
        self.assertTrue(teacher_media.moderation_calls[-1][0].value)
        self.assertEqual("student-2", teacher_media.moderation_calls[-1][0].target_id)
        self.assertNotIn("student-2", repr(blocked.payload))
        self.assertEqual("collaboration-chat-sync", blocked.payload["focus_target"])
        blocked_message = blocked.payload["collaboration"]["chat"]["messages"][0]
        self.assertFalse(blocked_message["can_moderate_sender"])
        self.assertFalse(blocked_message["can_remove_sender"])

        hidden = view.dispatch(
            "collaboration.chat.hide",
            {"message_key": message_key},
        )
        self.assertEqual("collaboration.chat.hidden", hidden.kind)
        self.assertEqual("collaboration-chat-sync", hidden.payload["focus_target"])
        self.assertEqual((), self.store.room_messages("room-1"))

    def test_departed_sender_history_has_no_stale_sender_moderation_actions(self) -> None:
        teacher_chat = FakeChat()
        teacher_media = FakeMedia()
        participant_moderation = ClassroomMediaController(
            local_participant_id="teacher-1",
            roster=self.roster,
            media=teacher_media,
        )
        teacher_controller = ClassroomCollaborationController(
            room_id="room-1",
            local_participant_id="teacher-1",
            roster=self.roster,
            chat=teacher_chat,
            files=FakeFiles(),
            store=self.store,
            file_store=self.file_store,
        )
        historical = ChatMessageMetadata(
            "departed-message",
            "room-1",
            "student-2",
            0,
            "Historical contribution",
            sent_at_unix_ms=1700000000000,
        )
        teacher_chat.ordered.append(historical)
        teacher_controller.sync_chat()
        self.roster.roles.pop("student-2")

        view = ClassroomCollaborationWebView(
            teacher_controller,
            self.store,
            lambda participant_id: self.labels[participant_id],
            language=UILanguage.EN,
            moderation_allowed=lambda: True,
            participant_moderation=participant_moderation,
            id_factory=self.next_id,
        )
        message = view.snapshot()["chat"]["messages"][0]

        self.assertEqual("Historical contribution", message["body"])
        self.assertTrue(message["can_hide"])
        self.assertFalse(message["can_moderate_sender"])
        self.assertFalse(message["can_remove_sender"])

    def test_co_teacher_snapshot_hides_forbidden_teacher_target_actions(self) -> None:
        co_chat = FakeChat()
        co_media = ClassroomMediaController(
            local_participant_id="co-1",
            roster=self.roster,
            media=FakeMedia(),
        )
        co_controller = ClassroomCollaborationController(
            room_id="room-1",
            local_participant_id="co-1",
            roster=self.roster,
            chat=co_chat,
            files=FakeFiles(),
            store=self.store,
            file_store=self.file_store,
        )
        co_controller.receive_chat(
            ChatMessageMetadata(
                "teacher-message",
                "room-1",
                "teacher-1",
                0,
                "Teacher instruction",
                sent_at_unix_ms=1700000000000,
            )
        )
        view = ClassroomCollaborationWebView(
            co_controller,
            self.store,
            lambda participant_id: self.labels[participant_id],
            language=UILanguage.EN,
            moderation_allowed=lambda: True,
            participant_moderation=co_media,
            id_factory=self.next_id,
        )

        message = view.snapshot()["chat"]["messages"][0]
        self.assertTrue(message["can_hide"])
        self.assertFalse(message["can_moderate_sender"])
        self.assertFalse(message["can_remove_sender"])

    def test_mismatched_participant_moderation_identity_is_not_exposed_or_dispatched(self) -> None:
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
                "student-message-mismatched-media",
                "room-1",
                "student-2",
                0,
                "Keep media authority scoped",
                sent_at_unix_ms=1700000000000,
            )
        )
        wrong_media = FakeMedia()
        mismatched = ClassroomMediaController(
            local_participant_id="co-1",
            roster=self.roster,
            media=wrong_media,
        )
        view = ClassroomCollaborationWebView(
            teacher_controller,
            self.store,
            lambda participant_id: self.labels[participant_id],
            language=UILanguage.EN,
            moderation_allowed=lambda: True,
            participant_moderation=mismatched,
            id_factory=self.next_id,
        )

        message = view.snapshot()["chat"]["messages"][0]
        self.assertTrue(message["can_moderate_sender"])
        self.assertFalse(message["can_remove_sender"])
        rejected = view.dispatch(
            "collaboration.participant.block_sender",
            {"message_key": message["message_key"]},
        )
        self.assertEqual("error", rejected.kind)
        self.assertEqual([], wrong_media.moderation_calls)

    def test_non_moderator_snapshot_does_not_expose_message_action_key(self) -> None:
        view = self.webview()
        view.dispatch("collaboration.chat.send", {"body": "Local"})
        message = view.snapshot()["chat"]["messages"][0]
        self.assertFalse(message["can_hide"])
        self.assertFalse(message["can_moderate_sender"])
        self.assertFalse(message["can_remove_sender"])
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
        self.assertEqual("collaboration-file-choose", retried.payload["focus_target"])
        self.assertEqual(1, len(self.files.retry_calls))

        self.selected_file = self.root / "cancel.pgn"
        self.selected_file.write_text('[Event "Cancel"]\n\n1. d4 d5 *\n', encoding="utf-8")
        self.files.fail_upload = True
        failed_again = view.dispatch("collaboration.file.choose_upload", {})
        cancel_item = next(
            item
            for item in failed_again.payload["collaboration"]["files"]["items"]
            if item["can_cancel"]
        )
        cancelled = view.dispatch(
            "collaboration.file.cancel",
            {"file_key": cancel_item["file_key"]},
        )
        self.assertEqual("collaboration.file.cancelled", cancelled.kind)
        self.assertEqual("collaboration-file-choose", cancelled.payload["focus_target"])

    def test_remote_failed_file_never_exposes_cancel_action(self) -> None:
        self.store.register_attachment(
            AttachmentMetadata(
                "remote-file",
                "room-1",
                "student-2",
                0,
                "remote.pgn",
                "application/x-chess-pgn",
                1,
                "0" * 64,
                "rooms/room-1/remote-file",
                "failed",
                scan_state="pending",
            )
        )

        item = self.webview().snapshot()["files"]["items"][0]
        self.assertFalse(item["can_cancel"])
        self.assertFalse(item["can_retry"])
        self.assertFalse(item["can_save"])
        self.assertFalse(item["can_open"])
        self.assertNotIn("file_key", item)
        self.assertEqual([], self.files.cancel_calls)

    def test_blocked_failed_file_never_exposes_retry_action(self) -> None:
        self.selected_file = self.root / "blocked-retry.pgn"
        self.selected_file.write_text('[Event "Blocked"]\n\n1. e4 e5 *\n', encoding="utf-8")
        self.files.fail_upload = True
        view = self.webview()

        failed = view.dispatch("collaboration.file.choose_upload", {})
        item = failed.payload["collaboration"]["files"]["items"][0]
        attachment = self.store.room_attachments("room-1")[0]
        self.store.update_attachment_state(
            attachment.attachment_id,
            transfer_state="failed",
            scan_state="blocked",
        )

        blocked = view.snapshot()["files"]["items"][0]
        self.assertFalse(blocked["can_retry"])
        retried = view.dispatch(
            "collaboration.file.retry",
            {"file_key": item["file_key"]},
        )
        self.assertEqual("error", retried.kind)
        self.assertEqual([], self.files.retry_calls)

    def test_terminal_failed_results_never_announce_file_success(self) -> None:
        self.selected_file = self.root / "terminal-failure.pgn"
        self.selected_file.write_text(
            '[Event "Terminal failure"]\n\n1. e4 e5 *\n',
            encoding="utf-8",
        )
        view = self.webview()

        def failed_result(prepared):
            return replace(
                prepared.metadata,
                transfer_state="failed",
                scan_state="pending",
            )

        with mock.patch.object(self.files, "upload", side_effect=failed_result):
            uploaded = view.dispatch("collaboration.file.choose_upload", {})

        self.assertEqual("error", uploaded.kind)
        self.assertNotIn("announcement", uploaded.payload)
        failed_item = uploaded.payload["collaboration"]["files"]["items"][0]
        self.assertTrue(failed_item["can_retry"])
        self.assertEqual(1, len(view._prepared))

        with mock.patch.object(self.files, "retry", side_effect=failed_result):
            retried = view.dispatch(
                "collaboration.file.retry",
                {"file_key": failed_item["file_key"]},
            )

        self.assertEqual("error", retried.kind)
        self.assertNotIn("announcement", retried.payload)
        self.assertTrue(
            retried.payload["collaboration"]["files"]["items"][0]["can_retry"]
        )
        self.assertEqual(1, len(view._prepared))

    def test_blocked_retry_result_drops_local_source_path(self) -> None:
        self.selected_file = self.root / "blocked-after-retry.pgn"
        self.selected_file.write_text(
            '[Event "Blocked after retry"]\n\n1. e4 e5 *\n',
            encoding="utf-8",
        )
        self.files.fail_upload = True
        view = self.webview()
        failed = view.dispatch("collaboration.file.choose_upload", {})
        item = failed.payload["collaboration"]["files"]["items"][0]
        self.assertTrue(item["can_retry"])
        current = self.store.room_attachments("room-1")[0]

        with mock.patch.object(
            self.controller,
            "retry_file",
            return_value=replace(current, scan_state="blocked"),
        ):
            retried = view.dispatch(
                "collaboration.file.retry",
                {"file_key": item["file_key"]},
            )

        self.assertEqual("error", retried.kind)
        self.assertEqual({}, view._prepared)
        self.assertFalse(
            retried.payload["collaboration"]["files"]["items"][0]["can_retry"]
        )
        self.assertNotIn(str(self.selected_file), repr(retried.payload))

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

    def test_safe_snapshot_degrades_without_exposing_store_failure(self) -> None:
        view = self.webview()
        with mock.patch.object(
            self.store,
            "room_messages",
            side_effect=RuntimeError("C:/private/corrupt.sqlite3"),
        ):
            snapshot = view.safe_snapshot()
        self.assertFalse(snapshot["available"])
        self.assertEqual("Classroom collaboration is temporarily unavailable.", snapshot["status_message"])
        self.assertEqual((), snapshot["chat"]["messages"])
        self.assertNotIn("private", repr(snapshot))

    def test_dispatch_rejects_non_text_command_without_raising(self) -> None:
        view = self.webview()
        event = view.dispatch(7, {})
        self.assertEqual("error", event.kind)
        self.assertEqual("The action could not be completed.", event.payload["message"])

    def test_language_switch_changes_presentation_without_rebuilding_core(self) -> None:
        view = self.webview(language=UILanguage.EN)
        self.assertEqual("Chat", view.snapshot()["chat"]["heading"])
        self.assertEqual("Message time", view.snapshot()["chat"]["timestamp_label"])
        view.set_language(UILanguage.UA)
        self.assertEqual("Чат", view.snapshot()["chat"]["heading"])
        self.assertEqual("Час повідомлення", view.snapshot()["chat"]["timestamp_label"])


if __name__ == "__main__":
    unittest.main()
