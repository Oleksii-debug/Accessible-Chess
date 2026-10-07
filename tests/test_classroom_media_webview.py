from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from acs.classroom_media_webview_bridge import ClassroomMediaWebViewBridge
from acs.classroom_media_webview_projection import ClassroomMediaWebViewProjection
from acs.classroom_realtime_media import (
    ClassroomMediaController,
    ClassroomRole,
    JoinCredential,
    MediaSource,
)
from acs.full_product_ui_shell import UILanguage
from acs.version2_final_product_application import Version2FinalProductApplication


NOW = datetime(2026, 10, 2, 20, 0, tzinfo=timezone.utc)


class FakeRoster:
    def __init__(self) -> None:
        self.roles = {
            "teacher-1": ClassroomRole.TEACHER,
            "co-1": ClassroomRole.CO_TEACHER,
            "student-1": ClassroomRole.STUDENT,
            "student-2": ClassroomRole.STUDENT,
            "observer-1": ClassroomRole.OBSERVER,
        }
        self.board = {
            "teacher-1": True,
            "co-1": True,
            "student-1": True,
            "student-2": False,
            "observer-1": False,
        }

    def participant_ids(self):
        return tuple(self.roles)

    def role_for(self, participant_id):
        return self.roles[participant_id]

    def board_control_allowed(self, participant_id):
        return self.board[participant_id]


class FakeMedia:
    def __init__(self) -> None:
        self.local_calls = []
        self.moderation_calls = []

    def connect(self, credential, *, enabled_sources):
        return None

    def reconnect(self, credential, *, enabled_sources):
        return None

    def disconnect(self):
        return None

    def set_local_source(self, source, enabled):
        self.local_calls.append((source, enabled))

    def apply_moderation(self, commands):
        self.moderation_calls.append(commands)

    def recover_device(self, kind, device_id, *, republish_enabled):
        return None


def join_credential(participant_id: str) -> JoinCredential:
    return JoinCredential(
        room_id="room-1",
        participant_id=participant_id,
        token="short-lived-token",
        issued_at=NOW,
        expires_at=NOW + timedelta(seconds=60),
    )


def composition(participant_id: str):
    roster = FakeRoster()
    media = FakeMedia()
    controller = ClassroomMediaController(
        local_participant_id=participant_id,
        roster=roster,
        media=media,
    )
    controller.join(
        join_credential(participant_id),
        now=NOW + timedelta(seconds=1),
    )
    labels = {
        "teacher-1": "Teacher",
        "co-1": "Co-teacher",
        "student-1": "Student One",
        "student-2": "Student Two",
        "observer-1": "Observer",
    }
    serial = iter(
        (
            "ui-op-1",
            "ui-op-2",
            "ui-op-3",
            "ui-op-4",
            "ui-op-5",
            "ui-op-6",
        )
    )
    projection = ClassroomMediaWebViewProjection(
        controller,
        lambda: dict(labels),
        language=UILanguage.EN,
        operation_id_factory=lambda: next(serial),
    )
    return controller, roster, media, labels, projection, ClassroomMediaWebViewBridge(projection)


def participant(snapshot, label: str):
    return next(item for item in snapshot["participants"] if item["label"] == label)


def test_student_snapshot_separates_local_enabled_permission_soft_mute_and_board_control():
    controller, _roster, _media, _labels, projection, _bridge = composition("student-1")
    controller.set_local_source(MediaSource.MICROPHONE, True)

    snapshot = projection.snapshot()
    own = snapshot["own"]

    assert snapshot["connected"] is True
    assert own["label"] == "Student One"
    assert own["microphone"] == {
        "publish_allowed": True,
        "soft_muted": False,
        "local_enabled": True,
    }
    assert own["camera"] == {
        "publish_allowed": True,
        "soft_muted": False,
        "local_enabled": False,
    }
    assert own["board_control_allowed"] is True
    assert own["actions"][0]["command"] == "media.local_source"
    assert participant(snapshot, "Student Two")["camera"]["local_enabled"] is None
    assert participant(snapshot, "Student Two")["actions"] == ()
    assert "student-1" not in repr(snapshot)
    assert "room-1" not in repr(snapshot)
    assert "short-lived-token" not in repr(snapshot)


def test_participant_order_is_stable_when_label_mapping_iteration_changes():
    controller, _roster, _media, labels, _projection, _bridge = composition("teacher-1")
    canonical_ids = tuple(labels)
    calls = 0

    def alternating_labels():
        nonlocal calls
        order = canonical_ids if calls % 2 == 0 else tuple(reversed(canonical_ids))
        calls += 1
        return {participant_id: labels[participant_id] for participant_id in order}

    projection = ClassroomMediaWebViewProjection(
        controller,
        alternating_labels,
        language=UILanguage.EN,
        operation_id_factory=lambda: "ui-order-test",
    )

    first = projection.snapshot()["participants"]
    second = projection.snapshot()["participants"]

    expected_labels = sorted(labels.values(), key=str.casefold)
    assert [item["label"] for item in first] == expected_labels
    assert [item["label"] for item in second] == expected_labels
    assert [item["participant_key"] for item in first] == [
        item["participant_key"] for item in second
    ]


