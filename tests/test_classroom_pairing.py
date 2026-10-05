from __future__ import annotations

from dataclasses import replace
import json
import unittest

from acs.classroom_domain import (
    ClassroomSnapshot,
    Course,
    Lesson,
    Student,
)
from acs.classroom_pairing import (
    ClassroomPairingError,
    PairingBatch,
    PairingMode,
    assert_pairing_scope,
    override_pairing,
    plan_pairings,
)
from acs.teaching_session import (
    LessonSession,
    PositionSourceKind,
    TeachingActivity,
    TeachingPositionSource,
    TeachingStep,
    default_policy,
)


def _classroom(*, deleted: str | None = None) -> ClassroomSnapshot:
    students = tuple(
        Student(
            student_id=f"s{index}",
            pseudonym=f"Student {index}",
            deleted=f"s{index}" == deleted,
            consent="withdrawn" if f"s{index}" == deleted else "not_collected",
        )
        if f"s{index}" != deleted
        else Student(
            student_id=f"s{index}",
            pseudonym="",
            deleted=True,
            consent="withdrawn",
        )
        for index in range(1, 7)
    )
    return ClassroomSnapshot(
        students=students,
        courses=(Course("course-1", "Course", ("lesson-1",)),),
        lessons=(
            Lesson(
                "lesson-1",
                "course-1",
                "Lesson",
                (),
                "2026-09-26T20:00:00Z",
            ),
        ),
    )


def _lesson(
    student_ids: tuple[str, ...] = ("s1", "s2", "s3", "s4", "s5"),
    *,
    source: TeachingPositionSource | None = None,
) -> LessonSession:
    if source is None:
        source = TeachingPositionSource(PositionSourceKind.START)
    step = TeachingStep(
        "step-1",
        TeachingActivity.TEACHER_EXPLAINS,
        "Explain the position.",
        default_policy(TeachingActivity.TEACHER_EXPLAINS),
    )
    return LessonSession(
        "session-1",
        "lesson-1",
        source,
        (step,),
        student_ids=student_ids,
    )


