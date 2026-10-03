from __future__ import annotations

import asyncio
from importlib import metadata
from types import SimpleNamespace
import traceback
import unittest

from acs.classroom_realtime_media import (
    MediaSource,
    ModerationAction,
    ModerationCommand,
)
from acs.livekit_classroom_moderation_admin import (
    LIVEKIT_API_VERSION,
    LiveKitClassroomModerationAdmin,
    LiveKitClassroomModerationAdminError,
)


class FakeServerError(Exception):
    def __init__(self, code, message="provider detail"):
        super().__init__(message)
        self.code = code


class FakeServerErrorCode:
    NOT_FOUND = "not_found"


class FakeTrackSource:
    CAMERA = 1
    MICROPHONE = 2
    SCREEN_SHARE = 3
    SCREEN_SHARE_AUDIO = 4


class FakeParticipantPermission:
    fields = (
        "can_subscribe",
        "can_publish",
        "can_publish_data",
        "can_publish_sources",
        "hidden",
        "can_update_metadata",
        "can_subscribe_metrics",
        "can_manage_agent_session",
    )

    def __init__(
        self,
        *,
        can_subscribe=True,
        can_publish=False,
        can_publish_data=False,
        can_publish_sources=(),
        hidden=False,
        can_update_metadata=False,
        can_subscribe_metrics=False,
        can_manage_agent_session=False,
    ):
        self.can_subscribe = can_subscribe
        self.can_publish = can_publish
        self.can_publish_data = can_publish_data
        self.can_publish_sources = list(can_publish_sources)
        self.hidden = hidden
        self.can_update_metadata = can_update_metadata
        self.can_subscribe_metrics = can_subscribe_metrics
        self.can_manage_agent_session = can_manage_agent_session

    def CopyFrom(self, other):
        for name in self.fields:
            value = getattr(other, name)
            setattr(self, name, list(value) if name == "can_publish_sources" else value)


class Request:
    def __init__(self, **kwargs):
        for name, value in kwargs.items():
            setattr(self, name, value)


class FakeApi:
    ParticipantPermission = FakeParticipantPermission
    UpdateParticipantRequest = Request
    RoomParticipantIdentity = Request
    MuteRoomTrackRequest = Request
    ServerError = FakeServerError
    ServerErrorCode = FakeServerErrorCode
    TrackSource = FakeTrackSource


class FakeRoomService:
    def __init__(self, participant=None):
        self.participant = participant
        self.lookups = []
        self.updates = []
        self.mutes = []
        self.removals = []
        self.get_error = None
        self.update_error = None
        self.mute_error = None
        self.remove_error = None

    async def get_participant(self, request):
        self.lookups.append(request)
        if self.get_error is not None:
            raise self.get_error
        return self.participant

    async def update_participant(self, request):
        self.updates.append(request)
        if self.update_error is not None:
            raise self.update_error
        self.participant = SimpleNamespace(
            identity=request.identity,
            permission=request.permission,
            tracks=list(getattr(self.participant, "tracks", ()) or ()),
        )
        return self.participant

    async def mute_published_track(self, request):
        self.mutes.append(request)
        if self.mute_error is not None:
            raise self.mute_error
        for value in list(getattr(self.participant, "tracks", ()) or ()):
            if getattr(value, "sid", None) == request.track_sid:
                value.muted = request.muted
                return SimpleNamespace(track=value)
        raise AssertionError("unknown track")

    async def remove_participant(self, request):
        self.removals.append(request)
        if self.remove_error is not None:
            raise self.remove_error
        return SimpleNamespace()


def participant(
    *,
    identity="student-1",
    sources=(FakeTrackSource.MICROPHONE, FakeTrackSource.CAMERA),
    can_publish=True,
    can_publish_data=False,
    tracks=(),
):
    return SimpleNamespace(
        identity=identity,
        permission=FakeParticipantPermission(
            can_subscribe=True,
            can_publish=can_publish,
            can_publish_data=can_publish_data,
            can_publish_sources=sources,
            can_update_metadata=False,
        ),
        tracks=list(tracks),
    )


