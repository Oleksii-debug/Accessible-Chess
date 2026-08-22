from __future__ import annotations

import unittest

from acs.analysis_service import AnalysisService
from acs.bookdocument import Exercise as BookExercise
from acs.bookdocument import Heading, Position, VariationTree
from acs.engine_assisted_workflows import (
    EngineAssistedWorkflowService,
    EngineVisibility,
)
from acs.engine_ports import EngineContractError, RawAnalysisLine
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep


FEN = "8/8/8/8/8/8/4K3/7k w - - 0 1"
FEN_2 = "8/8/8/8/8/8/4K3/6k1 w - - 0 1"


class FakeAnalysisEngine:
    def __init__(self, *, on_analyze=None, failure: Exception | None = None):
        self.calls = []
        self.closed = False
        self.on_analyze = on_analyze
        self.failure = failure

    def analyze(self, fen, multipv=5, depth=16):
        self.calls.append((fen, multipv, depth))
        if self.on_analyze is not None:
            self.on_analyze()
        if self.failure is not None:
            raise self.failure
        return [
            RawAnalysisLine(
                depth=depth,
                score_kind="cp",
                score_value=42,
                pv=("e2e4", "e7e5"),
            )
        ]

    def close(self):
        self.closed = True


def make_session() -> ExerciseSession:
    return ExerciseSession(
        ExerciseDefinition(
            exercise_id="lesson-1",
            start_fen=FEN,
            steps=(
                ExerciseStep(
                    frozenset({"e4"}),
                    hint="Control the centre.",
                ),
            ),
        )
    )


