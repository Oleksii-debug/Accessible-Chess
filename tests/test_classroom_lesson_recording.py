from __future__ import annotations

import unittest

from acs.classroom_lesson_recording import (
    LessonRecordingError,
    LessonRecordingLedger,
    ParticipantConsent,
    RecordingPolicy,
    RecordingState,
    policy_digest,
)


class Provider:
    def __init__(self):
        self.calls = []

    def start(self, *, room_id, lesson_id, policy):
        self.calls.append(("start", room_id, lesson_id))
        return "provider-recording-1"

    def stop(self, *, provider_ref):
        self.calls.append(("stop", provider_ref))

    def delete(self, *, provider_ref):
        self.calls.append(("delete", provider_ref))


class LessonRecordingTests(unittest.TestCase):
    def policy(self):
        return RecordingPolicy(
            storage_region="eu",
            retention_days=30,
            allow_audio=True,
            allow_video=True,
            allow_chat_transcript=False,
        )

    def consents(self, policy, *, second_granted=True):
        digest = policy_digest(policy)
        return (
            ParticipantConsent("teacher", digest, True, "2026-10-07T18:00:00Z"),
            ParticipantConsent("student", digest, second_granted, "2026-10-07T18:00:01Z"),
        )

    def test_exact_consent_required_before_provider_start(self):
        policy = self.policy()
        provider = Provider()
        ledger = LessonRecordingLedger()
        with self.assertRaisesRegex(LessonRecordingError, "explicit consent"):
            ledger.start(
                recording_id="r1",
                room_id="room1",
                lesson_id="lesson1",
                policy=policy,
                participant_ids=("teacher", "student"),
                consents=self.consents(policy, second_granted=False),
                provider=provider,
                started_at="2026-10-07T18:01:00Z",
            )
        self.assertEqual(provider.calls, [])

    def test_policy_change_invalidates_old_consent(self):
        old = RecordingPolicy("eu", 30, True, False, False)
        new = RecordingPolicy("eu", 7, True, False, False)
        provider = Provider()
        with self.assertRaisesRegex(LessonRecordingError, "explicit consent"):
            LessonRecordingLedger().start(
                recording_id="r1", room_id="room1", lesson_id="lesson1",
                policy=new, participant_ids=("teacher", "student"),
                consents=self.consents(old), provider=provider,
                started_at="2026-10-07T18:01:00Z",
            )
        self.assertEqual(provider.calls, [])

    def test_start_stop_delete_is_idempotent_and_history_is_durable(self):
        policy = self.policy()
        provider = Provider()
        ledger = LessonRecordingLedger()
        record = ledger.start(
            recording_id="r1", room_id="room1", lesson_id="lesson1",
            policy=policy, participant_ids=("teacher", "student"),
            consents=self.consents(policy), provider=provider,
            started_at="2026-10-07T18:01:00+00:00",
        )
        self.assertEqual(record.state, RecordingState.RECORDING)
        stopped = ledger.stop("r1", provider=provider, stopped_at="2026-10-07T18:20:00Z")
        self.assertEqual(stopped.state, RecordingState.STOPPED)
        self.assertEqual(ledger.stop("r1", provider=provider, stopped_at="2026-10-07T18:21:00Z"), stopped)
        deleted = ledger.delete("r1", provider=provider, deleted_at="2026-10-07T18:22:00Z")
        self.assertEqual(deleted.state, RecordingState.DELETED)
        self.assertEqual(ledger.delete("r1", provider=provider, deleted_at="2026-10-07T18:23:00Z"), deleted)
        self.assertEqual(provider.calls, [
            ("start", "room1", "lesson1"),
            ("stop", "provider-recording-1"),
            ("delete", "provider-recording-1"),
        ])
        text = ledger.to_json()
        self.assertIn('"retention_days":30', text)
        self.assertIn('"state":"deleted"', text)
        self.assertNotIn("api_key", text.lower())
        self.assertNotIn("secret", text.lower())

    def test_policy_requires_explicit_storage_and_data_class(self):
        with self.assertRaises(LessonRecordingError):
            RecordingPolicy("eu", 30, False, False, False)
        with self.assertRaises(LessonRecordingError):
            RecordingPolicy("bad region", 30, True, False, False)


if __name__ == "__main__":
    unittest.main()
