from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace
import traceback
import unittest

from acs.classroom_realtime_media import MediaSource, ModerationAction, ModerationCommand
from acs.livekit_moderation_provider import (
    LIVEKIT_API_VERSION,
    LiveKitModerationProviderAdmin,
    LiveKitModerationProviderError,
)


ROOM = "room-1"
TARGET = "student-1"


class FakeServerError(Exception):
    def __init__(self, code, message="provider-private-detail"):
        super().__init__(message)
        self.code = code


class FakeServerErrorCode:
    NOT_FOUND = "not_found"


class FakePermission:
    def __init__(
        self,
        *,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
        can_publish_sources=(),
        hidden=False,
        recorder=False,
        can_update_metadata=True,
        can_subscribe_metrics=True,
        can_manage_agent_session=False,
    ):
        self.can_publish = can_publish
        self.can_subscribe = can_subscribe
        self.can_publish_data = can_publish_data
        self.can_publish_sources = list(can_publish_sources)
        self.hidden = hidden
        self.recorder = recorder
        self.can_update_metadata = can_update_metadata
        self.can_subscribe_metrics = can_subscribe_metrics
        self.can_manage_agent_session = can_manage_agent_session

    def CopyFrom(self, other):
        self.__dict__.clear()
        self.__dict__.update(deepcopy(other.__dict__))


class Message:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeApi:
    ServerError = FakeServerError
    ServerErrorCode = FakeServerErrorCode
    ParticipantPermission = FakePermission
    RoomParticipantIdentity = Message
    UpdateParticipantRequest = Message
    MuteRoomTrackRequest = Message


def participant(
    *,
    identity=TARGET,
    permission=None,
    tracks=None,
):
    return Message(
        identity=identity,
        permission=permission or FakePermission(),
        tracks=[] if tracks is None else tracks,
    )


def track(sid, *, source=2, muted=False):
    return Message(sid=sid, source=source, muted=muted)


class FakeRoomService:
    def __init__(self, current=None):
        self.current = current or participant()
        self.get_calls = []
        self.update_calls = []
        self.mute_calls = []
        self.remove_calls = []
        self.get_error = None
        self.update_error = None
        self.mute_error = None
        self.remove_error = None

    async def get_participant(self, request):
        self.get_calls.append(request)
        if self.get_error is not None:
            raise self.get_error
        return self.current

    async def update_participant(self, request):
        self.update_calls.append(request)
        if self.update_error is not None:
            raise self.update_error
        self.current = participant(
            identity=request.identity,
            permission=request.permission,
            tracks=self.current.tracks,
        )
        return self.current

    async def mute_published_track(self, request):
        self.mute_calls.append(request)
        if self.mute_error is not None:
            raise self.mute_error
        for value in self.current.tracks:
            if value.sid == request.track_sid:
                value.muted = request.muted
                return Message(track=value)
        raise AssertionError("unknown track")

    async def remove_participant(self, request):
        self.remove_calls.append(request)
        if self.remove_error is not None:
            raise self.remove_error
        self.current = None
        return Message()


def command(
    action,
    *,
    source=None,
    value=False,
    operation_id="op-1",
):
    return ModerationCommand(
        operation_id=operation_id,
        actor_id="teacher-1",
        target_id=TARGET,
        action=action,
        source=source,
        value=value,
    )