class EngineAssistedWorkflowTests(unittest.TestCase):
    def make_service(self, engine: FakeAnalysisEngine):
        analysis = AnalysisService(lambda: engine)
        return EngineAssistedWorkflowService(analysis), analysis

    def test_visibility_tokens_match_teacher_presentation_contract(self):
        self.assertEqual(
            EngineVisibility.VISIBLE_TO_TEACHER.value,
            "visible_to_teacher",
        )
        self.assertEqual(
            EngineVisibility.VISIBLE_TO_STUDENT.value,
            "visible_to_student",
        )
        self.assertEqual(EngineVisibility.HIDDEN.value, "hidden")

    def test_teacher_only_projection_never_exposes_student_lines(self):
        engine = FakeAnalysisEngine()
        service, analysis = self.make_service(engine)
        try:
            result = service.analyze_teacher(
                FEN,
                visibility="visible_to_teacher",
                context_revision=4,
                revision_provider=lambda: 4,
            )
        finally:
            analysis.close()
        self.assertFalse(result.stale)
        self.assertEqual(len(result.teacher_lines), 1)
        self.assertEqual(result.student_lines, ())
        self.assertFalse(result.available_to_student)

    def test_student_visible_projection_is_explicitly_shared(self):
        engine = FakeAnalysisEngine()
        service, analysis = self.make_service(engine)
        try:
            result = service.analyze_teacher(
                FEN,
                visibility=EngineVisibility.VISIBLE_TO_STUDENT,
                context_revision="lesson-r7",
                revision_provider=lambda: "lesson-r7",
            )
        finally:
            analysis.close()
        self.assertEqual(result.teacher_lines, result.student_lines)
        self.assertTrue(result.available_to_teacher)
        self.assertTrue(result.available_to_student)

    def test_hidden_analysis_can_run_without_answer_material_leaking(self):
        engine = FakeAnalysisEngine()
        service, analysis = self.make_service(engine)
        try:
            result = service.analyze_teacher(
                FEN,
                visibility="hidden",
                context_revision=1,
                revision_provider=lambda: 1,
            )
        finally:
            analysis.close()
        self.assertEqual(len(engine.calls), 1)
        self.assertEqual(result.teacher_lines, ())
        self.assertEqual(result.student_lines, ())
        self.assertFalse(result.available_to_teacher)
        self.assertFalse(result.available_to_student)

    def test_provider_error_is_sanitized_before_audience_projection(self):
        secret = r"C:\Users\Teacher\private\stockfish.exe"
        engine = FakeAnalysisEngine(failure=RuntimeError(secret))
        service, analysis = self.make_service(engine)
        try:
            result = service.analyze_teacher(
                FEN,
                visibility="visible_to_teacher",
                context_revision=2,
                revision_provider=lambda: 2,
            )
        finally:
            analysis.close()
        self.assertEqual(result.error, "engine analysis unavailable")
        self.assertNotIn("Users", result.error)
        self.assertEqual(result.teacher_lines, ())
        self.assertEqual(result.student_lines, ())

    def test_training_analysis_does_not_mutate_progress(self):
        session = make_session()
        before = session.snapshot()
        engine = FakeAnalysisEngine()
        service, analysis = self.make_service(engine)
        try:
            result = service.analyze_training(session, FEN, multipv=1, depth=10)
        finally:
            analysis.close()
        self.assertFalse(result.stale)
        self.assertEqual(session.snapshot(), before)
        self.assertEqual(engine.calls, [(FEN, 1, 10)])

    def test_training_progress_change_during_engine_call_suppresses_answer(self):
        session = make_session()
        engine = FakeAnalysisEngine(on_analyze=lambda: session.request_hint())
        service, analysis = self.make_service(engine)
        try:
            result = service.analyze_training(
                session,
                FEN,
                visibility="visible_to_student",
            )
        finally:
            analysis.close()
        self.assertTrue(result.stale)
        self.assertEqual(result.teacher_lines, ())
        self.assertEqual(result.student_lines, ())
        self.assertEqual(session.hints_used, 1)

    def test_book_analysis_uses_only_explicit_semantic_fen_and_never_edits_block(self):
        blocks = (
            Position(fen=FEN, caption="Position"),
            VariationTree(root_fen=FEN, pgn="1. e4"),
            BookExercise(fen=FEN, prompt="Move", answer_text="e4"),
        )
        for block in blocks:
            with self.subTest(kind=type(block).__name__):
                engine = FakeAnalysisEngine()
                service, analysis = self.make_service(engine)
                before = dict(block.as_dict())
                try:
                    result = service.analyze_book_block(block)
                finally:
                    analysis.close()
                self.assertFalse(result.stale)
                self.assertEqual(block.as_dict(), before)
                self.assertEqual(engine.calls[0][0], FEN)

    def test_book_mutation_during_engine_call_suppresses_stale_answer(self):
        block = Position(fen=FEN)
        engine = FakeAnalysisEngine(on_analyze=lambda: setattr(block, "fen", FEN_2))
        service, analysis = self.make_service(engine)
        try:
            result = service.analyze_book_block(
                block,
                visibility="visible_to_student",
            )
        finally:
            analysis.close()
        self.assertTrue(result.stale)
        self.assertEqual(result.teacher_lines, ())
        self.assertEqual(result.student_lines, ())

    def test_non_position_book_block_is_rejected_before_engine_call(self):
        engine = FakeAnalysisEngine()
        service, analysis = self.make_service(engine)
        try:
            with self.assertRaises(EngineContractError):
                service.analyze_book_block(Heading(text="Chapter"))
        finally:
            analysis.close()
        self.assertEqual(engine.calls, [])

    def test_stale_teacher_revision_is_rejected_before_engine_call(self):
        engine = FakeAnalysisEngine()
        service, analysis = self.make_service(engine)
        try:
            result = service.analyze_teacher(
                FEN,
                visibility="visible_to_teacher",
                context_revision=7,
                revision_provider=lambda: 8,
            )
        finally:
            analysis.close()
        self.assertTrue(result.stale)
        self.assertEqual(engine.calls, [])
        self.assertEqual(result.teacher_lines, ())

    def test_teacher_revision_change_during_analysis_suppresses_answer(self):
        revision = {"value": 11}

        def change_revision():
            revision["value"] = 12

        engine = FakeAnalysisEngine(on_analyze=change_revision)
        service, analysis = self.make_service(engine)
        try:
            result = service.analyze_teacher(
                FEN,
                visibility="visible_to_student",
                context_revision=11,
                revision_provider=lambda: revision["value"],
            )
        finally:
            analysis.close()
        self.assertTrue(result.stale)
        self.assertEqual(result.teacher_lines, ())
        self.assertEqual(result.student_lines, ())

    def test_visibility_and_revision_scalars_fail_closed_without_coercion(self):
        engine = FakeAnalysisEngine()
        service, analysis = self.make_service(engine)
        try:
            for invalid in (True, 1, 1.0, object()):
                with self.subTest(visibility=repr(invalid)):
                    with self.assertRaises(EngineContractError):
                        service.analyze_teacher(
                            FEN,
                            visibility=invalid,
                            context_revision=1,
                            revision_provider=lambda: 1,
                        )
            for invalid_revision in (True, 1.0, "", " "):
                with self.subTest(revision=repr(invalid_revision)):
                    with self.assertRaises(EngineContractError):
                        service.analyze_teacher(
                            FEN,
                            visibility="hidden",
                            context_revision=invalid_revision,
                            revision_provider=lambda: invalid_revision,
                        )
        finally:
            analysis.close()
        self.assertEqual(engine.calls, [])


if __name__ == "__main__":
    unittest.main()
