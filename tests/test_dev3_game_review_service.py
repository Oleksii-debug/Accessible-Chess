from __future__ import annotations

from threading import Event, Thread
import unittest

from acs.analysis_service import AnalysisService
from acs.engine_ports import EngineContractError, EngineContractErrorCode, RawAnalysisLine
from acs.game_review_service import (
    GAME_REVIEW_MAX_POSITIONS,
    GAME_REVIEW_SAFE_ERROR,
    GameReviewPosition,
    GameReviewService,
    GameReviewStatus,
)


FEN = "8/8/8/8/8/8/4K3/7k w - - 0 1"
FEN_2 = "8/8/8/8/8/8/4K3/6k1 w - - 0 1"


class FakeAnalysisEngine:
    def __init__(self):
        self.calls = []
        self.closed = False
        self.on_analyze = None
        self.fail_calls: set[int] = set()

    def analyze(self, fen, multipv=5, depth=16):
        self.calls.append((fen, multipv, depth))
        call_number = len(self.calls)
        if self.on_analyze is not None:
            self.on_analyze(call_number)
        if call_number in self.fail_calls:
            raise RuntimeError(r"C:\Users\Student\private\stockfish.exe")
        return [
            RawAnalysisLine(
                depth=depth,
                score_kind="cp",
                score_value=call_number * 25,
                pv=("e2e4", "e7e5"),
            )
        ]

    def close(self):
        self.closed = True


def position(index: int, fen: str = FEN) -> GameReviewPosition:
    return GameReviewPosition(
        student_id="student-1",
        session_id="session-1",
        game_ref="game-42",
        source_revision="rev-a",
        position_id=f"ply-{index}",
        ply=index,
        fen=fen,
    )