class LiveKitModerationProviderAdminTests(unittest.TestCase):
    def make(self, current=None):
        service = FakeRoomService(current)
        adapter = LiveKitModerationProviderAdmin(
            room_service=service,
            api_module=FakeApi,
            sdk_version=LIVEKIT_API_VERSION,
        )
        return adapter, service

    def apply(self, adapter, value):
        asyncio.run(adapter.apply_moderation_command(room_id=ROOM, command=value))

    def test_revoking_one_source_from_implicit_all_materializes_other_sources(self):
        permission = FakePermission(
            can_publish=True,
            can_publish_sources=(),
            can_subscribe=False,
            can_publish_data=True,
            hidden=True,
            recorder=True,
            can_update_metadata=False,
            can_subscribe_metrics=False,
            can_manage_agent_session=True,
        )
        adapter, service = self.make(participant(permission=permission))

        self.apply(
            adapter,
            command(
                ModerationAction.PUBLISH_PERMISSION,
                source=MediaSource.MICROPHONE,
                value=False,
            ),
        )

        self.assertEqual(len(service.update_calls), 1)
        replacement = service.update_calls[0].permission
        self.assertTrue(replacement.can_publish)
        self.assertEqual(replacement.can_publish_sources, [1, 3, 4])
        self.assertFalse(replacement.can_subscribe)
        self.assertTrue(replacement.can_publish_data)
        self.assertTrue(replacement.hidden)
        self.assertTrue(replacement.recorder)
        self.assertFalse(replacement.can_update_metadata)
        self.assertFalse(replacement.can_subscribe_metrics)
        self.assertTrue(replacement.can_manage_agent_session)

    def test_explicit_publish_source_updates_only_requested_source(self):
        permission = FakePermission(
            can_publish=True,
            can_publish_sources=(1, 3),
        )
        adapter, service = self.make(participant(permission=permission))

        self.apply(
            adapter,
            command(
                ModerationAction.PUBLISH_PERMISSION,
                source=MediaSource.MICROPHONE,
                value=True,
            ),
        )
        self.assertEqual(service.update_calls[0].permission.can_publish_sources, [1, 2, 3])

        service.update_calls.clear()
        self.apply(
            adapter,
            command(
                ModerationAction.PUBLISH_PERMISSION,
                source=MediaSource.CAMERA,
                value=False,
                operation_id="op-2",
            ),
        )
        self.assertEqual(service.update_calls[0].permission.can_publish_sources, [2, 3])

    def test_last_source_revocation_disables_publish_and_enable_from_none_is_scoped(self):
        adapter, service = self.make(
            participant(permission=FakePermission(can_publish=True, can_publish_sources=(2,)))
        )
        self.apply(
            adapter,
            command(
                ModerationAction.PUBLISH_PERMISSION,
                source=MediaSource.MICROPHONE,
                value=False,
            ),
        )
        replacement = service.update_calls[-1].permission
        self.assertFalse(replacement.can_publish)
        self.assertEqual(replacement.can_publish_sources, [])

        adapter, service = self.make(
            participant(permission=FakePermission(can_publish=False, can_publish_sources=()))
        )
        self.apply(
            adapter,
            command(
                ModerationAction.PUBLISH_PERMISSION,
                source=MediaSource.CAMERA,
                value=True,
            ),
        )
        replacement = service.update_calls[-1].permission
        self.assertTrue(replacement.can_publish)
        self.assertEqual(replacement.can_publish_sources, [1])

    def test_publish_noop_does_not_rotate_provider_permission_or_token(self):
        adapter, service = self.make(
            participant(permission=FakePermission(can_publish=True, can_publish_sources=(2,)))
        )
        self.apply(
            adapter,
            command(
                ModerationAction.PUBLISH_PERMISSION,
                source=MediaSource.MICROPHONE,
                value=True,
            ),
        )
        self.assertEqual(service.update_calls, [])

    def test_permission_update_must_return_exact_target_and_requested_state(self):
        adapter, service = self.make(
            participant(permission=FakePermission(can_publish=True, can_publish_sources=(2,)))
        )

        async def wrong_identity(request):
            service.update_calls.append(request)
            return participant(
                identity="student-2",
                permission=request.permission,
            )
        service.update_participant = wrong_identity

        with self.assertRaisesRegex(
            LiveKitModerationProviderError,
            "identity does not match",
        ):
            self.apply(
                adapter,
                command(
                    ModerationAction.PUBLISH_PERMISSION,
                    source=MediaSource.MICROPHONE,
                    value=False,
                ),
            )

    def test_soft_mute_changes_only_microphone_tracks_that_need_it(self):
        current = participant(
            tracks=[
                track("mic-active", source=2, muted=False),
                track("mic-already", source=2, muted=True),
                track("camera", source=1, muted=False),
                track("screen-audio", source=4, muted=False),
            ]
        )
        adapter, service = self.make(current)

        self.apply(
            adapter,
            command(
                ModerationAction.SOFT_MUTE,
                source=MediaSource.MICROPHONE,
                value=True,
            ),
        )

        self.assertEqual(
            [(item.track_sid, item.muted) for item in service.mute_calls],
            [("mic-active", True)],
        )

    def test_soft_unmute_is_exact_state_assignment(self):
        current = participant(tracks=[track("mic-1", source=2, muted=True)])
        adapter, service = self.make(current)
        self.apply(
            adapter,
            command(
                ModerationAction.SOFT_MUTE,
                source=MediaSource.MICROPHONE,
                value=False,
            ),
        )
        self.assertEqual(
            [(item.track_sid, item.muted) for item in service.mute_calls],
            [("mic-1", False)],
        )

    def test_absent_participant_is_already_achieved_current_session_state(self):
        for action, source, value in (
            (ModerationAction.PUBLISH_PERMISSION, MediaSource.CAMERA, False),
            (ModerationAction.SOFT_MUTE, MediaSource.MICROPHONE, True),
        ):
            with self.subTest(action=action):
                adapter, service = self.make()
                service.get_error = FakeServerError("not_found")
                self.apply(adapter, command(action, source=source, value=value))
                self.assertEqual(service.update_calls, [])
                self.assertEqual(service.mute_calls, [])

    def test_remove_is_idempotent_for_structured_not_found_only(self):
        adapter, service = self.make()
        service.remove_error = FakeServerError("not_found")
        self.apply(
            adapter,
            command(ModerationAction.REMOVE, source=None, value=True),
        )
        self.assertEqual(len(service.remove_calls), 1)

        adapter, service = self.make()
        service.remove_error = FakeServerError("unavailable", "provider-secret")
        with self.assertRaisesRegex(
            LiveKitModerationProviderError,
            "^LiveKit moderation provider operation failed$",
        ) as caught:
            self.apply(
                adapter,
                command(ModerationAction.REMOVE, source=None, value=False),
            )
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn(
            "provider-secret",
            "".join(traceback.format_exception(caught.exception)),
        )

    def test_remove_does_not_invent_persistent_block_authority(self):
        adapter, service = self.make()
        self.apply(
            adapter,
            command(ModerationAction.REMOVE, source=None, value=True),
        )
        request = service.remove_calls[0]
        self.assertEqual(request.room, ROOM)
        self.assertEqual(request.identity, TARGET)
        self.assertEqual(set(request.__dict__), {"room", "identity"})

    def test_provider_errors_are_sanitized(self):
        adapter, service = self.make()
        service.get_error = RuntimeError("private-livekit-endpoint-and-secret")
        with self.assertRaisesRegex(
            LiveKitModerationProviderError,
            "^LiveKit moderation provider operation failed$",
        ) as caught:
            self.apply(
                adapter,
                command(
                    ModerationAction.PUBLISH_PERMISSION,
                    source=MediaSource.CAMERA,
                    value=False,
                ),
            )
        self.assertIsNone(caught.exception.__cause__)
        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertNotIn("private-livekit-endpoint-and-secret", rendered)

    def test_invalid_provider_state_fails_closed_before_update(self):
        bad_states = (
            FakePermission(can_publish=True, can_publish_sources=(2, 2)),
            FakePermission(can_publish=True, can_publish_sources=(9,)),
        )
        for permission in bad_states:
            with self.subTest(sources=permission.can_publish_sources):
                adapter, service = self.make(participant(permission=permission))
                with self.assertRaises(LiveKitModerationProviderError):
                    self.apply(
                        adapter,
                        command(
                            ModerationAction.PUBLISH_PERMISSION,
                            source=MediaSource.CAMERA,
                            value=False,
                        ),
                    )
                self.assertEqual(service.update_calls, [])

    def test_noncanonical_command_and_sdk_drift_fail_closed(self):
        adapter, _service = self.make()
        with self.assertRaisesRegex(
            LiveKitModerationProviderError,
            "command is not canonical",
        ):
            asyncio.run(
                adapter.apply_moderation_command(room_id=ROOM, command=object())
            )

        with self.assertRaisesRegex(
            LiveKitModerationProviderError,
            "version is not approved",
        ):
            LiveKitModerationProviderAdmin(
                room_service=FakeRoomService(),
                api_module=FakeApi,
                sdk_version="9.9.9",
            )

    def test_repr_contains_no_room_service_material(self):
        adapter, _service = self.make()
        rendered = repr(adapter)
        self.assertIn("room_service=<redacted>", rendered)
        self.assertIn("1.2.1", rendered)


if __name__ == "__main__":
    unittest.main()