class ClassroomPairingTests(unittest.TestCase):
    def test_sequential_pairing_is_stable_and_keeps_odd_student_unpaired(self):
        classroom = _classroom()
        lesson = _lesson()
        kwargs = dict(
            batch_id="batch-1",
            game_session_ids=("game-1", "game-2"),
            base_seconds=300,
            increment_seconds=2,
        )
        first = plan_pairings(lesson, classroom, **kwargs)
        retry = plan_pairings(lesson, classroom, **kwargs)

        self.assertEqual(first, retry)
        self.assertEqual(first.digest, retry.digest)
        self.assertEqual(first.mode, PairingMode.SEQUENTIAL)
        self.assertEqual(first.lesson_session_id, lesson.session_id)
        self.assertEqual(first.lesson_session_digest, lesson.digest)
        self.assertEqual(first.start_fen, lesson.source.fen)
        self.assertEqual(first.unpaired_student_ids, ("s5",))
        self.assertEqual(
            tuple(
                (item.white_student_id, item.black_student_id, item.game_session_id)
                for item in first.pairings
            ),
            (("s1", "s2", "game-1"), ("s3", "s4", "game-2")),
        )
        self.assertEqual(
            tuple((item.base_seconds, item.increment_seconds) for item in first.pairings),
            ((300, 2), (300, 2)),
        )
        self.assertEqual(
            tuple(item.pairing_id for item in first.pairings),
            tuple(item.pairing_id for item in retry.pairings),
        )

    def test_random_pairing_is_batch_stable_for_retry_and_preserves_membership(self):
        classroom = _classroom()
        lesson = _lesson(("s1", "s2", "s3", "s4"))

        kwargs = dict(
            batch_id="batch-random",
            game_session_ids=("game-a", "game-b"),
            mode=PairingMode.RANDOM,
        )
        first = plan_pairings(lesson, classroom, **kwargs)
        retry = plan_pairings(lesson, classroom, **kwargs)

        self.assertEqual(first, retry)
        self.assertEqual(first.digest, retry.digest)
        paired = tuple(
            student
            for item in first.pairings
            for student in (item.white_student_id, item.black_student_id)
        )
        self.assertEqual(set(paired), {"s1", "s2", "s3", "s4"})
        self.assertEqual(len(paired), 4)

    def test_selected_subset_must_be_unique_active_lesson_students(self):
        classroom = _classroom()
        lesson = _lesson()

        subset = plan_pairings(
            lesson,
            classroom,
            batch_id="batch-subset",
            student_ids=("s2", "s4"),
            game_session_ids=("game-subset",),
        )
        self.assertEqual(
            (
                subset.pairings[0].white_student_id,
                subset.pairings[0].black_student_id,
            ),
            ("s2", "s4"),
        )

        with self.assertRaisesRegex(ClassroomPairingError, "duplicate"):
            plan_pairings(
                lesson,
                classroom,
                batch_id="batch-duplicate",
                student_ids=("s1", "s1"),
                game_session_ids=("game-x",),
            )
        with self.assertRaisesRegex(ClassroomPairingError, "outside lesson session"):
            plan_pairings(
                lesson,
                classroom,
                batch_id="batch-outsider",
                student_ids=("s1", "s6"),
                game_session_ids=("game-x",),
            )
        with self.assertRaisesRegex(ClassroomPairingError, "at least two students"):
            plan_pairings(
                lesson,
                classroom,
                batch_id="batch-single",
                student_ids=("s1",),
                game_session_ids=(),
            )
        with self.assertRaisesRegex(ClassroomPairingError, "lesson session is outside current classroom scope"):
            plan_pairings(
                lesson,
                _classroom(deleted="s2"),
                batch_id="batch-deleted",
                game_session_ids=("game-1", "game-2"),
            )

    def test_game_session_identity_count_uniqueness_and_time_bounds_fail_closed(self):
        classroom = _classroom()
        lesson = _lesson(("s1", "s2", "s3", "s4"))

        for game_ids, expected in (
            (("game-1",), "match the number of pairs"),
            (("game-1", "game-1"), "must be unique"),
        ):
            with self.subTest(game_ids=game_ids), self.assertRaisesRegex(
                ClassroomPairingError, expected
            ):
                plan_pairings(
                    lesson,
                    classroom,
                    batch_id="batch-game-ids",
                    game_session_ids=game_ids,
                )

        for field, value in (("base_seconds", True), ("increment_seconds", -1)):
            with self.subTest(field=field), self.assertRaises(ClassroomPairingError):
                plan_pairings(
                    lesson,
                    classroom,
                    batch_id="batch-time",
                    game_session_ids=("game-1", "game-2"),
                    **{field: value},
                )

    def test_override_changes_only_colors_and_time_control(self):
        batch = plan_pairings(
            _lesson(("s1", "s2")),
            _classroom(),
            batch_id="batch-override",
            game_session_ids=("game-stable",),
            base_seconds=600,
            increment_seconds=5,
        )
        original = batch.pairings[0]

        updated = override_pairing(
            batch,
            pairing_id=original.pairing_id,
            white_student_id="s2",
            black_student_id="s1",
            base_seconds=900,
            increment_seconds=10,
        )
        changed = updated.pairings[0]
        self.assertEqual(changed.pairing_id, original.pairing_id)
        self.assertEqual(changed.game_session_id, original.game_session_id)
        self.assertEqual((changed.white_student_id, changed.black_student_id), ("s2", "s1"))
        self.assertEqual((changed.base_seconds, changed.increment_seconds), (900, 10))

        with self.assertRaisesRegex(ClassroomPairingError, "cannot change participant membership"):
            override_pairing(
                batch,
                pairing_id=original.pairing_id,
                white_student_id="s1",
                black_student_id="s3",
            )

    def test_canonical_json_round_trip_and_tamper_fail_closed(self):
        batch = plan_pairings(
            _lesson(("s1", "s2", "s3")),
            _classroom(),
            batch_id="batch-json",
            game_session_ids=("game-json",),
        )
        text = batch.to_json()
        restored = PairingBatch.from_json(text)
        self.assertEqual(restored, batch)
        self.assertEqual(restored.to_json(), text)
        self.assertEqual(restored.digest, batch.digest)

        record = json.loads(text)
        record["start_fen"] = "tampered"
        tampered = json.dumps(record, sort_keys=True, separators=(",", ":"))
        with self.assertRaisesRegex(ClassroomPairingError, "digest mismatch"):
            PairingBatch.from_json(tampered)

        duplicate = text[:-1] + ',"digest":"' + batch.digest + '"}'
        with self.assertRaisesRegex(ClassroomPairingError, "duplicate JSON key"):
            PairingBatch.from_json(duplicate)

        record = json.loads(text)
        record["version"] = 2
        body = {key: value for key, value in record.items() if key != "digest"}
        canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        import hashlib
        record["digest"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        future = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.assertRaisesRegex(ClassroomPairingError, "unsupported pairing plan version"):
            PairingBatch.from_json(future)

    def test_reconnect_scope_rejects_changed_plan_or_unavailable_student(self):
        classroom = _classroom()
        lesson = _lesson(("s1", "s2"))
        batch = plan_pairings(
            lesson,
            classroom,
            batch_id="batch-reconnect",
            game_session_ids=("game-reconnect",),
        )
        assert_pairing_scope(batch, lesson, classroom)

        changed_lesson = _lesson(("s1", "s2", "s3"))
        with self.assertRaisesRegex(ClassroomPairingError, "does not match"):
            assert_pairing_scope(batch, changed_lesson, classroom)

        with self.assertRaisesRegex(
            ClassroomPairingError,
            "lesson session is outside current classroom scope",
        ):
            assert_pairing_scope(batch, lesson, _classroom(deleted="s2"))

    def test_deserialized_batch_cannot_add_participants_outside_lesson_scope(self):
        lesson = _lesson(("s1", "s2"))
        classroom = _classroom()
        batch = plan_pairings(
            lesson,
            classroom,
            batch_id="batch-forged",
            game_session_ids=("game-forged",),
        )
        original = batch.pairings[0]
        forged_pairing = replace(original, black_student_id="s6")
        forged = replace(batch, pairings=(forged_pairing,))
        with self.assertRaisesRegex(ClassroomPairingError, "unavailable lesson student"):
            assert_pairing_scope(forged, lesson, classroom)


if __name__ == "__main__":
    unittest.main()