class GameReviewServiceTests(unittest.TestCase):
    def make_service(self):
        engine = FakeAnalysisEngine()
        analysis = AnalysisService(lambda: engine)
        return GameReviewService(analysis), analysis, engine

    def test_batch_returns_transient_evaluations_with_stable_linkage_and_no_pv(self):
        service, analysis, engine = self.make_service()
        try:
            result = service.review((position(1), position(2, FEN_2)), depth=12)
        finally:
            analysis.close()

        self.assertFalse(result.cancelled)
        self.assertEqual(result.requested_count, 2)
        self.assertEqual(len(result.points), 2)
        self.assertEqual(engine.calls, [(FEN, 1, 12), (FEN_2, 1, 12)])
        first = result.points[0]
        self.assertEqual(first.status, GameReviewStatus.ANALYZED)
        self.assertEqual(first.student_id, "student-1")
        self.assertEqual(first.session_id, "session-1")
        self.assertEqual(first.game_ref, "game-42")
        self.assertEqual(first.source_revision, "rev-a")
        self.assertEqual(first.position_id, "ply-1")
        self.assertEqual(first.ply, 1)
        self.assertEqual(first.score_kind, "cp")
        self.assertEqual(first.score_value, 25)
        self.assertFalse(hasattr(first, "pv"))

    def test_oversized_batch_is_rejected_before_any_engine_call(self):
        service, analysis, engine = self.make_service()
        oversized = tuple(position(index) for index in range(GAME_REVIEW_MAX_POSITIONS + 1))
        try:
            with self.assertRaises(EngineContractError):
                service.review(oversized)
        finally:
            analysis.close()
        self.assertEqual(engine.calls, [])

    def test_batch_requires_tuple_and_exact_bounded_depth(self):
        service, analysis, engine = self.make_service()
        try:
            with self.assertRaises(EngineContractError):
                service.review([position(1)])
            for invalid in (True, 0, 41, 1.0, "16"):
                with self.subTest(depth=repr(invalid)):
                    with self.assertRaises(EngineContractError):
                        service.review((position(1),), depth=invalid)
        finally:
            analysis.close()
        self.assertEqual(engine.calls, [])

    def test_batch_scope_and_position_identity_are_validated_before_engine_work(self):
        service, analysis, engine = self.make_service()
        duplicate = GameReviewPosition(
            "student-1",
            "session-1",
            "game-42",
            "rev-a",
            "ply-1",
            2,
            FEN_2,
        )
        mixed_scope = GameReviewPosition(
            "student-2",
            "session-1",
            "game-42",
            "rev-a",
            "ply-2",
            2,
            FEN_2,
        )
        try:
            with self.assertRaises(EngineContractError):
                service.review((position(1), duplicate))
            with self.assertRaises(EngineContractError):
                service.review((position(1), mixed_scope))
        finally:
            analysis.close()
        self.assertEqual(engine.calls, [])

    def test_cancel_before_first_position_never_calls_engine(self):
        service, analysis, engine = self.make_service()
        try:
            result = service.review((position(1), position(2)), cancel_provider=lambda: True)
        finally:
            analysis.close()
        self.assertTrue(result.cancelled)
        self.assertEqual(result.points, ())
        self.assertEqual(result.requested_count, 2)
        self.assertEqual(engine.calls, [])

    def test_cancel_arriving_during_engine_call_suppresses_completed_answer(self):
        service, analysis, engine = self.make_service()
        cancelled = {"value": False}

        def on_analyze(_call_number):
            cancelled["value"] = True

        engine.on_analyze = on_analyze
        try:
            result = service.review(
                (position(1), position(2)),
                cancel_provider=lambda: cancelled["value"],
            )
        finally:
            analysis.close()
        self.assertTrue(result.cancelled)
        self.assertEqual(result.points, ())
        self.assertEqual(len(engine.calls), 1)

    def test_cancel_between_positions_preserves_only_completed_prefix(self):
        service, analysis, engine = self.make_service()
        states = iter((False, False, True))
        try:
            result = service.review(
                (position(1), position(2), position(3)),
                cancel_provider=lambda: next(states),
            )
        finally:
            analysis.close()
        self.assertTrue(result.cancelled)
        self.assertEqual(len(result.points), 1)
        self.assertEqual(result.points[0].position_id, "ply-1")
        self.assertEqual(len(engine.calls), 1)

    def test_provider_failure_is_sanitized_and_batch_continues(self):
        service, analysis, engine = self.make_service()
        engine.fail_calls.add(1)
        try:
            result = service.review((position(1), position(2)))
        finally:
            analysis.close()
        self.assertFalse(result.cancelled)
        self.assertEqual(len(result.points), 2)
        failed, recovered = result.points
        self.assertEqual(failed.status, GameReviewStatus.UNAVAILABLE)
        self.assertEqual(failed.error, GAME_REVIEW_SAFE_ERROR)
        self.assertNotIn("Users", failed.error)
        self.assertIsNone(failed.score_value)
        self.assertEqual(recovered.status, GameReviewStatus.ANALYZED)
        self.assertEqual(recovered.score_value, 50)

    def test_analysis_invalidation_marks_point_stale_without_answer_material(self):
        service, analysis, engine = self.make_service()
        engine.on_analyze = lambda _call_number: analysis.invalidate(FEN_2)
        try:
            result = service.review((position(1),))
        finally:
            analysis.close()
        point = result.points[0]
        self.assertEqual(point.status, GameReviewStatus.STALE)
        self.assertIsNone(point.depth)
        self.assertIsNone(point.score_kind)
        self.assertIsNone(point.score_value)
        self.assertIsNone(point.error)

    def test_concurrent_batch_fails_busy_without_invalidating_active_batch(self):
        service, analysis, engine = self.make_service()
        entered = Event()
        release = Event()
        first_results = []
        first_errors = []

        def block_first(_call_number):
            entered.set()
            release.wait(2)

        def run_first():
            try:
                first_results.append(service.review((position(1),)))
            except Exception as exc:  # pragma: no cover - assertion captures it
                first_errors.append(exc)

        engine.on_analyze = block_first
        worker = Thread(target=run_first, name="dev3-game-review-test")
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            with self.assertRaises(EngineContractError) as captured:
                service.review((position(2),))
            self.assertEqual(captured.exception.code, EngineContractErrorCode.INVALID_SESSION)
            self.assertEqual(len(engine.calls), 1)
        finally:
            release.set()
            worker.join(2)

        try:
            self.assertFalse(worker.is_alive())
            self.assertEqual(first_errors, [])
            self.assertEqual(len(first_results), 1)
            self.assertFalse(first_results[0].cancelled)
            self.assertEqual(first_results[0].points[0].status, GameReviewStatus.ANALYZED)

            # The lock is not terminal: a later batch can run after completion.
            later = service.review((position(2),))
            self.assertEqual(later.points[0].status, GameReviewStatus.ANALYZED)
        finally:
            analysis.close()

    def test_position_identity_fen_and_scalars_fail_closed(self):
        for field, invalid in (
            ("student_id", ""),
            ("session_id", "x" * 257),
            ("game_ref", "bad\nref"),
            ("source_revision", 3),
            ("position_id", object()),
        ):
            kwargs = dict(
                student_id="student",
                session_id="session",
                game_ref="game",
                source_revision="revision",
                position_id="position",
                ply=1,
                fen=FEN,
            )
            kwargs[field] = invalid
            with self.subTest(field=field):
                with self.assertRaises(EngineContractError):
                    GameReviewPosition(**kwargs)
        with self.assertRaises(EngineContractError):
            position(True)
        with self.assertRaises(EngineContractError):
            GameReviewPosition("s", "t", "g", "r", "p", 0, "x" * 513)

    def test_cancel_provider_shape_and_failures_are_fail_closed(self):
        service, analysis, engine = self.make_service()
        try:
            with self.assertRaises(EngineContractError):
                service.review((position(1),), cancel_provider=1)
            with self.assertRaises(EngineContractError):
                service.review((position(1),), cancel_provider=lambda: 1)
            with self.assertRaises(EngineContractError):
                service.review(
                    (position(1),),
                    cancel_provider=lambda: (_ for _ in ()).throw(RuntimeError("secret")),
                )
            recovered = service.review((position(1),))
            self.assertEqual(recovered.points[0].status, GameReviewStatus.ANALYZED)
        finally:
            analysis.close()
        self.assertEqual(len(engine.calls), 1)


if __name__ == "__main__":
    unittest.main()
