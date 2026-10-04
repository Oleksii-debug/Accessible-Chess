from __future__ import annotations

import json
import unittest

from acs.book_index import BookEntryKind, BookIndex
from acs.book_training import (
    BookTrainingError,
    BookTrainingErrorCode,
    build_book_training_material,
    resolve_book_training_origin,
    restore_book_training_material,
)
from acs.bookdocument import BookDocument, Exercise, Paragraph
from acs.chesscore import Board, Move, sq_name
from acs.starter_books_training_release import (
    build_release_starter_course,
    build_training_task_catalogue,
)
from acs.training import ExerciseSession


EXPECTED_TRAINING_TASKS = 144
EXPECTED_OPENING_LINES = 16
EXPECTED_PLIES_PER_LINE = 9
EXPECTED_AUTHORED_UCI_LINES = (
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6", "d2d3", "f8c5", "c2c3"),
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5a4", "g8f6", "e1g1"),
    ("e2e4", "e7e5", "g1f3", "b8c6", "d2d4", "e5d4", "f3d4", "g8f6", "b1c3"),
    ("e2e4", "e7e5", "b1c3", "g8f6", "f2f4", "d7d5", "f4e5", "f6e4", "g1f3"),
    ("e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3"),
    ("e2e4", "e7e6", "d2d4", "d7d5", "b1c3", "g8f6", "e4e5", "f6d7", "f2f4"),
    ("e2e4", "c7c6", "d2d4", "d7d5", "b1c3", "d5e4", "c3e4", "c8f5", "e4g3"),
    ("e2e4", "d7d5", "e4d5", "d8d5", "b1c3", "d5d8", "d2d4", "g8f6", "g1f3"),
    ("d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "g8f6", "c1g5", "f8e7", "e2e3"),
    ("d2d4", "d7d5", "c2c4", "c7c6", "g1f3", "g8f6", "b1c3", "d5c4", "a2a4"),
    ("d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "f8g7", "e2e4", "d7d6", "g1f3"),
    ("d2d4", "g8f6", "c2c4", "e7e6", "b1c3", "f8b4", "e2e3", "e8g8", "f1d3"),
    ("c2c4", "e7e5", "b1c3", "g8f6", "g2g3", "d7d5", "c4d5", "f6d5", "f1g2"),
    ("g1f3", "d7d5", "c2c4", "e7e6", "g2g3", "g8f6", "f1g2", "f8e7", "e1g1"),
    ("d2d4", "d7d5", "g1f3", "g8f6", "c1f4", "e7e6", "e2e3", "f8e7", "f1d3"),
    ("d2d4", "f7f5", "g2g3", "g8f6", "f1g2", "g7g6", "g1f3", "f8g7", "e1g1"),
)

EXPECTED_AUTHORED_LABELS = (
    ("Italian Game", "Швидкий розвиток", "Розвинути коня і слона та контролювати центр."),
    ("Ruy Lopez", "Тиск на центр", "Зрозуміти тиск слона на захисника пішака e5."),
    ("Scotch Game", "Відкритий центр", "Побачити раннє розкриття центру ходом d4."),
    ("Vienna Game", "Активний центр", "Порівняти розвиток коня c3 з типовим Nf3."),
    ("Sicilian Defense", "Асиметричний центр", "Розпізнавати структуру після c5 і центрального обміну."),
    ("French Defense", "Пішаковий ланцюг", "Вивчити напруження e4-d5 та розвиток фігур."),
    ("Caro-Kann Defense", "Надійний центр", "Побачити підготовлений удар d5 і центральний обмін."),
    ("Scandinavian Defense", "Темп проти ферзя", "Оцінити ранній вихід ферзя та розвиток з темпом."),
    ("Queen's Gambit", "Тиск на d5", "Зрозуміти ідею c4 проти центрального пішака d5."),
    ("Slav Defense", "Міцний ферзевий центр", "Порівняти підтримку d5 пішаком c6."),
    ("King's Indian Defense", "Фіанкетто", "Розпізнавати фіанкетто чорного слона і боротьбу за центр."),
    ("Nimzo-Indian Defense", "Зв'язка коня", "Побачити тиск Bb4 на коня c3 і центр білих."),
    ("English Opening", "Фланговий контроль", "Контролювати d5 через c4 без раннього e4 або d4."),
    ("Reti Opening", "Гнучкий розвиток", "Розвивати королівський фланг із відкладеним центром."),
    ("London System", "Стабільна схема розвитку", "Відпрацювати ранній Bf4 у ферзевому дебюті."),
    ("Dutch Defense", "Контроль e4", "Побачити ідею f5 та фіанкетто у закритому центрі."),
)


def _uci(move: Move) -> str:
    """Project a canonical-core Move to the release catalogue's UCI form."""

    promotion = "" if move.promotion is None else move.promotion.lower()
    return f"{sq_name(move.frm)}{sq_name(move.to)}{promotion}"


class StarterTrainingCanonicalLegalityTests(unittest.TestCase):
    def test_every_published_fen_and_answer_round_trips_through_canonical_core(self) -> None:
        tasks = build_training_task_catalogue()
        self.assertEqual(EXPECTED_TRAINING_TASKS, len(tasks))

        for task in tasks:
            with self.subTest(task_id=task.task_id, opening=task.opening, ply=task.ply):
                # Rehydrate the published position independently instead of trusting
                # the mutable Board instance used while the catalogue was built.
                board = Board(task.fen)
                self.assertEqual(task.fen, board.fen())

                # Chess legality stays owned by acs.chesscore.  This regression gate
                # only serializes canonical legal moves to the release UCI contract;
                # it does not implement a second move/rules engine in test code.
                legal_answers = {_uci(move) for move in board.legal_moves()}
                self.assertIn(
                    task.answer_uci,
                    legal_answers,
                    msg=(
                        f"starter task {task.task_id} publishes non-legal answer "
                        f"{task.answer_uci!r} for FEN {task.fen!r}"
                    ),
                )

    def test_catalogue_matches_reviewed_authored_uci_lines_exactly(self) -> None:
        tasks = build_training_task_catalogue()
        self.assertEqual(EXPECTED_OPENING_LINES, len(EXPECTED_AUTHORED_UCI_LINES))
        self.assertEqual(EXPECTED_TRAINING_TASKS, len(tasks))

        for opening_index, expected_line in enumerate(
            EXPECTED_AUTHORED_UCI_LINES,
            start=1,
        ):
            start = (opening_index - 1) * EXPECTED_PLIES_PER_LINE
            line = tasks[start : start + EXPECTED_PLIES_PER_LINE]
            with self.subTest(opening_index=opening_index, opening=line[0].opening):
                self.assertEqual(EXPECTED_PLIES_PER_LINE, len(expected_line))
                self.assertEqual(
                    expected_line,
                    tuple(task.answer_uci for task in line),
                )

    def test_catalogue_matches_reviewed_authored_labels_exactly(self) -> None:
        tasks = build_training_task_catalogue()
        self.assertEqual(EXPECTED_OPENING_LINES, len(EXPECTED_AUTHORED_LABELS))

        for opening_index, expected_labels in enumerate(
            EXPECTED_AUTHORED_LABELS,
            start=1,
        ):
            start = (opening_index - 1) * EXPECTED_PLIES_PER_LINE
            line = tasks[start : start + EXPECTED_PLIES_PER_LINE]
            with self.subTest(opening_index=opening_index):
                actual = (
                    line[0].opening,
                    line[0].theme_uk,
                    line[0].learning_goal_uk,
                )
                self.assertEqual(expected_labels, actual)

    def test_catalogue_preserves_exact_canonical_opening_chains(self) -> None:
        tasks = build_training_task_catalogue()
        self.assertEqual(
            EXPECTED_TRAINING_TASKS,
            EXPECTED_OPENING_LINES * EXPECTED_PLIES_PER_LINE,
        )
        self.assertEqual(EXPECTED_TRAINING_TASKS, len(tasks))

        for opening_index in range(1, EXPECTED_OPENING_LINES + 1):
            start = (opening_index - 1) * EXPECTED_PLIES_PER_LINE
            line = tasks[start : start + EXPECTED_PLIES_PER_LINE]
            self.assertEqual(EXPECTED_PLIES_PER_LINE, len(line))
            opening = line[0].opening
            theme = line[0].theme_uk
            learning_goal = line[0].learning_goal_uk
            board = Board()

            for ply, task in enumerate(line, start=1):
                with self.subTest(
                    opening_index=opening_index,
                    task_id=task.task_id,
                    ply=ply,
                ):
                    self.assertEqual(
                        f"opening-{opening_index:02d}-ply-{ply:02d}",
                        task.task_id,
                    )
                    self.assertEqual(ply, task.ply)
                    self.assertEqual(opening, task.opening)
                    self.assertEqual(theme, task.theme_uk)
                    self.assertEqual(learning_goal, task.learning_goal_uk)
                    # This is the cross-task continuity proof missing from the
                    # per-position legality test: each published task must begin
                    # at exactly the canonical position reached by accepting the
                    # preceding published answer in this same authored line.
                    self.assertEqual(board.fen(), task.fen)
                    board.push(board.parse_move(task.answer_uci))

    def test_shipped_course_exercises_enter_and_complete_canonical_training(self) -> None:
        tasks = build_training_task_catalogue()
        course = build_release_starter_course()
        exercise_entries = BookIndex(course).of_kind(BookEntryKind.EXERCISE)
        self.assertEqual(EXPECTED_TRAINING_TASKS, len(exercise_entries))
        self.assertEqual(len(tasks), len(exercise_entries))

        seen_block_ids: set[str] = set()
        seen_source_anchors: set[str] = set()
        seen_target_keys: set[str] = set()
        for task, entry in zip(tasks, exercise_entries, strict=True):
            with self.subTest(task_id=task.task_id, target=entry.target.key):
                expected_block_id = f"starter-release-{task.task_id}"
                expected_source_anchor = f"starter-release:training:{task.task_id}"
                self.assertEqual(expected_block_id, entry.target.block_id)
                self.assertEqual(expected_source_anchor, entry.target.source_anchor)
                self.assertNotIn(entry.target.block_id, seen_block_ids)
                self.assertNotIn(entry.target.source_anchor, seen_source_anchors)
                self.assertNotIn(entry.target.key, seen_target_keys)
                seen_block_ids.add(entry.target.block_id)
                seen_source_anchors.add(entry.target.source_anchor)
                seen_target_keys.add(entry.target.key)

                material = build_book_training_material(course, entry.target.key)
                self.assertEqual(entry.target.key, material.origin.target_key)
                self.assertEqual(expected_block_id, material.origin.block_id)
                self.assertEqual(expected_source_anchor, material.origin.source_anchor)
                self.assertEqual(task.fen, material.definition.start_fen)
                self.assertEqual(1, len(material.definition.steps))

                expected = Board(task.fen)
                expected_san = expected.push(expected.parse_move(task.answer_uci))
                self.assertEqual(
                    frozenset({expected_san}),
                    material.definition.steps[0].accepted_moves,
                )

                session = ExerciseSession(material.definition)
                result = session.submit(task.answer_uci)
                self.assertTrue(
                    result.accepted,
                    msg=f"shipped starter exercise rejected {task.answer_uci!r}",
                )
                self.assertTrue(result.completed)
                self.assertTrue(session.completed)
                self.assertEqual((expected_san,), session.accepted_path)
                self.assertEqual(expected.fen(), session.current_fen)


    def test_every_release_exercise_rejects_every_alternative_legal_move_without_advancing(self) -> None:
        tasks = build_training_task_catalogue()
        course = build_release_starter_course()
        exercise_entries = BookIndex(course).of_kind(BookEntryKind.EXERCISE)
        self.assertEqual(len(tasks), len(exercise_entries))

        for task, entry in zip(tasks, exercise_entries, strict=True):
            with self.subTest(task_id=task.task_id, target=entry.target.key):
                board = Board(task.fen)
                legal_uci = tuple(_uci(move) for move in board.legal_moves())
                alternatives = tuple(
                    candidate
                    for candidate in legal_uci
                    if candidate != task.answer_uci
                )
                self.assertTrue(
                    alternatives,
                    msg=f"starter task {task.task_id} has no negative legal-move control",
                )

                material = build_book_training_material(course, entry.target.key)
                session = ExerciseSession(material.definition)

                # Exhaust the canonical legal move set, not merely one sampled
                # negative. Every other legal move must remain a mistake and
                # must leave the semantic training position/path untouched.
                for attempt_number, alternative in enumerate(alternatives, start=1):
                    rejected = session.submit(alternative)
                    self.assertFalse(
                        rejected.accepted,
                        msg=(
                            f"starter task {task.task_id} accepted alternative legal move "
                            f"{alternative!r}"
                        ),
                    )
                    self.assertFalse(rejected.completed)
                    self.assertFalse(session.completed)
                    self.assertEqual(0, session.step_index)
                    self.assertEqual((), session.accepted_path)
                    self.assertEqual(task.fen, session.current_fen)
                    self.assertEqual(attempt_number, session.attempts)
                    self.assertEqual(attempt_number, session.mistakes)

                expected = Board(task.fen)
                expected.push(expected.parse_move(task.answer_uci))
                accepted = session.submit(task.answer_uci)
                self.assertTrue(accepted.accepted)
                self.assertTrue(accepted.completed)
                self.assertTrue(session.completed)
                self.assertEqual(1, session.step_index)
                self.assertEqual(len(alternatives) + 1, session.attempts)
                self.assertEqual(len(alternatives), session.mistakes)
                self.assertEqual(expected.fen(), session.current_fen)
                self.assertEqual(1, len(session.accepted_path))

    def test_release_exercises_preserve_authored_identity_and_durable_origin(self) -> None:
        tasks = build_training_task_catalogue()
        course = build_release_starter_course()
        exercise_entries = BookIndex(course).of_kind(BookEntryKind.EXERCISE)
        self.assertEqual(len(tasks), len(exercise_entries))

        exercise_ids: set[str] = set()
        source_ids: set[str] = set()
        for task, entry in zip(tasks, exercise_entries, strict=True):
            with self.subTest(task_id=task.task_id, target=entry.target.key):
                block = course.blocks[entry.target.index]
                self.assertIsInstance(block, Exercise)
                assert isinstance(block, Exercise)

                expected_prompt = (
                    f"{task.opening}. {task.theme_uk} "
                    f"Крок {task.ply}: знайдіть тематичний хід. "
                    f"Навчальна мета: {task.learning_goal_uk}"
                )
                self.assertEqual(task.fen, block.fen)
                self.assertEqual(task.answer_uci, block.answer_text)
                self.assertEqual(expected_prompt, block.prompt)
                self.assertEqual("starter", block.difficulty)
                self.assertIsNone(block.solution_pgn)

                material = build_book_training_material(course, entry.target.key)
                self.assertEqual(block.prompt, material.definition.title)
                self.assertEqual("starter", material.definition.metadata["difficulty"])
                self.assertEqual(
                    "book_exercise",
                    material.definition.metadata["content_kind"],
                )
                self.assertIsNotNone(material.definition.source_id)
                self.assertNotIn(material.definition.exercise_id, exercise_ids)
                exercise_ids.add(material.definition.exercise_id)
                assert material.definition.source_id is not None
                self.assertNotIn(material.definition.source_id, source_ids)
                source_ids.add(material.definition.source_id)

                # The durable payload must resolve back through the semantic
                # BookIndex identity, not merely through the historical index.
                payload = material.as_dict()
                restored = restore_book_training_material(course, payload)
                self.assertEqual(payload, restored.as_dict())
                location = resolve_book_training_origin(course, restored.origin)
                self.assertEqual(entry.target.index, location.index)
                self.assertEqual("Exercise", location.kind)

        self.assertEqual(EXPECTED_TRAINING_TASKS, len(exercise_ids))
        self.assertEqual(EXPECTED_TRAINING_TASKS, len(source_ids))


    def test_release_training_identity_is_stable_across_fresh_builds(self) -> None:
        first_tasks = build_training_task_catalogue()
        second_tasks = build_training_task_catalogue()
        self.assertEqual(first_tasks, second_tasks)

        first_course = build_release_starter_course()
        second_course = build_release_starter_course()
        first_entries = BookIndex(first_course).of_kind(BookEntryKind.EXERCISE)
        second_entries = BookIndex(second_course).of_kind(BookEntryKind.EXERCISE)
        self.assertEqual(EXPECTED_TRAINING_TASKS, len(first_entries))
        self.assertEqual(len(first_entries), len(second_entries))

        for first_entry, second_entry in zip(first_entries, second_entries, strict=True):
            with self.subTest(target=first_entry.target.key):
                self.assertEqual(first_entry.target.key, second_entry.target.key)
                self.assertEqual(first_entry.target.block_id, second_entry.target.block_id)
                self.assertEqual(
                    first_entry.target.source_anchor,
                    second_entry.target.source_anchor,
                )

                first_material = build_book_training_material(
                    first_course,
                    first_entry.target.key,
                )
                second_material = build_book_training_material(
                    second_course,
                    second_entry.target.key,
                )
                self.assertEqual(first_material.as_dict(), second_material.as_dict())

                restored = restore_book_training_material(
                    second_course,
                    first_material.as_dict(),
                )
                self.assertEqual(first_material.as_dict(), restored.as_dict())
                resolved = resolve_book_training_origin(
                    second_course,
                    first_material.origin,
                )
                self.assertEqual(second_entry.target.index, resolved.index)
                self.assertEqual("Exercise", resolved.kind)

    def test_release_training_identity_survives_bookdocument_wire_round_trip(self) -> None:
        tasks = build_training_task_catalogue()
        original = build_release_starter_course()
        persisted = json.loads(json.dumps(original.as_dict(), ensure_ascii=False))
        reopened = BookDocument.from_dict(persisted)
        self.assertEqual(persisted, reopened.as_dict())

        original_entries = BookIndex(original).of_kind(BookEntryKind.EXERCISE)
        reopened_entries = BookIndex(reopened).of_kind(BookEntryKind.EXERCISE)
        self.assertEqual(EXPECTED_TRAINING_TASKS, len(original_entries))
        self.assertEqual(len(original_entries), len(reopened_entries))
        self.assertEqual(len(tasks), len(reopened_entries))

        for task, original_entry, reopened_entry in zip(
            tasks,
            original_entries,
            reopened_entries,
            strict=True,
        ):
            with self.subTest(task_id=task.task_id, target=original_entry.target.key):
                self.assertEqual(original_entry.target.key, reopened_entry.target.key)
                self.assertEqual(original_entry.target.block_id, reopened_entry.target.block_id)
                self.assertEqual(
                    original_entry.target.source_anchor,
                    reopened_entry.target.source_anchor,
                )

                original_material = build_book_training_material(
                    original,
                    original_entry.target.key,
                )
                reopened_material = build_book_training_material(
                    reopened,
                    reopened_entry.target.key,
                )
                self.assertEqual(
                    original_material.as_dict(),
                    reopened_material.as_dict(),
                )

                material_payload = json.loads(
                    json.dumps(original_material.as_dict(), ensure_ascii=False)
                )
                restored_material = restore_book_training_material(
                    reopened,
                    material_payload,
                )
                self.assertEqual(
                    original_material.as_dict(),
                    restored_material.as_dict(),
                )
                resolved = resolve_book_training_origin(
                    reopened,
                    original_material.origin,
                )
                self.assertEqual(reopened_entry.target.index, resolved.index)
                self.assertEqual("Exercise", resolved.kind)

                session = ExerciseSession(original_material.definition)
                result = session.submit(task.answer_uci)
                self.assertTrue(result.accepted)
                self.assertTrue(result.completed)
                snapshot = json.loads(
                    json.dumps(session.snapshot(), ensure_ascii=False)
                )

                resumed = ExerciseSession.restore(
                    restored_material.definition,
                    snapshot,
                )
                self.assertTrue(resumed.completed)
                self.assertEqual(session.accepted_path, resumed.accepted_path)
                self.assertEqual(session.current_fen, resumed.current_fen)
                self.assertEqual(snapshot, resumed.snapshot())

    def test_persisted_release_material_rejects_non_move_definition_drift(self) -> None:
        tasks = build_training_task_catalogue()
        course = build_release_starter_course()
        exercise_entries = BookIndex(course).of_kind(BookEntryKind.EXERCISE)
        self.assertEqual(len(tasks), len(exercise_entries))

        for ordinal, (task, entry) in enumerate(
            zip(tasks, exercise_entries, strict=True)
        ):
            material = build_book_training_material(course, entry.target.key)
            next_task = tasks[(ordinal + 1) % len(tasks)]
            self.assertNotEqual(task.fen, next_task.fen)

            mutations = (
                ("exercise_id", lambda definition: definition.__setitem__(
                    "exercise_id", str(definition["exercise_id"]) + "-forged"
                )),
                ("start_fen", lambda definition: definition.__setitem__(
                    "start_fen", next_task.fen
                )),
                ("title", lambda definition: definition.__setitem__(
                    "title", str(definition["title"]) + " [forged]"
                )),
                ("tags", lambda definition: definition.__setitem__(
                    "tags", [*definition["tags"], "forged"]
                )),
                ("source_id", lambda definition: definition.__setitem__(
                    "source_id", "forged-source-id"
                )),
                ("metadata", lambda definition: definition.__setitem__(
                    "metadata", {**definition["metadata"], "difficulty": "forged"}
                )),
                ("hint", lambda definition: definition["steps"][0].__setitem__(
                    "hint", "forged hint"
                )),
                ("explanation", lambda definition: definition["steps"][0].__setitem__(
                    "explanation", "forged explanation"
                )),
            )

            for field, mutate in mutations:
                with self.subTest(task_id=task.task_id, field=field):
                    payload = json.loads(
                        json.dumps(material.as_dict(), ensure_ascii=False)
                    )
                    definition = payload["definition"]
                    self.assertIsInstance(definition, dict)
                    mutate(definition)

                    with self.assertRaises(BookTrainingError) as caught:
                        restore_book_training_material(course, payload)
                    self.assertEqual(
                        BookTrainingErrorCode.STALE_ORIGIN,
                        caught.exception.code,
                    )

    def test_persisted_release_material_rejects_semantic_origin_identity_drift(self) -> None:
        course = build_release_starter_course()
        exercise_entries = BookIndex(course).of_kind(BookEntryKind.EXERCISE)
        self.assertEqual(EXPECTED_TRAINING_TASKS, len(exercise_entries))

        for ordinal, entry in enumerate(exercise_entries):
            material = build_book_training_material(course, entry.target.key)
            next_entry = exercise_entries[(ordinal + 1) % len(exercise_entries)]
            self.assertNotEqual(entry.target.key, next_entry.target.key)

            origin_mutations = (
                ("target_key", next_entry.target.key),
                (
                    "block_id",
                    str(material.origin.block_id) + "-forged"
                    if material.origin.block_id is not None
                    else "forged-block-id",
                ),
                (
                    "source_anchor",
                    str(material.origin.source_anchor) + ":forged"
                    if material.origin.source_anchor is not None
                    else "forged:source:anchor",
                ),
                (
                    "book_fingerprint",
                    "0" * 64
                    if material.origin.book_fingerprint != "0" * 64
                    else "1" * 64,
                ),
            )

            for field, forged_value in origin_mutations:
                with self.subTest(target=entry.target.key, field=field):
                    payload = json.loads(
                        json.dumps(material.as_dict(), ensure_ascii=False)
                    )
                    origin = payload["origin"]
                    self.assertIsInstance(origin, dict)
                    origin[field] = forged_value

                    with self.assertRaises(BookTrainingError) as caught:
                        restore_book_training_material(course, payload)
                    self.assertEqual(
                        BookTrainingErrorCode.STALE_ORIGIN,
                        caught.exception.code,
                    )

    def test_persisted_release_material_rejects_tampered_training_definition(self) -> None:
        tasks = build_training_task_catalogue()
        course = build_release_starter_course()
        exercise_entries = BookIndex(course).of_kind(BookEntryKind.EXERCISE)
        self.assertEqual(len(tasks), len(exercise_entries))

        for task, entry in zip(tasks, exercise_entries, strict=True):
            with self.subTest(task_id=task.task_id, target=entry.target.key):
                material = build_book_training_material(course, entry.target.key)
                payload = json.loads(
                    json.dumps(material.as_dict(), ensure_ascii=False)
                )

                board = Board(task.fen)
                alternatives = [
                    move
                    for move in board.legal_moves()
                    if _uci(move) != task.answer_uci
                ]
                self.assertTrue(alternatives)
                alternative_board = Board(task.fen)
                alternative_san = alternative_board.push(alternatives[0])

                definition = payload["definition"]
                self.assertIsInstance(definition, dict)
                steps = definition["steps"]
                self.assertIsInstance(steps, list)
                self.assertEqual(1, len(steps))
                step = steps[0]
                self.assertIsInstance(step, dict)
                step["accepted_moves"] = [alternative_san]

                with self.assertRaises(BookTrainingError) as caught:
                    restore_book_training_material(course, payload)
                self.assertEqual(
                    BookTrainingErrorCode.STALE_ORIGIN,
                    caught.exception.code,
                )

    def test_persisted_release_material_rejects_tampered_origin_digest(self) -> None:
        course = build_release_starter_course()
        exercise_entries = BookIndex(course).of_kind(BookEntryKind.EXERCISE)
        self.assertEqual(EXPECTED_TRAINING_TASKS, len(exercise_entries))

        for entry in exercise_entries:
            with self.subTest(target=entry.target.key):
                material = build_book_training_material(course, entry.target.key)
                payload = json.loads(
                    json.dumps(material.as_dict(), ensure_ascii=False)
                )
                origin = payload["origin"]
                self.assertIsInstance(origin, dict)
                original_digest = origin["block_digest"]
                self.assertIsInstance(original_digest, str)
                replacement = (
                    "0" * 64
                    if original_digest != "0" * 64
                    else "1" * 64
                )
                origin["block_digest"] = replacement

                with self.assertRaises(BookTrainingError) as caught:
                    restore_book_training_material(course, payload)
                self.assertEqual(
                    BookTrainingErrorCode.STALE_ORIGIN,
                    caught.exception.code,
                )

    def test_release_origins_survive_reordering_and_reject_content_drift(self) -> None:
        course = build_release_starter_course()
        exercise_entries = BookIndex(course).of_kind(BookEntryKind.EXERCISE)
        self.assertEqual(EXPECTED_TRAINING_TASKS, len(exercise_entries))

        inserted = Paragraph(
            text="Regression-only unrelated semantic block.",
            block_id="starter-release-regression-unrelated",
            source_anchor="starter-release:regression:unrelated",
        )
        shifted = BookDocument(
            title=course.title,
            language=course.language,
            author=course.author,
            source_name=course.source_name,
            source_uri=course.source_uri,
            source_rights=course.source_rights,
            warnings=list(course.warnings),
            blocks=[inserted, *course.blocks],
        )

        for ordinal in (0, EXPECTED_TRAINING_TASKS // 2, EXPECTED_TRAINING_TASKS - 1):
            entry = exercise_entries[ordinal]
            material = build_book_training_material(course, entry.target.key)
            with self.subTest(ordinal=ordinal, target=entry.target.key):
                shifted_location = resolve_book_training_origin(shifted, material.origin)
                self.assertEqual(entry.target.index + 1, shifted_location.index)
                self.assertNotEqual(material.origin.index_at_export, shifted_location.index)
                restored = restore_book_training_material(shifted, material.as_dict())
                self.assertEqual(material.as_dict(), restored.as_dict())

                original = course.blocks[entry.target.index]
                self.assertIsInstance(original, Exercise)
                assert isinstance(original, Exercise)
                changed = Exercise(
                    fen=original.fen,
                    prompt=original.prompt + " [semantic drift]",
                    solution_pgn=original.solution_pgn,
                    answer_text=original.answer_text,
                    difficulty=original.difficulty,
                    block_id=original.block_id,
                    source_anchor=original.source_anchor,
                )
                drifted_blocks = list(course.blocks)
                drifted_blocks[entry.target.index] = changed
                drifted = BookDocument(
                    title=course.title,
                    language=course.language,
                    author=course.author,
                    source_name=course.source_name,
                    source_uri=course.source_uri,
                    source_rights=course.source_rights,
                    warnings=list(course.warnings),
                    blocks=drifted_blocks,
                )
                with self.assertRaises(BookTrainingError) as caught:
                    resolve_book_training_origin(drifted, material.origin)
                self.assertEqual(BookTrainingErrorCode.STALE_ORIGIN, caught.exception.code)


if __name__ == "__main__":
    unittest.main()