def command(action, *, source=None, value=True, target="student-1", operation="op-1"):
    return ModerationCommand(
        operation_id=operation,
        actor_id="teacher-1",
        target_id=target,
        action=action,
        source=source,
        value=value,
    )


class LiveKitClassroomModerationAdminTests(unittest.TestCase):
    def admin(self, room=None):
        room = room or FakeRoomService(participant())
        return (
            LiveKitClassroomModerationAdmin(
                room_service=room,
                api_module=FakeApi,
                sdk_version=LIVEKIT_API_VERSION,
            ),
            room,
        )

    def apply(self, admin, value):
        return asyncio.run(
            admin.apply_moderation_command(room_id="room-1", command=value)
        )

    def matches(self, admin, value):
        return asyncio.run(
            admin.moderation_effect_matches(room_id="room-1", command=value)
        )

    def test_state_verifier_reads_publish_permission_without_mutation(self):
        admin, room = self.admin()
        self.assertTrue(
            self.matches(
                admin,
                command(
                    ModerationAction.PUBLISH_PERMISSION,
                    source=MediaSource.MICROPHONE,
                    value=True,
                ),
            )
        )
        self.assertFalse(
            self.matches(
                admin,
                command(
                    ModerationAction.PUBLISH_PERMISSION,
                    source=MediaSource.SCREEN_SHARE,
                    value=True,
                    operation="op-screen",
                ),
            )
        )
        self.assertTrue(
            self.matches(
                admin,
                command(
                    ModerationAction.PUBLISH_PERMISSION,
                    source=MediaSource.SCREEN_SHARE,
                    value=False,
                    operation="op-screen-off",
                ),
            )
        )
        self.assertEqual(room.updates, [])
        self.assertEqual(room.mutes, [])
        self.assertEqual(room.removals, [])

    def test_state_verifier_reads_soft_mute_and_preserves_release_noop(self):
        tracks = (
            SimpleNamespace(
                sid="mic-muted",
                source=FakeTrackSource.MICROPHONE,
                muted=True,
            ),
            SimpleNamespace(
                sid="camera-open",
                source=FakeTrackSource.CAMERA,
                muted=False,
            ),
        )
        room = FakeRoomService(participant(tracks=tracks))
        admin, room = self.admin(room)
        self.assertTrue(
            self.matches(
                admin,
                command(
                    ModerationAction.SOFT_MUTE,
                    source=MediaSource.MICROPHONE,
                    value=True,
                ),
            )
        )
        room.participant.tracks.append(
            SimpleNamespace(
                sid="mic-open",
                source=FakeTrackSource.MICROPHONE,
                muted=False,
            )
        )
        self.assertFalse(
            self.matches(
                admin,
                command(
                    ModerationAction.SOFT_MUTE,
                    source=MediaSource.MICROPHONE,
                    value=True,
                    operation="op-mute-open",
                ),
            )
        )
        lookups_before_release = len(room.lookups)
        self.assertTrue(
            self.matches(
                admin,
                command(
                    ModerationAction.SOFT_MUTE,
                    source=MediaSource.MICROPHONE,
                    value=False,
                    operation="op-release",
                ),
            )
        )
        self.assertEqual(len(room.lookups), lookups_before_release)
        self.assertEqual(room.mutes, [])
        self.assertEqual(room.updates, [])
        self.assertEqual(room.removals, [])

    def test_state_verifier_treats_absent_microphone_track_as_satisfied_noop(self):
        room = FakeRoomService(
            participant(
                tracks=(
                    SimpleNamespace(
                        sid="camera-only",
                        source=FakeTrackSource.CAMERA,
                        muted=False,
                    ),
                )
            )
        )
        admin, room = self.admin(room)

        self.assertTrue(
            self.matches(
                admin,
                command(
                    ModerationAction.SOFT_MUTE,
                    source=MediaSource.MICROPHONE,
                    value=True,
                ),
            )
        )
        self.assertEqual(room.mutes, [])
        self.assertEqual(room.updates, [])
        self.assertEqual(room.removals, [])

    def test_state_verifier_requires_exact_boolean_microphone_state(self):
        tracks = (
            SimpleNamespace(
                sid="mic-invalid",
                source=FakeTrackSource.MICROPHONE,
                muted=1,
            ),
        )
        room = FakeRoomService(participant(tracks=tracks))
        admin, room = self.admin(room)
        with self.assertRaisesRegex(
            LiveKitClassroomModerationAdminError,
            "mute state is invalid",
        ):
            self.matches(
                admin,
                command(
                    ModerationAction.SOFT_MUTE,
                    source=MediaSource.MICROPHONE,
                    value=True,
                ),
            )
        self.assertEqual(room.mutes, [])

    def test_state_verifier_confirms_remove_only_from_provider_not_found(self):
        room = FakeRoomService(participant())
        admin, room = self.admin(room)
        remove = command(ModerationAction.REMOVE, value=True)
        self.assertFalse(self.matches(admin, remove))
        self.assertEqual(room.removals, [])

        room.get_error = FakeServerError(
            FakeServerErrorCode.NOT_FOUND,
            "already gone",
        )
        self.assertTrue(self.matches(admin, remove))
        self.assertEqual(room.removals, [])

    def test_state_verifier_provider_failure_and_identity_mismatch_fail_closed(self):
        secret = "provider-state-secret"
        room = FakeRoomService(participant())
        room.get_error = FakeServerError("internal", secret)
        admin, room = self.admin(room)
        with self.assertRaisesRegex(
            LiveKitClassroomModerationAdminError,
            "^LiveKit participant lookup failed$",
        ) as caught:
            self.matches(
                admin,
                command(ModerationAction.REMOVE, value=True),
            )
        self.assertNotIn(
            secret,
            "".join(traceback.format_exception(caught.exception)),
        )
        self.assertIsNone(caught.exception.__cause__)
        self.assertEqual(room.removals, [])

        wrong_room = FakeRoomService(participant(identity="other"))
        wrong_admin, wrong_room = self.admin(wrong_room)
        with self.assertRaisesRegex(
            LiveKitClassroomModerationAdminError,
            "identity is not canonical",
        ):
            self.matches(
                wrong_admin,
                command(
                    ModerationAction.PUBLISH_PERMISSION,
                    source=MediaSource.MICROPHONE,
                    value=True,
                ),
            )
        self.assertEqual(wrong_room.updates, [])
        self.assertEqual(wrong_room.mutes, [])
        self.assertEqual(wrong_room.removals, [])

    def test_disabling_one_source_preserves_other_explicit_provider_permission(self):
        admin, room = self.admin()
        self.apply(
            admin,
            command(
                ModerationAction.PUBLISH_PERMISSION,
                source=MediaSource.MICROPHONE,
                value=False,
            ),
        )
        self.assertEqual(len(room.lookups), 1)
        self.assertEqual(len(room.updates), 1)
        request = room.updates[0]
        self.assertEqual(request.room, "room-1")
        self.assertEqual(request.identity, "student-1")
        self.assertEqual(
            request.permission.can_publish_sources,
            [FakeTrackSource.CAMERA],
        )
        self.assertTrue(request.permission.can_publish)
        self.assertTrue(request.permission.can_subscribe)
        self.assertFalse(request.permission.can_publish_data)

    def test_already_achieved_publish_permission_is_provider_noop(self):
        admin, room = self.admin()
        self.apply(
            admin,
            command(
                ModerationAction.PUBLISH_PERMISSION,
                source=MediaSource.MICROPHONE,
                value=True,
            ),
        )
        self.assertEqual(len(room.lookups), 1)
        self.assertEqual(room.updates, [])

    def test_publish_update_response_must_confirm_exact_target_and_state(self):
        admin, room = self.admin()

        async def stale_update(request):
            room.updates.append(request)
            return participant(
                identity=request.identity,
                sources=(FakeTrackSource.MICROPHONE, FakeTrackSource.CAMERA),
                can_publish=True,
            )

        room.update_participant = stale_update
        with self.assertRaisesRegex(
            LiveKitClassroomModerationAdminError,
            "did not reach requested state",
        ):
            self.apply(
                admin,
                command(
                    ModerationAction.PUBLISH_PERMISSION,
                    source=MediaSource.CAMERA,
                    value=False,
                ),
            )

        async def wrong_identity(request):
            room.updates.append(request)
            return participant(
                identity="other",
                sources=(FakeTrackSource.MICROPHONE,),
                can_publish=True,
            )

        room.updates.clear()
        room.update_participant = wrong_identity
        with self.assertRaisesRegex(
            LiveKitClassroomModerationAdminError,
            "update identity is not canonical",
        ):
            self.apply(
                admin,
                command(
                    ModerationAction.PUBLISH_PERMISSION,
                    source=MediaSource.CAMERA,
                    value=False,
                    operation="op-2",
                ),
            )

    def test_disabling_last_source_turns_off_publish_capability(self):
        room = FakeRoomService(
            participant(sources=(FakeTrackSource.MICROPHONE,), can_publish=True)
        )
        admin, room = self.admin(room)
        self.apply(
            admin,
            command(
                ModerationAction.PUBLISH_PERMISSION,
                source=MediaSource.MICROPHONE,
                value=False,
            ),
        )
        permission = room.updates[0].permission
        self.assertEqual(permission.can_publish_sources, [])
        self.assertFalse(permission.can_publish)

    def test_enabling_source_from_explicit_nonpublishing_state_is_narrow(self):
        room = FakeRoomService(participant(sources=(), can_publish=False))
        admin, room = self.admin(room)
        self.apply(
            admin,
            command(
                ModerationAction.PUBLISH_PERMISSION,
                source=MediaSource.SCREEN_SHARE,
                value=True,
            ),
        )
        permission = room.updates[0].permission
        self.assertEqual(
            permission.can_publish_sources,
            [FakeTrackSource.SCREEN_SHARE],
        )
        self.assertTrue(permission.can_publish)
        self.assertFalse(permission.can_publish_data)

    def test_unrestricted_or_noncanonical_provider_permission_fails_closed(self):
        cases = (
            participant(sources=(), can_publish=True),
            participant(
                sources=(FakeTrackSource.MICROPHONE, FakeTrackSource.SCREEN_SHARE_AUDIO),
                can_publish=True,
            ),
            participant(
                sources=(FakeTrackSource.MICROPHONE,),
                can_publish=False,
            ),
        )
        for current in cases:
            with self.subTest(permission=current.permission.__dict__):
                room = FakeRoomService(current)
                admin, room = self.admin(room)
                with self.assertRaises(LiveKitClassroomModerationAdminError):
                    self.apply(
                        admin,
                        command(
                            ModerationAction.PUBLISH_PERMISSION,
                            source=MediaSource.CAMERA,
                            value=False,
                        ),
                    )
                self.assertEqual(room.updates, [])

    def test_publish_permission_preserves_rpc_data_permission(self):
        room = FakeRoomService(
            participant(
                sources=(FakeTrackSource.MICROPHONE, FakeTrackSource.CAMERA),
                can_publish=True,
                can_publish_data=True,
            )
        )
        admin, room = self.admin(room)

        self.apply(
            admin,
            command(
                ModerationAction.PUBLISH_PERMISSION,
                source=MediaSource.CAMERA,
                value=False,
            ),
        )

        permission = room.updates[0].permission
        self.assertEqual(
            permission.can_publish_sources,
            [FakeTrackSource.MICROPHONE],
        )
        self.assertTrue(permission.can_publish)
        self.assertTrue(permission.can_publish_data)

    def test_provider_identity_must_match_canonical_target(self):
        room = FakeRoomService(participant(identity="other"))
        admin, room = self.admin(room)
        with self.assertRaisesRegex(
            LiveKitClassroomModerationAdminError,
            "identity is not canonical",
        ):
            self.apply(
                admin,
                command(
                    ModerationAction.PUBLISH_PERMISSION,
                    source=MediaSource.CAMERA,
                    value=False,
                ),
            )
        self.assertEqual(room.updates, [])

    def test_soft_mute_only_mutes_current_unmuted_microphone_tracks(self):
        tracks = (
            SimpleNamespace(
                sid="mic-open",
                source=FakeTrackSource.MICROPHONE,
                muted=False,
            ),
            SimpleNamespace(
                sid="mic-muted",
                source=FakeTrackSource.MICROPHONE,
                muted=True,
            ),
            SimpleNamespace(
                sid="camera",
                source=FakeTrackSource.CAMERA,
                muted=False,
            ),
        )
        room = FakeRoomService(participant(tracks=tracks))
        admin, room = self.admin(room)
        self.apply(
            admin,
            command(
                ModerationAction.SOFT_MUTE,
                source=MediaSource.MICROPHONE,
                value=True,
            ),
        )
        self.assertEqual(len(room.mutes), 1)
        request = room.mutes[0]
        self.assertEqual(request.track_sid, "mic-open")
        self.assertTrue(request.muted)
        self.assertEqual(request.identity, "student-1")

    def test_soft_mute_response_must_confirm_exact_track_state(self):
        tracks = (
            SimpleNamespace(
                sid="mic-open",
                source=FakeTrackSource.MICROPHONE,
                muted=False,
            ),
        )
        room = FakeRoomService(participant(tracks=tracks))
        admin, room = self.admin(room)

        async def stale_mute(request):
            room.mutes.append(request)
            return SimpleNamespace(
                track=SimpleNamespace(sid=request.track_sid, muted=False)
            )

        room.mute_published_track = stale_mute
        with self.assertRaisesRegex(
            LiveKitClassroomModerationAdminError,
            "did not reach requested state",
        ):
            self.apply(
                admin,
                command(
                    ModerationAction.SOFT_MUTE,
                    source=MediaSource.MICROPHONE,
                    value=True,
                ),
            )

    def test_soft_mute_release_never_forces_remote_unmute(self):
        room = FakeRoomService(participant())
        admin, room = self.admin(room)
        self.apply(
            admin,
            command(
                ModerationAction.SOFT_MUTE,
                source=MediaSource.MICROPHONE,
                value=False,
            ),
        )
        self.assertEqual(room.lookups, [])
        self.assertEqual(room.mutes, [])

    def test_remove_is_idempotent_when_provider_reports_not_found(self):
        room = FakeRoomService(participant())
        room.remove_error = FakeServerError(FakeServerErrorCode.NOT_FOUND, "gone")
        admin, room = self.admin(room)
        self.apply(
            admin,
            command(ModerationAction.REMOVE, value=True),
        )
        self.assertEqual(len(room.removals), 1)

    def test_non_not_found_provider_failures_are_sanitized(self):
        secret = "provider-secret-detail"
        room = FakeRoomService(participant())
        room.remove_error = FakeServerError("internal", secret)
        admin, room = self.admin(room)
        with self.assertRaisesRegex(
            LiveKitClassroomModerationAdminError,
            "^LiveKit participant removal failed$",
        ) as caught:
            self.apply(admin, command(ModerationAction.REMOVE, value=False))
        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertNotIn(secret, rendered)
        self.assertIsNone(caught.exception.__cause__)

    def test_missing_active_participant_fails_stateful_operations(self):
        room = FakeRoomService()
        room.get_error = FakeServerError(FakeServerErrorCode.NOT_FOUND, "missing")
        admin, room = self.admin(room)
        with self.assertRaisesRegex(
            LiveKitClassroomModerationAdminError,
            "participant is unavailable",
        ):
            self.apply(
                admin,
                command(
                    ModerationAction.PUBLISH_PERMISSION,
                    source=MediaSource.MICROPHONE,
                    value=False,
                ),
            )
        with self.assertRaisesRegex(
            LiveKitClassroomModerationAdminError,
            "participant is unavailable",
        ):
            self.apply(
                admin,
                command(
                    ModerationAction.SOFT_MUTE,
                    source=MediaSource.MICROPHONE,
                    value=True,
                ),
            )

    def test_provider_mutation_failures_are_sanitized(self):
        secret = "do-not-leak-provider-detail"
        room = FakeRoomService(participant())
        room.update_error = RuntimeError(secret)
        admin, room = self.admin(room)
        with self.assertRaisesRegex(
            LiveKitClassroomModerationAdminError,
            "^LiveKit publish permission update failed$",
        ) as caught:
            self.apply(
                admin,
                command(
                    ModerationAction.PUBLISH_PERMISSION,
                    source=MediaSource.CAMERA,
                    value=False,
                ),
            )
        self.assertNotIn(secret, "".join(traceback.format_exception(caught.exception)))
        self.assertIsNone(caught.exception.__cause__)

    def test_constructor_rejects_wrong_sdk_or_incomplete_room_service(self):
        with self.assertRaisesRegex(
            LiveKitClassroomModerationAdminError,
            "version is not approved",
        ):
            LiveKitClassroomModerationAdmin(
                room_service=FakeRoomService(participant()),
                api_module=FakeApi,
                sdk_version="wrong",
            )

        with self.assertRaisesRegex(
            LiveKitClassroomModerationAdminError,
            "room service API is unavailable",
        ):
            LiveKitClassroomModerationAdmin(
                room_service=object(),
                api_module=FakeApi,
                sdk_version=LIVEKIT_API_VERSION,
            )

    def test_real_pinned_sdk_preserves_rpc_data_grant_when_installed(self):
        try:
            installed = metadata.version("livekit-api")
        except metadata.PackageNotFoundError:
            self.skipTest("livekit-api is installed by the dedicated provider gate")
        self.assertEqual(installed, LIVEKIT_API_VERSION)

        from livekit import api

        current = SimpleNamespace(
            identity="student-1",
            permission=api.ParticipantPermission(
                can_subscribe=True,
                can_publish=True,
                can_publish_data=True,
                can_publish_sources=[
                    api.TrackSource.MICROPHONE,
                    api.TrackSource.CAMERA,
                ],
            ),
            tracks=[],
        )
        room = FakeRoomService(current)
        admin = LiveKitClassroomModerationAdmin(room_service=room)

        self.apply(
            admin,
            command(
                ModerationAction.PUBLISH_PERMISSION,
                source=MediaSource.CAMERA,
                value=False,
            ),
        )

        request = room.updates[0]
        self.assertEqual(
            list(request.permission.can_publish_sources),
            [api.TrackSource.MICROPHONE],
        )
        self.assertTrue(request.permission.can_publish)
        self.assertTrue(request.permission.can_publish_data)
        self.assertTrue(
            self.matches(
                admin,
                command(
                    ModerationAction.PUBLISH_PERMISSION,
                    source=MediaSource.CAMERA,
                    value=False,
                    operation="op-real-verify-camera",
                ),
            )
        )
        self.assertTrue(
            self.matches(
                admin,
                command(
                    ModerationAction.PUBLISH_PERMISSION,
                    source=MediaSource.MICROPHONE,
                    value=True,
                    operation="op-real-verify-microphone",
                ),
            )
        )
        self.assertEqual(len(room.updates), 1)
        self.assertEqual(room.mutes, [])
        self.assertEqual(room.removals, [])

    def test_repr_does_not_render_room_service_details(self):
        secret = "room-service-secret"
        room = FakeRoomService(participant())
        room.secret = secret
        admin, _ = self.admin(room)
        self.assertNotIn(secret, repr(admin))
        self.assertIn(LIVEKIT_API_VERSION, repr(admin))


if __name__ == "__main__":
    unittest.main()
