from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.classroom_collaboration import (
    ClassroomCollaborationController,
    FileTransferProgress,
)
from acs.classroom_collaboration_storage import (
    AttachmentMetadata,
    AttachmentStateUpdate,
    ChatMessageMetadata,
    ClassroomCollaborationSQLiteStore,
)
from acs.classroom_collaboration_webview import ClassroomCollaborationWebView
from acs.classroom_domain import MAX_WIRE_INTEGER
from acs.classroom_realtime_media import ClassroomMediaController, ClassroomRole
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

    def webview(
        self,
        *,
        language: UILanguage = UILanguage.EN,
        chat_retention: str = "session",
        file_retention: str = "session",
        file_progress_event_sink=None,
    ) -> ClassroomCollaborationWebView:
        return ClassroomCollaborationWebView(
            self.controller,
            self.store,
            lambda participant_id: self.labels[participant_id],
            language=language,
            file_picker=lambda: self.selected_file,
            file_saver=lambda token, name: self.save_calls.append((token, name)),
            file_opener=lambda token, name: self.open_calls.append((token, name)),
            file_progress_event_sink=file_progress_event_sink,
            chat_retention=chat_retention,
            file_retention=file_retention,
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

    def test_browser_chat_body_is_bounded_before_identity_or_pending_state(self) -> None:
        view = self.webview()

        for body in ("", "   ", "bad\x00body", "x" * 4001, "bad" + chr(0xD800)):
            with self.subTest(body=repr(body[:20])):
                event = view.dispatch(
                    "collaboration.chat.send",
                    {"body": body},
                )
                self.assertEqual("error", event.kind)
                self.assertEqual({}, view._pending_chat)
                self.assertEqual({}, self.ids)
                self.assertEqual((), self.store.room_messages("room-1"))

    def test_failed_chat_send_reuses_host_identity_for_same_draft(self) -> None:
        view = self.webview()
        calls: list[tuple[str, str]] = []

        def flaky_send_chat(*, message_id: str, body: str, retention: str = "session"):
            calls.append((message_id, body))
            if len(calls) == 1:
                raise RuntimeError("ambiguous chat transport")
            return None

        with mock.patch.object(
            self.controller,
            "send_chat",
            side_effect=flaky_send_chat,
        ):
            failed = view.dispatch(
                "collaboration.chat.send",
                {"body": "Retry exactly once"},
            )
            retried = view.dispatch(
                "collaboration.chat.send",
                {"body": "Retry exactly once"},
            )

        self.assertEqual("error", failed.kind)
        self.assertEqual(
            "Message send was not confirmed. Retry or refresh chat.",
            failed.payload["message"],
        )
        self.assertEqual("collaboration-chat-input", failed.payload["focus_target"])
        self.assertEqual("collaboration.chat.sent", retried.kind)
        self.assertEqual(
            calls,
            [
                ("message-ui-1", "Retry exactly once"),
                ("message-ui-1", "Retry exactly once"),
            ],
        )
        self.assertEqual(1, self.ids["message"])
        self.assertEqual({}, view._pending_chat)
        self.assertNotIn("message-ui-1", repr(failed.payload))
        self.assertNotIn("message-ui-1", repr(retried.payload))

    def test_changed_chat_draft_mints_new_identity_after_failure(self) -> None:
        view = self.webview()
        calls: list[tuple[str, str]] = []

        def flaky_send(*, message_id: str, body: str, retention: str = "session"):
            calls.append((message_id, body))
            if len(calls) == 1:
                raise RuntimeError("ambiguous chat transport")
            return None

        with mock.patch.object(
            self.controller,
            "send_chat",
            side_effect=flaky_send,
        ):
            failed = view.dispatch(
                "collaboration.chat.send",
                {"body": "Original draft"},
            )
            changed = view.dispatch(
                "collaboration.chat.send",
                {"body": "Edited draft"},
            )

        self.assertEqual("error", failed.kind)
        self.assertEqual(
            "Message send was not confirmed. Retry or refresh chat.",
            failed.payload["message"],
        )
        self.assertEqual("collaboration.chat.sent", changed.kind)
        self.assertEqual(
            calls,
            [
                ("message-ui-1", "Original draft"),
                ("message-ui-2", "Edited draft"),
            ],
        )
        self.assertEqual({"message-ui-1"}, set(view._pending_chat.values()))
        self.assertNotIn("Original draft", repr(view._pending_chat))
        self.assertNotIn("Edited draft", repr(view._pending_chat))

    def test_multiple_ambiguous_chat_drafts_keep_independent_retry_identities(self) -> None:
        view = self.webview()
        calls: list[tuple[str, str]] = []

        def ambiguous_send(*, message_id: str, body: str, retention: str = "session"):
            calls.append((message_id, body))
            raise RuntimeError("ambiguous chat transport")

        with mock.patch.object(
            self.controller,
            "send_chat",
            side_effect=ambiguous_send,
        ):
            first = view.dispatch(
                "collaboration.chat.send",
                {"body": "First ambiguous"},
            )
            second = view.dispatch(
                "collaboration.chat.send",
                {"body": "Second ambiguous"},
            )
            first_retry = view.dispatch(
                "collaboration.chat.send",
                {"body": "First ambiguous"},
            )

        self.assertEqual("error", first.kind)
        self.assertEqual("error", second.kind)
        self.assertEqual("error", first_retry.kind)
        self.assertEqual(
            calls,
            [
                ("message-ui-1", "First ambiguous"),
                ("message-ui-2", "Second ambiguous"),
                ("message-ui-1", "First ambiguous"),
            ],
        )
        self.assertEqual(
            {"message-ui-1", "message-ui-2"},
            set(view._pending_chat.values()),
        )
        self.assertNotIn("First ambiguous", repr(view._pending_chat))
        self.assertNotIn("Second ambiguous", repr(view._pending_chat))

    def test_ambiguous_chat_recovery_state_is_bounded_before_minting_more_ids(self) -> None:
        view = self.webview()
        calls: list[str] = []

        def ambiguous_send(*, message_id: str, body: str, retention: str = "session"):
            calls.append(message_id)
            raise RuntimeError("ambiguous chat transport")

        with mock.patch.object(
            self.controller,
            "send_chat",
            side_effect=ambiguous_send,
        ):
            events = tuple(
                view.dispatch(
                    "collaboration.chat.send",
                    {"body": f"Ambiguous draft {index}"},
                )
                for index in range(33)
            )

        self.assertTrue(all(event.kind == "error" for event in events))
        self.assertEqual(32, len(calls))
        self.assertEqual(32, self.ids["message"])
        self.assertEqual(32, len(view._pending_chat))
        self.assertNotIn("Ambiguous draft", repr(view._pending_chat))

    def test_chat_sync_clears_recovered_pending_identity(self) -> None:
        view = self.webview()
        calls: list[str] = []

        def failed_send(*, message_id: str, body: str, retention: str = "session"):
            calls.append(message_id)
            raise RuntimeError("ambiguous chat transport")

        with mock.patch.object(
            self.controller,
            "send_chat",
            side_effect=failed_send,
        ):
            failed = view.dispatch(
                "collaboration.chat.send",
                {"body": "Recovered later"},
            )
        self.assertEqual("error", failed.kind)
        pending_id = calls[0]

        accepted = ChatMessageMetadata(
            pending_id,
            "room-1",
            "student-1",
            0,
            "Recovered later",
            sent_at_unix_ms=1700000000000,
        )
        self.chat.messages[pending_id] = accepted
        self.chat.ordered = [accepted]

        synced = view.dispatch("collaboration.chat.sync", {})
        self.assertEqual("collaboration.chat.synced", synced.kind)
        self.assertEqual("Message sent.", synced.payload["announcement"])
        self.assertEqual({}, view._pending_chat)
        self.assertNotIn(pending_id, repr(synced.payload))

        next_calls: list[str] = []

        def next_send(*, message_id: str, body: str, retention: str = "session"):
            next_calls.append(message_id)
            return None

        with mock.patch.object(
            self.controller,
            "send_chat",
            side_effect=next_send,
        ):
            sent_again = view.dispatch(
                "collaboration.chat.send",
                {"body": "Recovered later"},
            )
        self.assertEqual("collaboration.chat.sent", sent_again.kind)
        self.assertEqual(next_calls, ["message-ui-2"])

    def test_chat_sync_does_not_confirm_mutated_pending_identity(self) -> None:
        view = self.webview()
        calls: list[str] = []

        def failed_send(*, message_id: str, body: str, retention: str = "session"):
            calls.append(message_id)
            raise RuntimeError("ambiguous chat transport")

        with mock.patch.object(
            self.controller,
            "send_chat",
            side_effect=failed_send,
        ):
            failed = view.dispatch(
                "collaboration.chat.send",
                {"body": "Expected pending body"},
            )
        self.assertEqual("error", failed.kind)
        pending_id = calls[0]

        accepted_with_wrong_body = ChatMessageMetadata(
            pending_id,
            "room-1",
            "student-1",
            0,
            "Unexpected body",
            retention="session",
            sent_at_unix_ms=1700000000000,
        )
        self.chat.messages[pending_id] = accepted_with_wrong_body
        self.chat.ordered = [accepted_with_wrong_body]

        synced = view.dispatch("collaboration.chat.sync", {})
        self.assertEqual("error", synced.kind)
        self.assertEqual(
            "Message send was not confirmed. Retry or refresh chat.",
            synced.payload["message"],
        )
        self.assertEqual(1, len(view._pending_chat))
        self.assertEqual(
            (accepted_with_wrong_body,),
            self.store.room_messages("room-1", include_hidden=True),
        )

    def test_chat_history_is_bounded_pageable_and_keeps_semantic_order(self) -> None:
        for sequence in range(105):
            self.store.append_message(
                ChatMessageMetadata(
                    f"history-{sequence}",
                    "room-1",
                    "student-2",
                    sequence,
                    f"Message {sequence}",
                    sent_at_unix_ms=1700000000000 + sequence,
                )
            )
        view = self.webview()

        latest = view.snapshot()["chat"]
        self.assertEqual(5, len(latest["messages"]))
        self.assertEqual("Message 100", latest["messages"][0]["body"])
        self.assertEqual("Message 104", latest["messages"][-1]["body"])
        self.assertEqual("Message history page 3 of 3", latest["page_label"])
        self.assertTrue(latest["can_older"])
        self.assertFalse(latest["can_newer"])

        beyond_latest = view.dispatch("collaboration.chat.newer", {})
        self.assertEqual("error", beyond_latest.kind)

        middle_event = view.dispatch("collaboration.chat.older", {})
        middle = middle_event.payload["collaboration"]["chat"]
        self.assertEqual("collaboration.chat.page", middle_event.kind)
        self.assertEqual("collaboration-chat-older", middle_event.payload["focus_target"])
        self.assertEqual("Message history page 2 of 3", middle_event.payload["announcement"])
        self.assertEqual(50, len(middle["messages"]))
        self.assertEqual("Message 50", middle["messages"][0]["body"])
        self.assertEqual("Message 99", middle["messages"][-1]["body"])
        self.assertTrue(middle["can_older"])
        self.assertTrue(middle["can_newer"])

        self.store.append_message(
            ChatMessageMetadata(
                "history-105",
                "room-1",
                "student-2",
                105,
                "Message 105",
                sent_at_unix_ms=1700000000105,
            )
        )
        stable_middle = view.snapshot()["chat"]
        self.assertEqual("Message 50", stable_middle["messages"][0]["body"])
        self.assertEqual("Message 99", stable_middle["messages"][-1]["body"])

        oldest_event = view.dispatch("collaboration.chat.older", {})
        oldest = oldest_event.payload["collaboration"]["chat"]
        self.assertEqual("collaboration-chat-newer", oldest_event.payload["focus_target"])
        self.assertEqual(50, len(oldest["messages"]))
        self.assertEqual("Message 0", oldest["messages"][0]["body"])
        self.assertEqual("Message 49", oldest["messages"][-1]["body"])
        self.assertFalse(oldest["can_older"])
        self.assertTrue(oldest["can_newer"])

        middle_again = view.dispatch("collaboration.chat.newer", {})
        self.assertEqual(
            "Message 50",
            middle_again.payload["collaboration"]["chat"]["messages"][0]["body"],
        )

    def test_trusted_live_chat_push_is_unread_and_duplicate_is_not_reannounced(self) -> None:
        view = self.webview()
        message = ChatMessageMetadata(
            "live-remote-message",
            "room-1",
            "student-2",
            0,
            "Live answer",
            sent_at_unix_ms=1700000000000,
        )

        received = view.receive_chat(message)
        self.assertEqual("collaboration.chat.received", received.kind)
        self.assertEqual(
            "Student two: Live answer",
            received.payload["announcement"],
        )
        self.assertEqual(
            1,
            received.payload["collaboration"]["chat"]["unread_count"],
        )

        duplicate = view.receive_chat(message)
        self.assertEqual("collaboration.chat.received", duplicate.kind)
        self.assertNotIn("announcement", duplicate.payload)
        self.assertEqual(
            1,
            duplicate.payload["collaboration"]["chat"]["unread_count"],
        )
        self.assertEqual(1, len(self.store.room_messages("room-1")))

    def test_hidden_live_redelivery_clears_existing_unread_state(self) -> None:
        view = self.webview()
        message = ChatMessageMetadata(
            "remote-live-hidden",
            "room-1",
            "student-2",
            0,
            "Visible before moderation",
            sent_at_unix_ms=1700000000000,
        )
        first = view.receive_chat(message)
        self.assertEqual(
            1,
            first.payload["collaboration"]["chat"]["unread_count"],
        )

        hidden = view.receive_chat(replace(message, hidden=True))

        self.assertEqual("collaboration.chat.received", hidden.kind)
        self.assertNotIn("announcement", hidden.payload)
        self.assertEqual(
            0,
            hidden.payload["collaboration"]["chat"]["unread_count"],
        )
        self.assertEqual((), hidden.payload["collaboration"]["chat"]["messages"])
        self.assertEqual(set(), view._unread_message_ids)

    def test_sync_removes_hidden_message_from_unread_count(self) -> None:
        view = self.webview()
        message = ChatMessageMetadata(
            "remote-unread-hidden",
            "room-1",
            "student-2",
            0,
            "Moderated after delivery",
            sent_at_unix_ms=1700000000000,
        )
        received = view.receive_chat(message)
        self.assertEqual(
            1,
            received.payload["collaboration"]["chat"]["unread_count"],
        )

        def hide_during_sync():
            self.store.set_message_hidden(message.message_id, True)
            return ()

        with mock.patch.object(
            self.controller,
            "sync_chat",
            side_effect=hide_during_sync,
        ):
            synced = view.dispatch("collaboration.chat.sync", {})

        self.assertEqual("collaboration.chat.synced", synced.kind)
        self.assertEqual(0, synced.payload["collaboration"]["chat"]["unread_count"])
        self.assertEqual((), synced.payload["collaboration"]["chat"]["messages"])
        self.assertEqual(set(), view._unread_message_ids)

    def test_trusted_live_chat_echo_recovers_pending_send_without_unread(self) -> None:
        view = self.webview()
        with mock.patch.object(
            self.controller,
            "send_chat",
            side_effect=RuntimeError("ambiguous provider send"),
        ):
            failed = view.dispatch(
                "collaboration.chat.send",
                {"body": "Pending live echo"},
            )
        self.assertEqual("error", failed.kind)
        self.assertEqual(1, len(view._pending_chat))
        pending_id = next(iter(view._pending_chat.values()))
        self.assertNotIn("Pending live echo", repr(view._pending_chat))

        recovered = view.receive_chat(
            ChatMessageMetadata(
                pending_id,
                "room-1",
                "student-1",
                0,
                "Pending live echo",
                retention="session",
                sent_at_unix_ms=1700000000000,
            )
        )
        self.assertEqual("collaboration.chat.received", recovered.kind)
        self.assertEqual("Message sent.", recovered.payload["announcement"])
        self.assertEqual({}, view._pending_chat)
        self.assertEqual(
            0,
            recovered.payload["collaboration"]["chat"]["unread_count"],
        )
        self.assertEqual(1, len(self.store.room_messages("room-1")))

    def test_trusted_live_chat_echo_rejects_pending_identity_with_changed_body(self) -> None:
        view = self.webview()
        with mock.patch.object(
            self.controller,
            "send_chat",
            side_effect=RuntimeError("ambiguous provider send"),
        ):
            failed = view.dispatch(
                "collaboration.chat.send",
                {"body": "Original pending body"},
            )
        self.assertEqual("error", failed.kind)
        pending_id = next(iter(view._pending_chat.values()))

        with self.assertRaisesRegex(
            ValueError,
            "live chat conflicts with pending send identity",
        ):
            view.receive_chat(
                ChatMessageMetadata(
                    pending_id,
                    "room-1",
                    "student-1",
                    0,
                    "Mutated pending body",
                    retention="session",
                    sent_at_unix_ms=1700000000000,
                )
            )

        self.assertEqual(1, len(view._pending_chat))
        self.assertEqual((), self.store.room_messages("room-1"))

    def test_trusted_live_file_push_is_visible_without_manual_refresh(self) -> None:
        view = self.webview()
        attachment = AttachmentMetadata(
            "live-remote-file",
            "room-1",
            "student-2",
            0,
            "live.pgn",
            "application/x-chess-pgn",
            4,
            "0" * 64,
            "rooms/room-1/live-remote-file",
            "stored",
            retention="session",
            scan_state="clean",
        )

        received = view.receive_file(attachment)
        self.assertEqual("collaboration.file.received", received.kind)
        self.assertEqual(
            "New file: live.pgn.",
            received.payload["announcement"],
        )
        items = received.payload["collaboration"]["files"]["items"]
        self.assertEqual(["live.pgn"], [item["name"] for item in items])

        duplicate = view.receive_file(attachment)
        self.assertEqual("collaboration.file.received", duplicate.kind)
        self.assertNotIn("announcement", duplicate.payload)
        self.assertEqual(
            1,
            len(self.store.room_attachments("room-1")),
        )

    def test_chat_sync_failure_is_contextual_without_exposing_transport_details(self) -> None:
        view = self.webview()
        with mock.patch.object(
            self.controller,
            "sync_chat",
            side_effect=RuntimeError("wss://secret.example/room-1"),
        ):
            event = view.dispatch("collaboration.chat.sync", {})

        self.assertEqual("error", event.kind)
        self.assertEqual("Chat refresh failed.", event.payload["message"])
        self.assertEqual("collaboration-chat-sync", event.payload["focus_target"])
        self.assertNotIn("secret.example", repr(event.payload))

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
        self.assertEqual(
            "Student two: Visiblegnp next",
            messages[-1]["action_message"],
        )
        self.assertEqual("Student two", messages[-1]["action_sender"])
        self.assertNotIn("\u202E", event.payload["announcement"])
        self.assertNotIn("\u200b", event.payload["announcement"])
        self.assertNotIn("\u202E", messages[-1]["action_message"])
        self.assertNotIn("\u200b", messages[-1]["action_message"])

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

    def test_file_history_is_bounded_pageable_and_keeps_semantic_order(self) -> None:
        for sequence in range(105):
            self.store.register_attachment(
                AttachmentMetadata(
                    f"history-file-{sequence}",
                    "room-1",
                    "student-2",
                    sequence,
                    f"file-{sequence}.pgn",
                    "application/x-chess-pgn",
                    1,
                    "0" * 64,
                    f"rooms/room-1/history-file-{sequence}",
                    "stored",
                    scan_state="clean",
                )
            )
        view = self.webview()

        latest = view.snapshot()["files"]
        self.assertEqual(5, len(latest["items"]))
        self.assertEqual("file-100.pgn", latest["items"][0]["name"])
        self.assertEqual("file-104.pgn", latest["items"][-1]["name"])
        self.assertEqual("File history page 3 of 3", latest["page_label"])
        self.assertTrue(latest["can_older"])
        self.assertFalse(latest["can_newer"])

        beyond_latest = view.dispatch("collaboration.file.newer", {})
        self.assertEqual("error", beyond_latest.kind)

        middle_event = view.dispatch("collaboration.file.older", {})
        middle = middle_event.payload["collaboration"]["files"]
        self.assertEqual("collaboration.file.page", middle_event.kind)
        self.assertEqual("collaboration-file-older", middle_event.payload["focus_target"])
        self.assertEqual("File history page 2 of 3", middle_event.payload["announcement"])
        self.assertEqual(50, len(middle["items"]))
        self.assertEqual("file-50.pgn", middle["items"][0]["name"])
        self.assertEqual("file-99.pgn", middle["items"][-1]["name"])

        self.store.register_attachment(
            AttachmentMetadata(
                "history-file-105",
                "room-1",
                "student-2",
                105,
                "file-105.pgn",
                "application/x-chess-pgn",
                1,
                "0" * 64,
                "rooms/room-1/history-file-105",
                "stored",
                scan_state="clean",
            )
        )
        stable_middle = view.snapshot()["files"]
        self.assertEqual("file-50.pgn", stable_middle["items"][0]["name"])
        self.assertEqual("file-99.pgn", stable_middle["items"][-1]["name"])

        oldest_event = view.dispatch("collaboration.file.older", {})
        oldest = oldest_event.payload["collaboration"]["files"]
        self.assertEqual("collaboration-file-newer", oldest_event.payload["focus_target"])
        self.assertEqual("file-0.pgn", oldest["items"][0]["name"])
        self.assertEqual("file-49.pgn", oldest["items"][-1]["name"])
        self.assertFalse(oldest["can_older"])
        self.assertTrue(oldest["can_newer"])

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
                transfer_state="stored",
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

    def test_file_sync_clears_terminal_progress_after_authoritative_tombstone(self) -> None:
        self.selected_file = self.root / "deleted-after-upload.pgn"
        self.selected_file.write_bytes(b"1234")
        self.files.scan_state = "clean"
        view = self.webview(file_progress_event_sink=lambda _event: None)

        uploaded = view.dispatch("collaboration.file.choose_upload", {})
        self.assertEqual("collaboration.file.sent", uploaded.kind)
        self.assertIsNotNone(
            uploaded.payload["collaboration"]["files"]["transfer_progress"]
        )
        uploaded_revision = uploaded.payload["collaboration"]["files"]["progress_revision"]
        attachment = self.store.room_attachments("room-1")[0]

        def delete_authoritatively():
            self.store.update_attachment_state(
                attachment.attachment_id,
                transfer_state="deleted",
                scan_state=attachment.scan_state,
            )
            return ()

        with mock.patch.object(
            self.controller,
            "sync_files",
            side_effect=delete_authoritatively,
        ):
            synced = view.dispatch("collaboration.file.sync", {})

        self.assertEqual("collaboration.files.synced", synced.kind)
        self.assertEqual((), synced.payload["collaboration"]["files"]["items"])
        self.assertIsNone(
            synced.payload["collaboration"]["files"]["transfer_progress"]
        )
        self.assertGreater(
            synced.payload["collaboration"]["files"]["progress_revision"],
            uploaded_revision,
        )
        self.assertIsNone(view._file_progress)
        self.assertIsNone(view._file_progress_attempt_token)

    def test_file_sync_bad_state_revision_fails_closed_without_partial_projection(self) -> None:
        self.store.register_attachment(
            AttachmentMetadata(
                "remote-state-gap",
                "room-1",
                "student-2",
                0,
                "gap.pgn",
                "application/x-chess-pgn",
                4,
                "0" * 64,
                "rooms/room-1/remote-state-gap",
                "stored",
                scan_state="pending",
            )
        )
        self.files.state_override = (
            AttachmentStateUpdate(
                "room-1",
                "remote-state-gap",
                1,
                "stored",
                "clean",
            ),
        )
        event = self.webview().dispatch("collaboration.file.sync", {})

        self.assertEqual("error", event.kind)
        self.assertNotIn("announcement", event.payload)
        item = event.payload["collaboration"]["files"]["items"][0]
        self.assertEqual("Scan: pending", item["scan_label"])
        self.assertFalse(item["can_save"])
        self.assertFalse(item["can_open"])
        self.assertNotIn("file_key", item)

    def test_file_sync_rejects_browser_fields_without_transport_call(self) -> None:
        view = self.webview()
        event = view.dispatch("collaboration.file.sync", {"after": 0})
        self.assertEqual("error", event.kind)
        self.assertEqual([], self.files.ordered)

    def test_file_picker_cancel_and_failure_are_contextual_without_path_leak(self) -> None:
        view = self.webview()

        cancelled = view.dispatch("collaboration.file.choose_upload", {})
        self.assertEqual("collaboration.file.selection_cancelled", cancelled.kind)
        self.assertEqual(
            "File selection cancelled.",
            cancelled.payload["announcement"],
        )
        self.assertEqual(
            "collaboration-file-choose",
            cancelled.payload["focus_target"],
        )
        self.assertEqual((), self.store.room_attachments("room-1"))

        def failing_picker() -> Path | None:
            raise RuntimeError("C:/private/student/secret-choice.pgn")

        failing_view = ClassroomCollaborationWebView(
            self.controller,
            self.store,
            lambda participant_id: self.labels[participant_id],
            language=UILanguage.EN,
            file_picker=failing_picker,
            id_factory=self.next_id,
        )
        failed = failing_view.dispatch("collaboration.file.choose_upload", {})
        self.assertEqual("error", failed.kind)
        self.assertEqual("Could not choose file.", failed.payload["message"])
        self.assertEqual(
            "collaboration-file-choose",
            failed.payload["focus_target"],
        )
        self.assertNotIn("C:/private", repr(failed.payload))
        self.assertNotIn("secret-choice", repr(failed.payload))
        self.assertEqual((), self.store.room_attachments("room-1"))

    def test_file_sync_failure_is_contextual_without_provider_detail(self) -> None:
        view = self.webview()
        with mock.patch.object(
            self.controller,
            "sync_files",
            side_effect=RuntimeError("https://provider.example/secret-room"),
        ):
            event = view.dispatch("collaboration.file.sync", {})

        self.assertEqual("error", event.kind)
        self.assertEqual("File refresh failed.", event.payload["message"])
        self.assertEqual("collaboration-file-sync", event.payload["focus_target"])
        self.assertNotIn("provider.example", repr(event.payload))

    def test_file_save_open_and_cancel_failures_keep_sensitive_details_out_of_browser(self) -> None:
        self.selected_file = self.root / "safe-actions.pgn"
        self.selected_file.write_text(
            '[Event "Safe actions"]\n\n1. e4 e5 *\n',
            encoding="utf-8",
        )
        self.files.scan_state = "clean"

        def fail_save(token: str, name: str) -> None:
            raise RuntimeError(f"C:/private/save/{token}/{name}")

        def fail_open(token: str, name: str) -> None:
            raise RuntimeError(f"shell://private/{token}/{name}")

        view = ClassroomCollaborationWebView(
            self.controller,
            self.store,
            lambda participant_id: self.labels[participant_id],
            language=UILanguage.EN,
            file_picker=lambda: self.selected_file,
            file_saver=fail_save,
            file_opener=fail_open,
            id_factory=self.next_id,
        )
        uploaded = view.dispatch("collaboration.file.choose_upload", {})
        item = uploaded.payload["collaboration"]["files"]["items"][0]

        saved = view.dispatch(
            "collaboration.file.save",
            {"file_key": item["file_key"]},
        )
        self.assertEqual("error", saved.kind)
        self.assertEqual(
            "Could not prepare safe file save: safe-actions.pgn.",
            saved.payload["message"],
        )
        self.assertNotIn("short-lived-read-token", repr(saved.payload))
        self.assertNotIn("C:/private", repr(saved.payload))

        opened = view.dispatch(
            "collaboration.file.open",
            {"file_key": item["file_key"]},
        )
        self.assertEqual("error", opened.kind)
        self.assertEqual(
            "Could not prepare file open: safe-actions.pgn.",
            opened.payload["message"],
        )
        self.assertNotIn("short-lived-read-token", repr(opened.payload))
        self.assertNotIn("shell://private", repr(opened.payload))

        self.selected_file = self.root / "cancel-fail.pgn"
        self.selected_file.write_text(
            '[Event "Cancel failure"]\n\n1. d4 d5 *\n',
            encoding="utf-8",
        )
        self.files.fail_upload = True
        failed = view.dispatch("collaboration.file.choose_upload", {})
        cancel_item = next(
            file_item
            for file_item in failed.payload["collaboration"]["files"]["items"]
            if file_item["name"] == "cancel-fail.pgn"
        )
        with mock.patch.object(
            self.controller,
            "cancel_file",
            side_effect=RuntimeError("provider cancellation secret"),
        ):
            cancelled = view.dispatch(
                "collaboration.file.cancel",
                {"file_key": cancel_item["file_key"]},
            )
        self.assertEqual("error", cancelled.kind)
        self.assertEqual(
            "Could not cancel file transfer: cancel-fail.pgn.",
            cancelled.payload["message"],
        )
        self.assertNotIn("provider cancellation secret", repr(cancelled.payload))
        self.assertTrue(
            next(
                file_item
                for file_item in cancelled.payload["collaboration"]["files"]["items"]
                if file_item["name"] == "cancel-fail.pgn"
            )["can_cancel"]
        )

    def test_file_upload_and_save_keep_local_path_object_key_hash_and_token_out_of_browser(self) -> None:
        self.selected_file = self.root / "lesson notes.txt"
        self.selected_file.write_text("accessible classroom file", encoding="utf-8")
        self.files.scan_state = "clean"
        view = self.webview()

        uploaded = view.dispatch("collaboration.file.choose_upload", {})
        self.assertEqual("collaboration.file.sent", uploaded.kind)
        self.assertEqual(
            "File sent: lesson notes.txt.",
            uploaded.payload["announcement"],
        )
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
            "File passed to safe save: lesson notes.txt.",
            saved.payload["announcement"],
        )
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
            "File passed to explicit open: lesson notes.txt.",
            opened.payload["announcement"],
        )
        self.assertEqual(
            [("short-lived-read-token", "lesson notes.txt")],
            self.open_calls,
        )
        self.assertNotIn("short-lived-read-token", repr(opened.payload))

    def test_file_upload_progress_is_incremental_session_bound_and_secret_safe(self) -> None:
        self.selected_file = self.root / "progress.pgn"
        self.selected_file.write_bytes(b"0123456789")
        self.files.scan_state = "clean"
        self.files.progress_samples = (
            FileTransferProgress("attachment-ui-1", 4, 10),
        )
        progress_events = []
        view = self.webview(file_progress_event_sink=progress_events.append)

        uploaded = view.dispatch("collaboration.file.choose_upload", {})

        self.assertEqual("collaboration.file.sent", uploaded.kind)
        self.assertEqual(
            [0, 4, 10],
            [
                event.payload["file_progress"]["transferred_bytes"]
                for event in progress_events
            ],
        )
        self.assertEqual(
            [False, False, True],
            [event.payload["file_progress"]["complete"] for event in progress_events],
        )
        first_progress_revisions = [
            event.payload["file_progress"]["progress_revision"]
            for event in progress_events
        ]
        self.assertEqual([1, 2, 3], first_progress_revisions)
        self.assertEqual(
            first_progress_revisions[-1],
            uploaded.payload["collaboration"]["files"]["progress_revision"],
        )
        self.assertEqual(
            first_progress_revisions[-1],
            uploaded.payload["collaboration"]["files"]["transfer_progress"][
                "progress_revision"
            ],
        )
        session_key = uploaded.payload["collaboration"]["session_key"]
        transfer_keys = {
            event.payload["file_progress"]["transfer_key"]
            for event in progress_events
        }
        self.assertEqual(1, len(transfer_keys))
        first_transfer_key = next(iter(transfer_keys))
        self.assertEqual(64, len(first_transfer_key))
        self.assertNotEqual(
            uploaded.payload["collaboration"]["files"]["items"][0]["file_key"],
            first_transfer_key,
        )
        self.assertEqual(
            first_transfer_key,
            uploaded.payload["collaboration"]["files"]["transfer_progress"]["transfer_key"],
        )
        for command in ("collaboration.file.save", "collaboration.file.open"):
            rejected = view.dispatch(command, {"file_key": first_transfer_key})
            self.assertEqual("error", rejected.kind)
        self.assertEqual([], self.save_calls)
        self.assertEqual([], self.open_calls)
        for event in progress_events:
            self.assertEqual("collaboration.file.progress", event.kind)
            progress = event.payload["file_progress"]
            self.assertEqual(session_key, progress["session_key"])
            self.assertEqual("progress.pgn", progress["name"])
            self.assertEqual(10, progress["total_bytes"])
            self.assertEqual("File transfer progress", progress["label"])
            self.assertIn("progress.pgn", progress["text"])
            exposed = repr(event.payload)
            self.assertNotIn(str(self.root), exposed)
            self.assertNotIn("rooms/room-1", exposed)
            self.assertNotIn("sha256", exposed.lower())
            self.assertNotIn("attachment-ui-1", exposed)

        self.selected_file = self.root / "progress-two.pgn"
        self.selected_file.write_bytes(b"abcdefghijkl")
        self.files.progress_samples = (
            FileTransferProgress("attachment-ui-2", 6, 12),
        )
        progress_events.clear()
        second = view.dispatch("collaboration.file.choose_upload", {})
        self.assertEqual("collaboration.file.sent", second.kind)
        second_transfer_keys = {
            event.payload["file_progress"]["transfer_key"]
            for event in progress_events
        }
        self.assertEqual(1, len(second_transfer_keys))
        second_transfer_key = next(iter(second_transfer_keys))
        self.assertNotEqual(first_transfer_key, second_transfer_key)
        second_progress_revisions = [
            event.payload["file_progress"]["progress_revision"]
            for event in progress_events
        ]
        self.assertEqual(sorted(second_progress_revisions), second_progress_revisions)
        self.assertEqual(len(set(second_progress_revisions)), len(second_progress_revisions))
        self.assertGreater(second_progress_revisions[0], first_progress_revisions[-1])
        self.assertEqual(
            second_progress_revisions[-1],
            second.payload["collaboration"]["files"]["progress_revision"],
        )
        self.assertEqual(
            second_transfer_key,
            second.payload["collaboration"]["files"]["transfer_progress"]["transfer_key"],
        )
        self.assertEqual(
            12,
            second.payload["collaboration"]["files"]["transfer_progress"]["total_bytes"],
        )

    def test_all_bytes_sent_remains_finalizing_until_authoritative_completion(self) -> None:
        self.selected_file = self.root / "finalizing.pgn"
        self.selected_file.write_bytes(b"0123456789")
        self.files.scan_state = "clean"
        self.files.progress_samples = (
            FileTransferProgress("attachment-ui-1", 10, 10),
        )
        progress_events = []
        view = self.webview(file_progress_event_sink=progress_events.append)

        uploaded = view.dispatch("collaboration.file.choose_upload", {})

        self.assertEqual("collaboration.file.sent", uploaded.kind)
        self.assertEqual(
            [(0, False), (10, False), (10, True)],
            [
                (
                    event.payload["file_progress"]["transferred_bytes"],
                    event.payload["file_progress"]["complete"],
                )
                for event in progress_events
            ],
        )
        provider_all_bytes = progress_events[-2].payload["file_progress"]
        terminal = progress_events[-1].payload["file_progress"]
        self.assertEqual(
            "All bytes transferred; finalizing transfer: finalizing.pgn.",
            provider_all_bytes["text"],
        )
        self.assertEqual(
            "Transferred 10 B of 10 B: finalizing.pgn.",
            terminal["text"],
        )
        self.assertFalse(provider_all_bytes["complete"])
        self.assertTrue(terminal["complete"])
        self.assertLess(
            provider_all_bytes["progress_revision"],
            terminal["progress_revision"],
        )

    def test_partial_upload_failure_clears_progress_before_retry(self) -> None:
        self.selected_file = self.root / "partial-retry.pgn"
        self.selected_file.write_bytes(b"0123456789")
        progress_events = []
        view = self.webview(file_progress_event_sink=progress_events.append)

        def fail_after_partial(prepared, *, on_progress):
            on_progress(
                FileTransferProgress(
                    prepared.metadata.attachment_id,
                    4,
                    prepared.metadata.size_bytes,
                )
            )
            raise RuntimeError("provider failed after partial transfer")

        with mock.patch.object(self.files, "upload", side_effect=fail_after_partial):
            failed = view.dispatch("collaboration.file.choose_upload", {})

        self.assertEqual("error", failed.kind)
        self.assertEqual([0, 4], [
            event.payload["file_progress"]["transferred_bytes"]
            for event in progress_events
        ])
        failed_transfer_keys = {
            event.payload["file_progress"]["transfer_key"]
            for event in progress_events
        }
        self.assertEqual(1, len(failed_transfer_keys))
        failed_transfer_key = next(iter(failed_transfer_keys))
        self.assertIsNone(
            failed.payload["collaboration"]["files"]["transfer_progress"]
        )
        failed_revision = failed.payload["collaboration"]["files"]["progress_revision"]
        self.assertGreater(
            failed_revision,
            progress_events[-1].payload["file_progress"]["progress_revision"],
        )
        self.assertIsNone(view._file_progress)
        failed_item = failed.payload["collaboration"]["files"]["items"][0]
        self.assertTrue(failed_item["can_retry"])

        progress_events.clear()
        retried = view.dispatch(
            "collaboration.file.retry",
            {"file_key": failed_item["file_key"]},
        )
        self.assertEqual("collaboration.file.retried", retried.kind)
        self.assertEqual(
            0,
            progress_events[0].payload["file_progress"]["transferred_bytes"],
        )
        self.assertGreater(
            progress_events[0].payload["file_progress"]["progress_revision"],
            failed_revision,
        )
        self.assertTrue(progress_events[-1].payload["file_progress"]["complete"])
        self.assertEqual(
            progress_events[-1].payload["file_progress"]["progress_revision"],
            retried.payload["collaboration"]["files"]["progress_revision"],
        )
        retry_transfer_keys = {
            event.payload["file_progress"]["transfer_key"]
            for event in progress_events
        }
        self.assertEqual(1, len(retry_transfer_keys))
        retry_transfer_key = next(iter(retry_transfer_keys))
        self.assertNotEqual(failed_transfer_key, retry_transfer_key)
        self.assertEqual(
            retried.payload["collaboration"]["files"]["transfer_progress"]["transfer_key"],
            retry_transfer_key,
        )

    def test_retired_browser_session_ignores_remaining_old_attempt_progress(self) -> None:
        self.selected_file = self.root / "retire-during-progress.pgn"
        self.selected_file.write_bytes(b"0123456789")
        self.files.scan_state = "clean"
        self.files.progress_samples = (
            FileTransferProgress("attachment-ui-1", 4, 10),
            FileTransferProgress("attachment-ui-1", 8, 10),
        )
        progress_events = []
        view = self.webview()
        original_session_key = view.snapshot()["session_key"]

        def retire_on_first_progress(event):
            progress_events.append(event)
            view.retire_browser_session()

        view.set_file_progress_event_sink(retire_on_first_progress)

        uploaded = view.dispatch("collaboration.file.choose_upload", {})

        self.assertEqual("collaboration.file.sent", uploaded.kind)
        self.assertEqual(1, len(progress_events))
        self.assertEqual(
            0,
            progress_events[0].payload["file_progress"]["transferred_bytes"],
        )
        self.assertEqual(
            original_session_key,
            progress_events[0].payload["file_progress"]["session_key"],
        )
        current = uploaded.payload["collaboration"]
        self.assertNotEqual(original_session_key, current["session_key"])
        self.assertIsNone(current["files"]["transfer_progress"])
        self.assertEqual(0, current["files"]["progress_revision"])
        self.assertIsNone(view._file_progress)
        self.assertIsNone(view._file_progress_attempt_token)
        self.assertIsNone(view._file_progress_event_sink)
        self.assertEqual(
            "stored",
            self.store.room_attachments("room-1")[0].transfer_state,
        )

    def test_retired_browser_session_ignores_remaining_retry_progress(self) -> None:
        self.selected_file = self.root / "retire-during-retry.pgn"
        self.selected_file.write_bytes(b"0123456789")
        self.files.fail_upload = True
        view = self.webview()

        failed = view.dispatch("collaboration.file.choose_upload", {})
        self.assertEqual("error", failed.kind)
        failed_item = failed.payload["collaboration"]["files"]["items"][0]
        self.assertTrue(failed_item["can_retry"])
        self.assertEqual(1, len(view._prepared))

        self.files.fail_upload = False
        self.files.scan_state = "clean"
        self.files.progress_samples = (
            FileTransferProgress("attachment-ui-1", 5, 10),
            FileTransferProgress("attachment-ui-1", 9, 10),
        )
        progress_events = []
        original_session_key = view.snapshot()["session_key"]

        def retire_on_first_progress(event):
            progress_events.append(event)
            view.retire_browser_session()

        view.set_file_progress_event_sink(retire_on_first_progress)

        retried = view.dispatch(
            "collaboration.file.retry",
            {"file_key": failed_item["file_key"]},
        )

        self.assertEqual("collaboration.file.retried", retried.kind)
        self.assertEqual(1, len(progress_events))
        self.assertEqual(
            0,
            progress_events[0].payload["file_progress"]["transferred_bytes"],
        )
        current = retried.payload["collaboration"]
        self.assertNotEqual(original_session_key, current["session_key"])
        self.assertIsNone(current["files"]["transfer_progress"])
        self.assertEqual(0, current["files"]["progress_revision"])
        self.assertEqual({}, view._prepared)
        self.assertIsNone(view._file_progress)
        self.assertIsNone(view._file_progress_attempt_token)
        self.assertIsNone(view._file_progress_event_sink)
        self.assertEqual(
            "stored",
            self.store.room_attachments("room-1")[0].transfer_state,
        )
        self.assertNotIn(str(self.selected_file), repr(retried.payload))

    def test_broken_file_progress_sink_cannot_turn_valid_upload_into_failure(self) -> None:
        self.selected_file = self.root / "progress-sink-failure.pgn"
        self.selected_file.write_bytes(b"abc")
        self.files.scan_state = "clean"

        def broken_sink(_event):
            raise RuntimeError("browser event channel disappeared")

        view = self.webview(file_progress_event_sink=broken_sink)
        uploaded = view.dispatch("collaboration.file.choose_upload", {})

        self.assertEqual("collaboration.file.sent", uploaded.kind)
        self.assertEqual(
            "stored",
            self.store.room_attachments("room-1")[0].transfer_state,
        )
        self.assertNotIn("browser event channel", repr(uploaded.payload))

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
        self.assertEqual(
            "File transfer failed: nonretriable.pgn.",
            event.payload["message"],
        )
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

    def test_stale_host_moderation_flag_cannot_outlive_canonical_role(self) -> None:
        teacher_controller = ClassroomCollaborationController(
            room_id="room-1",
            local_participant_id="teacher-1",
            roster=self.roster,
            chat=FakeChat(),
            files=FakeFiles(),
            store=self.store,
            file_store=self.file_store,
        )
        teacher_controller.receive_chat(
            ChatMessageMetadata(
                "student-message-role-change",
                "room-1",
                "student-2",
                0,
                "Role changed",
                sent_at_unix_ms=1700000000000,
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
        self.assertTrue(view.snapshot()["chat"]["moderation_available"])

        self.roster.roles["teacher-1"] = ClassroomRole.STUDENT
        snapshot = view.snapshot()
        self.assertFalse(snapshot["chat"]["moderation_available"])
        message = snapshot["chat"]["messages"][0]
        self.assertFalse(message["can_hide"])
        self.assertFalse(message["can_moderate_sender"])
        self.assertFalse(message["can_remove_sender"])
        self.assertNotIn("message_key", message)

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

    def test_retire_browser_session_invalidates_keys_and_releases_ephemeral_state(self) -> None:
        self.selected_file = self.root / "retire-clean.pgn"
        self.selected_file.write_text(
            '[Event "Retire clean"]\n\n1. e4 e5 *\n',
            encoding="utf-8",
        )
        self.files.scan_state = "clean"
        progress_events = []
        view = self.webview(file_progress_event_sink=progress_events.append)
        self.assertIsNotNone(view._file_progress_event_sink)
        old_session_key = view.snapshot()["session_key"]
        self.assertEqual(32, len(old_session_key))

        uploaded = view.dispatch("collaboration.file.choose_upload", {})
        clean_item = next(
            item
            for item in uploaded.payload["collaboration"]["files"]["items"]
            if item["name"] == "retire-clean.pgn"
        )
        old_file_key = clean_item["file_key"]
        old_file_dom_id = clean_item["dom_id"]
        self.assertEqual(
            old_file_dom_id,
            next(
                item["dom_id"]
                for item in view.snapshot()["files"]["items"]
                if item["name"] == "retire-clean.pgn"
            ),
        )

        self.chat.ordered.append(
            ChatMessageMetadata(
                "remote-retire-message",
                "room-1",
                "student-2",
                0,
                "Unread before unbind",
                sent_at_unix_ms=1700000000000,
            )
        )
        synced = view.dispatch("collaboration.chat.sync", {})
        self.assertEqual(1, synced.payload["collaboration"]["chat"]["unread_count"])
        old_message_dom_id = synced.payload["collaboration"]["chat"]["messages"][0][
            "dom_id"
        ]

        with mock.patch.object(
            self.controller,
            "send_chat",
            side_effect=RuntimeError("ambiguous send"),
        ):
            failed_send = view.dispatch(
                "collaboration.chat.send",
                {"body": "Pending before unbind"},
            )
        self.assertEqual("error", failed_send.kind)
        self.assertEqual(1, len(view._pending_chat))
        pending_before_retire = dict(view._pending_chat)
        self.assertNotIn("Pending before unbind", repr(view._pending_chat))

        self.selected_file = self.root / "retire-retry.pgn"
        self.selected_file.write_text(
            '[Event "Retire retry"]\n\n1. d4 d5 *\n',
            encoding="utf-8",
        )
        self.files.fail_upload = True
        failed_upload = view.dispatch("collaboration.file.choose_upload", {})
        self.assertEqual("error", failed_upload.kind)
        self.assertEqual(1, len(view._prepared))

        view._chat_page_bucket = 4
        view._file_page_bucket = 5
        view._removed_participant_ids.add("student-2")
        view.retire_browser_session()

        self.assertIsNone(view._file_progress_event_sink)
        self.assertIsNone(view._file_progress_attempt_token)
        self.assertEqual(pending_before_retire, view._pending_chat)
        self.assertEqual({}, view._prepared)
        self.assertIsNone(view._chat_page_bucket)
        self.assertIsNone(view._file_page_bucket)
        self.assertEqual(set(), view._removed_participant_ids)
        snapshot = view.snapshot()
        self.assertEqual(0, snapshot["chat"]["unread_count"])
        self.assertNotEqual(old_session_key, snapshot["session_key"])
        self.assertEqual(32, len(snapshot["session_key"]))
        self.assertIsNone(snapshot["files"]["transfer_progress"])

        stale = view.dispatch(
            "collaboration.file.save",
            {"file_key": old_file_key},
        )
        self.assertEqual("error", stale.kind)
        self.assertEqual([], self.save_calls)

        current_clean = next(
            item
            for item in snapshot["files"]["items"]
            if item["name"] == "retire-clean.pgn"
        )
        self.assertNotEqual(old_file_key, current_clean["file_key"])
        self.assertNotEqual(old_file_dom_id, current_clean["dom_id"])
        current_message = next(
            item
            for item in snapshot["chat"]["messages"]
            if item["body"] == "Unread before unbind"
        )
        self.assertNotEqual(old_message_dom_id, current_message["dom_id"])
        self.assertNotIn("remote-retire-message", current_message["dom_id"])
        saved = view.dispatch(
            "collaboration.file.save",
            {"file_key": current_clean["file_key"]},
        )
        self.assertEqual("collaboration.file.saved", saved.kind)
        self.assertEqual(
            [("short-lived-read-token", "retire-clean.pgn")],
            self.save_calls,
        )

    def test_file_sync_drops_retry_source_after_authoritative_recovery(self) -> None:
        self.selected_file = self.root / "ambiguous-recovered.pgn"
        self.selected_file.write_text(
            '[Event "Recovered"]\n\n1. e4 e5 *\n',
            encoding="utf-8",
        )
        self.files.fail_upload = True
        view = self.webview()

        failed_event = view.dispatch("collaboration.file.choose_upload", {})
        self.assertEqual("error", failed_event.kind)
        self.assertEqual(1, len(view._prepared))
        failed = self.store.room_attachments("room-1")[0]
        authoritative = replace(
            failed,
            sequence_no=0,
            transfer_state="stored",
            scan_state="clean",
        )
        self.files.fail_upload = False
        self.files.history_override = (authoritative,)

        synced = view.dispatch("collaboration.file.sync", {})

        self.assertEqual("collaboration.files.synced", synced.kind)
        self.assertEqual({}, view._prepared)
        item = synced.payload["collaboration"]["files"]["items"][0]
        self.assertFalse(item["can_retry"])
        self.assertTrue(item["can_save"])
        self.assertTrue(item["can_open"])
        self.assertNotIn(str(self.selected_file), repr(synced.payload))

    def test_failed_upload_exposes_bounded_retry_without_browser_path(self) -> None:
        self.selected_file = self.root / "retry.pgn"
        self.selected_file.write_text('[Event "Test"]\n\n1. e4 e5 *\n', encoding="utf-8")
        self.files.fail_upload = True
        progress_events = []
        view = self.webview(file_progress_event_sink=progress_events.append)

        failed = view.dispatch("collaboration.file.choose_upload", {})
        self.assertEqual("error", failed.kind)
        self.assertEqual(
            "File transfer failed: retry.pgn.",
            failed.payload["message"],
        )
        item = failed.payload["collaboration"]["files"]["items"][0]
        self.assertTrue(item["can_retry"])
        self.assertIsNone(
            failed.payload["collaboration"]["files"]["transfer_progress"]
        )
        failed_attempt_keys = {
            event.payload["file_progress"]["transfer_key"]
            for event in progress_events
        }
        self.assertEqual(1, len(failed_attempt_keys))
        failed_attempt_key = next(iter(failed_attempt_keys))
        self.assertNotIn(str(self.selected_file), repr(failed.payload))

        self.files.fail_upload = False
        progress_events.clear()
        retry_size = self.selected_file.stat().st_size
        self.files.progress_samples = (
            FileTransferProgress("attachment-ui-1", retry_size // 2, retry_size),
        )
        retried = view.dispatch("collaboration.file.retry", {"file_key": item["file_key"]})
        self.assertEqual("collaboration.file.retried", retried.kind)
        self.assertEqual(
            [0, retry_size // 2, retry_size],
            [
                event.payload["file_progress"]["transferred_bytes"]
                for event in progress_events
            ],
        )
        self.assertTrue(progress_events[-1].payload["file_progress"]["complete"])
        retry_attempt_keys = {
            event.payload["file_progress"]["transfer_key"]
            for event in progress_events
        }
        self.assertEqual(1, len(retry_attempt_keys))
        retry_attempt_key = next(iter(retry_attempt_keys))
        self.assertNotEqual(failed_attempt_key, retry_attempt_key)
        self.assertEqual(
            retry_attempt_key,
            retried.payload["collaboration"]["files"]["transfer_progress"]["transfer_key"],
        )
        self.assertTrue(
            retried.payload["collaboration"]["files"]["transfer_progress"]["complete"]
        )
        self.assertEqual(
            "File retry completed: retry.pgn.",
            retried.payload["announcement"],
        )
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
        self.assertEqual(
            "File transfer cancelled: cancel.pgn.",
            cancelled.payload["announcement"],
        )
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
        self.assertEqual({}, view._prepared)
        self.assertNotIn(str(self.selected_file), repr(retried.payload))

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
        self.assertEqual(
            "File transfer failed: terminal-failure.pgn.",
            uploaded.payload["message"],
        )
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
        self.assertEqual(
            "File retry failed: terminal-failure.pgn.",
            retried.payload["message"],
        )
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
        self.assertEqual(
            "File retry failed: blocked-after-retry.pgn.",
            retried.payload["message"],
        )
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

    def test_trusted_host_retention_policy_is_explicit_and_browser_cannot_override(self) -> None:
        self.selected_file = self.root / "retention.pgn"
        self.selected_file.write_text(
            '[Event "Retention"]\n\n1. e4 e5 *\n',
            encoding="utf-8",
        )
        self.files.scan_state = "clean"
        view = self.webview(
            chat_retention="persistent",
            file_retention="transient",
        )

        initial = view.snapshot()
        self.assertEqual(
            "New message retention: persistent",
            initial["chat"]["retention_policy_label"],
        )
        self.assertEqual(
            "New file retention: transient",
            initial["files"]["retention_policy_label"],
        )

        sent = view.dispatch("collaboration.chat.send", {"body": "Keep this"})
        self.assertEqual("persistent", self.store.room_messages("room-1")[0].retention)
        self.assertEqual(
            "Retention: persistent",
            sent.payload["collaboration"]["chat"]["messages"][0]["retention_label"],
        )

        uploaded = view.dispatch("collaboration.file.choose_upload", {})
        self.assertEqual(
            "transient",
            self.store.room_attachments("room-1")[0].retention,
        )
        self.assertEqual(
            "Retention: transient",
            uploaded.payload["collaboration"]["files"]["items"][0]["retention_label"],
        )

        rejected_chat = view.dispatch(
            "collaboration.chat.send",
            {"body": "Browser override", "retention": "transient"},
        )
        self.assertEqual("error", rejected_chat.kind)
        self.assertEqual(1, len(self.store.room_messages("room-1")))
        rejected_file = view.dispatch(
            "collaboration.file.choose_upload",
            {"retention": "persistent"},
        )
        self.assertEqual("error", rejected_file.kind)
        self.assertEqual(1, len(self.store.room_attachments("room-1")))

        with self.assertRaises(ValueError):
            self.webview(chat_retention="forever")
        with self.assertRaises(ValueError):
            self.webview(file_retention="forever")

    def test_language_switch_advances_active_file_progress_projection(self) -> None:
        self.selected_file = self.root / "localized-progress.pgn"
        self.selected_file.write_bytes(b"abcd")
        self.files.scan_state = "clean"
        view = self.webview(language=UILanguage.EN)

        uploaded = view.dispatch("collaboration.file.choose_upload", {})
        self.assertEqual("collaboration.file.sent", uploaded.kind)
        en_files = uploaded.payload["collaboration"]["files"]
        en_progress = en_files["transfer_progress"]
        self.assertIsNotNone(en_progress)
        assert en_progress is not None
        self.assertEqual(en_files["progress_revision"], en_progress["progress_revision"])
        en_revision = en_progress["progress_revision"]
        transfer_key = en_progress["transfer_key"]
        self.assertEqual("File transfer progress", en_progress["label"])
        self.assertIn("Transferred", en_progress["text"])

        view.set_language(UILanguage.UA)
        ua_files = view.snapshot()["files"]
        ua_progress = ua_files["transfer_progress"]
        self.assertIsNotNone(ua_progress)
        assert ua_progress is not None
        self.assertEqual(en_revision + 1, ua_files["progress_revision"])
        self.assertEqual(ua_files["progress_revision"], ua_progress["progress_revision"])
        self.assertEqual(transfer_key, ua_progress["transfer_key"])
        self.assertEqual(en_progress["transferred_bytes"], ua_progress["transferred_bytes"])
        self.assertEqual(en_progress["total_bytes"], ua_progress["total_bytes"])
        self.assertEqual("Прогрес передавання файла", ua_progress["label"])
        self.assertIn("Передано", ua_progress["text"])

        # Re-applying the same language is not a new projection generation.
        stable_revision = ua_files["progress_revision"]
        view.set_language(UILanguage.UA)
        self.assertEqual(
            stable_revision,
            view.snapshot()["files"]["progress_revision"],
        )

    def test_language_switch_cannot_overflow_progress_revision(self) -> None:
        self.selected_file = self.root / "revision-boundary.bin"
        self.selected_file.write_bytes(b"x")
        view = self.webview(language=UILanguage.EN)

        uploaded = view.dispatch("collaboration.file.choose_upload", {})
        self.assertEqual("collaboration.file.sent", uploaded.kind)
        self.assertIsNotNone(view._file_progress)
        view._file_progress_revision = MAX_WIRE_INTEGER

        with self.assertRaisesRegex(
            RuntimeError,
            "file progress presentation revision exhausted",
        ):
            view.set_language(UILanguage.UA)

        self.assertEqual(UILanguage.EN, view.language)
        self.assertEqual(MAX_WIRE_INTEGER, view._file_progress_revision)
        self.assertEqual(
            MAX_WIRE_INTEGER,
            view.snapshot()["files"]["progress_revision"],
        )

    def test_language_switch_changes_presentation_without_rebuilding_core(self) -> None:
        view = self.webview(language=UILanguage.EN)
        self.assertEqual("Chat", view.snapshot()["chat"]["heading"])
        self.assertEqual("Unread", view.snapshot()["chat"]["unread_message_label"])
        self.assertEqual("Message time", view.snapshot()["chat"]["timestamp_label"])
        self.assertEqual("Refresh files", view.snapshot()["files"]["sync_label"])
        self.assertEqual(
            "Sending message…",
            view.snapshot()["chat"]["send_pending_label"],
        )
        self.assertEqual(
            "Refreshing files…",
            view.snapshot()["files"]["sync_pending_label"],
        )
        self.assertEqual(
            "Choosing or sending file…",
            view.snapshot()["files"]["choose_upload_pending_label"],
        )
        self.assertEqual(
            "New message retention: session",
            view.snapshot()["chat"]["retention_policy_label"],
        )
        self.assertEqual(
            "New file retention: session",
            view.snapshot()["files"]["retention_policy_label"],
        )
        view.set_language(UILanguage.UA)
        self.assertEqual("Чат", view.snapshot()["chat"]["heading"])
        self.assertEqual("Непрочитане", view.snapshot()["chat"]["unread_message_label"])
        self.assertEqual("Час повідомлення", view.snapshot()["chat"]["timestamp_label"])
        self.assertEqual("Оновити файли", view.snapshot()["files"]["sync_label"])
        self.assertEqual(
            "Надсилання повідомлення…",
            view.snapshot()["chat"]["send_pending_label"],
        )
        self.assertEqual(
            "Оновлення файлів…",
            view.snapshot()["files"]["sync_pending_label"],
        )
        self.assertEqual(
            "Вибір або надсилання файла…",
            view.snapshot()["files"]["choose_upload_pending_label"],
        )
        self.assertEqual(
            "Зберігання нових повідомлень: session (сесійне)",
            view.snapshot()["chat"]["retention_policy_label"],
        )
        self.assertEqual(
            "Зберігання нових файлів: session (сесійне)",
            view.snapshot()["files"]["retention_policy_label"],
        )


if __name__ == "__main__":
    unittest.main()