def test_teacher_projection_exposes_only_role_allowed_moderation_and_keeps_board_authority_independent():
    controller, roster, media, _labels, projection, bridge = composition("teacher-1")
    snapshot = projection.snapshot()

    teacher = participant(snapshot, "Teacher")
    student = participant(snapshot, "Student One")
    co_teacher = participant(snapshot, "Co-teacher")
    assert teacher["actions"] == ()
    assert {item["command"] for item in student["actions"]} == {
        "media.soft_mute",
        "media.publish_permission",
        "media.remove",
    }
    assert {item["command"] for item in co_teacher["actions"]} == {
        "media.soft_mute",
        "media.publish_permission",
        "media.remove",
    }

    key = student["participant_key"]
    event = bridge.dispatch(
        "media.publish_permission",
        {"participant_key": key, "source": "microphone", "allowed": False},
    )
    assert event.kind == "media-updated"
    assert controller.participant_policy("student-1").source(
        MediaSource.MICROPHONE
    ).publish_allowed is False
    assert controller.participant_policy("student-1").board_control_allowed is True
    assert roster.board["student-1"] is True
    command = media.moderation_calls[-1][0]
    assert command.actor_id == "teacher-1"
    assert command.target_id == "student-1"
    assert command.operation_id == "ui-op-1"


def test_bridge_never_accepts_raw_roster_identity_or_browser_operation_id():
    _controller, _roster, media, _labels, projection, bridge = composition("teacher-1")
    student = participant(projection.snapshot(), "Student One")

    invalid = (
        (
            "media.publish_permission",
            {
                "participant_key": "student-1",
                "source": "camera",
                "allowed": False,
            },
        ),
        (
            "media.publish_permission",
            {
                "participant_key": student["participant_key"],
                "source": "camera",
                "allowed": False,
                "operation_id": "attacker-chosen",
            },
        ),
        (
            "media.publish_permission",
            {
                "participant_key": student["participant_key"],
                "source": "screen_share",
                "allowed": False,
            },
        ),
    )
    for command, payload in invalid:
        event = bridge.dispatch(command, payload)
        assert event.kind == "error"
    assert media.moderation_calls == []


def test_own_microphone_and_camera_actions_are_keyboard_button_ready_and_controller_enforced():
    controller, _roster, media, _labels, projection, bridge = composition("student-1")
    own = projection.snapshot()["own"]
    microphone_action = next(
        item for item in own["actions"] if item["payload"]["source"] == "microphone"
    )

    event = bridge.dispatch(
        microphone_action["command"],
        microphone_action["payload"],
    )
    assert event.kind == "media-updated"
    assert media.local_calls[-1] == (MediaSource.MICROPHONE, True)
    assert MediaSource.MICROPHONE in controller.state.desired_sources
    assert event.payload["focus_target"] == "media-own-microphone-toggle"

    controller.set_publish_permission(
        actor_id="teacher-1",
        target_id="student-1",
        source=MediaSource.CAMERA,
        allowed=False,
        operation_id="external-camera-lock",
    )
    own = projection.snapshot()["own"]
    assert not any(
        item["payload"]["source"] == "camera" and item["payload"]["enabled"] is True
        for item in own["actions"]
    )


def test_batch_controls_target_students_only_and_do_not_change_board_control():
    controller, roster, media, _labels, projection, bridge = composition("teacher-1")
    before = {key: roster.board[key] for key in roster.board}

    event = bridge.dispatch(
        "media.all_publish_permission",
        {"source": "camera", "allowed": False},
    )
    assert event.kind == "media-updated"
    commands = media.moderation_calls[-1]
    assert {item.target_id for item in commands} == {"student-1", "student-2"}
    assert all(item.source is MediaSource.CAMERA for item in commands)
    assert {key: roster.board[key] for key in roster.board} == before
    assert controller.participant_policy("observer-1").source(
        MediaSource.CAMERA
    ).publish_allowed is False


def test_co_teacher_cannot_moderate_teacher_or_self_but_can_moderate_student():
    _controller, _roster, _media, _labels, projection, _bridge = composition("co-1")
    snapshot = projection.snapshot()

    assert participant(snapshot, "Teacher")["actions"] == ()
    assert participant(snapshot, "Co-teacher")["actions"] == ()
    assert participant(snapshot, "Student One")["actions"]


def test_snapshot_failure_is_sanitized_by_bridge_and_does_not_echo_labels():
    controller, _roster, media, labels, _projection, _bridge = composition("teacher-1")
    labels["student-1"] = "Secret\nLabel"
    projection = ClassroomMediaWebViewProjection(
        controller,
        lambda: dict(labels),
        language=UILanguage.EN,
    )
    bridge = ClassroomMediaWebViewBridge(projection)

    event = bridge.dispatch("media.snapshot", {})
    assert event.kind == "error"
    assert "Secret" not in event.payload["message"]
    assert media.moderation_calls == []


def test_removed_participant_state_stays_textual_and_no_chess_state_enters_projection():
    _controller, _roster, _media, _labels, projection, bridge = composition("teacher-1")
    student = participant(projection.snapshot(), "Student Two")
    event = bridge.dispatch(
        "media.remove",
        {"participant_key": student["participant_key"], "block": True},
    )
    assert event.kind == "media-updated"
    updated = participant(event.payload["snapshot"], "Student Two")
    assert updated["removed"] is True
    assert updated["blocked"] is True
    assert updated["actions"] == ()
    assert event.payload["focus_target"] == updated["dom_id"]
    lowered = repr(event.payload["snapshot"]).lower()
    assert "fen" not in lowered
    assert "make_move" not in lowered
    assert "pgn" not in lowered


def minimal_application(language=UILanguage.EN):
    application = object.__new__(Version2FinalProductApplication)
    application.shell = SimpleNamespace(language=language)
    application.media = None
    application.teacher = None
    application._teacher_state_provider = None
    application._teacher_dispatch = None
    application._assert_thread = lambda: None
    application._rebuild_education_bridge = lambda selected: None
    return application


def test_application_publishes_media_binding_only_after_safe_initial_projection():
    controller, _roster, _media, labels, _projection, _bridge = composition("student-1")
    application = minimal_application()

    application.bind_classroom_media(controller, lambda: dict(labels))
    assert application.media is not None
    event = application.browser_command("media", "media.snapshot", {})
    assert event["kind"] == "render"
    assert event["payload"]["snapshot"]["own"]["label"] == "Student One"

    try:
        application.bind_classroom_media(controller, lambda: dict(labels))
    except RuntimeError:
        pass
    else:
        raise AssertionError("duplicate media binding was accepted")

    application.unbind_classroom_media()
    assert application.media is None


def test_application_rejects_invalid_initial_media_projection_without_publishing_bridge():
    controller, _roster, _media, labels, _projection, _bridge = composition("student-1")
    application = minimal_application()
    labels.pop("student-1")

    try:
        application.bind_classroom_media(controller, lambda: dict(labels))
    except ValueError:
        pass
    else:
        raise AssertionError("invalid initial media projection was accepted")
    assert application.media is None


def test_media_provider_failure_does_not_abort_product_language_synchronization():
    controller, _roster, _media, labels, _projection, _bridge = composition("student-1")
    application = minimal_application(language=UILanguage.EN)
    application.bind_classroom_media(controller, lambda: dict(labels))
    assert application.media is not None

    labels["student-1"] = "broken\nlabel"
    application.sync_composed_surfaces_language(UILanguage.UA)

    assert application.media is not None
    assert application.media.projection.language is UILanguage.UA



def test_committed_local_media_action_enters_recovery_if_projection_fails_after_effect():
    controller, _roster, media, labels, _projection, bridge = composition("student-1")
    labels["student-1"] = "broken\nlabel"

    event = bridge.dispatch(
        "media.local_source",
        {"source": "microphone", "enabled": True},
    )

    assert event.kind == "media-updated"
    assert event.payload["snapshot"] is None
    assert event.payload["recovery_required"] is True
    assert event.payload["focus_target"] == "classroom-media-heading"
    assert event.payload["announcement"] == "Media state updated."
    assert media.local_calls[-1] == (MediaSource.MICROPHONE, True)
    assert MediaSource.MICROPHONE in controller.state.desired_sources

def test_disconnected_or_removed_room_state_exposes_no_live_moderation_controls():
    controller, _roster, _media, _labels, projection, _bridge = composition("teacher-1")
    connected = projection.snapshot()
    assert participant(connected, "Student One")["actions"]
    assert connected["all_student_actions"]

    controller.mark_transport_lost()
    disconnected = projection.snapshot()
    assert participant(disconnected, "Student One")["actions"] == ()
    assert disconnected["all_student_actions"] == ()

    reconnect_credential = JoinCredential(
        room_id="room-1",
        participant_id="teacher-1",
        token="fresh-reconnect-token",
        issued_at=NOW + timedelta(seconds=2),
        expires_at=NOW + timedelta(seconds=62),
    )
    controller.reconnect(
        reconnect_credential,
        now=NOW + timedelta(seconds=3),
    )
    controller.remove_participant(
        actor_id="teacher-1",
        target_id="student-1",
        block=True,
        operation_id="remove-before-projection",
    )
    removed = participant(projection.snapshot(), "Student One")
    assert removed["removed"] is True
    assert removed["blocked"] is True
    assert removed["actions"] == ()


def test_participant_focus_ids_use_full_opaque_key_without_truncation():
    _controller, _roster, _media, _labels, projection, _bridge = composition("teacher-1")
    student = participant(projection.snapshot(), "Student One")
    key = student["participant_key"]
    assert len(key) == 64
    assert student["dom_id"] == "media-participant-" + key
    for action in student["actions"]:
        assert key in action["id"]
