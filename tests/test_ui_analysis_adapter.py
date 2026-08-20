from types import SimpleNamespace
import unittest

from acs.chesscore import Board
from acs.engine_ports import EngineContractError, EngineContractErrorCode
from acs.ui_analysis_adapter import (
    AnalysisPresentation,
    AnalysisPresentationAdapter,
    AnalysisPresentationLine,
)

START_FEN = Board.START


class FakePresentationService:
    def __init__(self):
        self.current = SimpleNamespace(
            running=False,
            fen=None,
            multipv=5,
            depth=16,
            last_result=None,
        )
        self.starts = []
        self.updates = []
        self.stop_count = 0
        self.close_count = 0
        self.fail_start = False
        self.fail_update = False
        self.fail_configure = False
        self.configures = []

    def start(self, fen, multipv=5, depth=16):
        if self.fail_start:
            raise RuntimeError("start failed")
        self.starts.append((fen, multipv, depth))
        self.current.running = True
        self.current.fen = fen
        self.current.multipv = multipv
        self.current.depth = depth
        return len(self.starts)

    def update_position(self, fen):
        if self.fail_update:
            raise RuntimeError("update failed")
        self.updates.append(fen)
        self.current.fen = fen
        return len(self.updates)

    def stop(self):
        self.stop_count += 1
        self.current.running = False
        return self.stop_count

    def configure(self, *, multipv=None, depth=None):
        if self.fail_configure:
            raise RuntimeError("configure failed")
        self.configures.append((multipv, depth))
        self.current.multipv = multipv
        self.current.depth = depth
        self.current.last_result = None
        return len(self.configures)

    def close(self):
        self.close_count += 1
        self.current.running = False

    def state(self):
        return self.current


def structural_result(fen, lines=(), *, stale=False, error=None):
    return SimpleNamespace(
        fen=fen,
        stale=stale,
        error=error,
        lines=lines,
    )


class AnalysisPresentationAdapterTests(unittest.TestCase):
    def test_line_and_presentation_dtos_are_exact_and_detached(self):
        first = AnalysisPresentationLine(1, 18, " cp ", 34, (" e2e4 ",))
        second = AnalysisPresentationLine(2, 17, "mate", -3, ("d2d4",))
        presentation = AnalysisPresentation(
            True,
            "  fen-a  ",
            True,
            2,
            18,
            (first, second),
            None,
            False,
        )
        payload = presentation.as_dict()
        payload["lines"][0]["pv"].append("e7e5")

        self.assertEqual(presentation.fen, "fen-a")
        self.assertEqual(presentation.lines[0].score_kind, "cp")
        self.assertEqual(presentation.lines[0].pv, ("e2e4",))

        invalid_lines = (
            (True, 18, "cp", 1, ("e2e4",)),
            (0, 18, "cp", 1, ("e2e4",)),
            (11, 18, "cp", 1, ("e2e4",)),
            (1, True, "cp", 1, ("e2e4",)),
            (1, -1, "cp", 1, ("e2e4",)),
            (1, 18, True, 1, ("e2e4",)),
            (1, 18, "wdl", 1, ("e2e4",)),
            (1, 18, "cp", True, ("e2e4",)),
            (1, 18, "cp", 1, ["e2e4"]),
            (1, 18, "cp", 1, (True,)),
        )
        for values in invalid_lines:
            with self.subTest(line=values):
                with self.assertRaises(EngineContractError) as caught:
                    AnalysisPresentationLine(*values)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_RESULT,
                )

        invalid_presentations = (
            (1, None, False, 5, 16, (), None, False),
            (False, None, 1, 5, 16, (), None, False),
            (False, True, False, 5, 16, (), None, False),
            (False, "fen", False, 5, 16, (), None, False),
            (True, None, False, 5, 16, (), None, False),
            (True, "fen", False, True, 16, (), None, False),
            (True, "fen", False, 0, 16, (), None, False),
            (True, "fen", False, 5, True, (), None, False),
            (True, "fen", False, 5, 41, (), None, False),
            (True, "fen", False, 5, 16, [], None, False),
            (True, "fen", False, 5, 16, (object(),), None, False),
            (True, "fen", False, 5, 16, (), "   ", False),
            (True, "fen", False, 5, 16, (), 7, False),
            (True, "fen", False, 5, 16, (), None, 1),
            (True, "fen", False, 5, 16, (first,), None, True),
            (True, "fen", False, 5, 16, (first,), "offline", False),
            (True, "fen", False, 5, 16, (second,), None, False),
            (True, "fen", False, 1, 16, (first, second), None, False),
        )
        for values in invalid_presentations:
            with self.subTest(presentation=values):
                with self.assertRaises(EngineContractError) as caught:
                    AnalysisPresentation(*values)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_SESSION,
                )

    def test_constructor_validates_service_and_exact_limit_scalars(self):
        for service in (object(), FakePresentationService):
            with self.subTest(service=service):
                with self.assertRaises(EngineContractError) as caught:
                    AnalysisPresentationAdapter(service)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_PROVIDER,
                )

        for kwargs in (
            {"multipv": True},
            {"multipv": "5"},
            {"multipv": 5.0},
            {"depth": True},
            {"depth": "16"},
            {"depth": 16.0},
        ):
            with self.subTest(config=kwargs):
                with self.assertRaises(EngineContractError) as caught:
                    AnalysisPresentationAdapter(None, **kwargs)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_CONFIG,
                )

        clamped = AnalysisPresentationAdapter(None, multipv=99, depth=0)
        snapshot = clamped.snapshot("fen")
        self.assertEqual((snapshot.multipv, snapshot.depth), (10, 1))

    def test_enable_and_sync_publish_state_only_after_service_success(self):
        service = FakePresentationService()
        adapter = AnalysisPresentationAdapter(service)
        service.fail_start = True

        with self.assertRaisesRegex(RuntimeError, "start failed"):
            adapter.enable("fen-a")
        self.assertFalse(adapter.enabled)
        self.assertIsNone(adapter._fen)

        service.fail_start = False
        adapter.enable("  fen-a  ")
        self.assertTrue(adapter.enabled)
        self.assertEqual(adapter._fen, "fen-a")
        self.assertEqual(service.starts, [("fen-a", 5, 16)])

        service.fail_update = True
        with self.assertRaisesRegex(RuntimeError, "update failed"):
            adapter.sync_position("fen-b")
        self.assertEqual(adapter._fen, "fen-a")
        self.assertEqual(service.current.fen, "fen-a")

        service.fail_update = False
        adapter.sync_position("  fen-b  ")
        self.assertEqual(adapter._fen, "fen-b")
        self.assertEqual(service.updates, ["fen-b"])

        adapter.disable()
        self.assertFalse(adapter.enabled)
        self.assertEqual(service.stop_count, 1)
        adapter.close()
        self.assertEqual(service.close_count, 1)

    def test_projection_accepts_bounded_structural_and_dictionary_lines(self):
        service = FakePresentationService()
        adapter = AnalysisPresentationAdapter(service, multipv=2, depth=18)
        adapter.enable(START_FEN)
        service.current.last_result = structural_result(
            START_FEN,
            (
                SimpleNamespace(
                    multipv=1,
                    depth=18,
                    score_kind="cp",
                    score_value=34,
                    pv=("e2e4", "e7e5"),
                ),
                {
                    "multipv": 2,
                    "depth": 17,
                    "scoreKind": "mate",
                    "scoreValue": -3,
                    "pv": ["d2d4"],
                },
            ),
        )

        snapshot = adapter.snapshot(START_FEN)

        self.assertEqual(len(snapshot.lines), 2)
        self.assertIsInstance(snapshot.lines[0], AnalysisPresentationLine)
        self.assertEqual(snapshot.lines[1].score_kind, "mate")
        self.assertEqual(
            snapshot.as_dict()["lines"][0]["pv"],
            ["e4", "e5"],
        )
        self.assertEqual(len(snapshot.lines[0].position_fens), 2)

    def test_stale_and_error_results_suppress_untrusted_lines(self):
        service = FakePresentationService()
        adapter = AnalysisPresentationAdapter(service)
        adapter.enable("fen-current")
        service.current.last_result = structural_result(
            "fen-old",
            object(),
            stale=False,
            error=7,
        )

        stale = adapter.snapshot("fen-current")
        self.assertTrue(stale.stale)
        self.assertEqual(stale.lines, ())
        self.assertIsNone(stale.error)

        service.current.last_result = structural_result(
            "fen-current",
            object(),
            error="  provider offline  ",
        )
        failed = adapter.snapshot("fen-current")
        self.assertFalse(failed.stale)
        self.assertEqual(failed.error, "provider offline")
        self.assertEqual(failed.lines, ())

        service.current.last_result = None
        service.current.fen = "fen-old"
        state_mismatch = adapter.snapshot("fen-current")
        self.assertTrue(state_mismatch.stale)
        self.assertEqual(state_mismatch.lines, ())

    def test_invalid_current_state_or_line_fails_with_stable_code(self):
        service = FakePresentationService()
        adapter = AnalysisPresentationAdapter(service)
        adapter.enable("fen")
        service.current.running = 1
        with self.assertRaises(EngineContractError) as state_error:
            adapter.snapshot("fen")
        self.assertEqual(
            state_error.exception.code,
            EngineContractErrorCode.INVALID_SESSION,
        )

        service.current.running = True
        service.current.last_result = structural_result(
            "fen",
            (
                SimpleNamespace(
                    multipv=True,
                    depth=18,
                    score_kind="cp",
                    score_value=1,
                    pv=("e2e4",),
                ),
            ),
        )
        with self.assertRaises(EngineContractError) as result_error:
            adapter.snapshot("fen")
        self.assertEqual(
            result_error.exception.code,
            EngineContractErrorCode.INVALID_RESULT,
        )

    def test_text_commands_validate_index_language_and_fen(self):
        service = FakePresentationService()
        adapter = AnalysisPresentationAdapter(service)
        adapter.enable(START_FEN)
        service.current.last_result = structural_result(
            START_FEN,
            (
                SimpleNamespace(
                    multipv=1,
                    depth=18,
                    score_kind="cp",
                    score_value=34,
                    pv=("e2e4", "e7e5"),
                ),
            ),
        )

        self.assertIn("Варіант 1", adapter.read_pv(1, START_FEN, lang="uk"))
        self.assertIn("Variation 1", adapter.read_pv(1, START_FEN, lang="en"))
        self.assertIn("Оцінка", adapter.evaluation_text(START_FEN, lang="uk"))
        self.assertIn("e 4", adapter.best_move_text(START_FEN, lang="en"))

        for index in (True, "1", 1.0):
            with self.subTest(index=index):
                with self.assertRaises(EngineContractError) as caught:
                    adapter.read_pv(index, START_FEN)
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_REQUEST,
                )
        with self.assertRaises(EngineContractError) as language_error:
            adapter.read_pv(1, START_FEN, lang="fr")
        self.assertEqual(
            language_error.exception.code,
            EngineContractErrorCode.INVALID_REQUEST,
        )
        with self.assertRaises(EngineContractError) as fen_error:
            adapter.snapshot(True)
        self.assertEqual(
            fen_error.exception.code,
            EngineContractErrorCode.INVALID_REQUEST,
        )

    def test_uci_is_legality_checked_then_projected_only_as_san(self):
        service = FakePresentationService()
        adapter = AnalysisPresentationAdapter(service)
        adapter.enable(START_FEN)
        service.current.last_result = structural_result(
            START_FEN,
            (
                SimpleNamespace(
                    multipv=1,
                    depth=20,
                    score_kind="cp",
                    score_value=27,
                    pv=("e2e4", "e7e5", "g1f3"),
                ),
            ),
        )

        snapshot = adapter.snapshot(START_FEN)

        self.assertEqual(snapshot.lines[0].pv, ("e4", "e5", "Nf3"))
        self.assertNotIn("e2e4", str(snapshot.as_dict()))
        self.assertEqual(len(snapshot.lines[0].position_fens), 3)

        service.current.last_result = structural_result(
            START_FEN,
            (
                SimpleNamespace(
                    multipv=1,
                    depth=20,
                    score_kind="cp",
                    score_value=27,
                    pv=("e2e5",),
                ),
            ),
        )
        with self.assertRaises(EngineContractError) as caught:
            adapter.snapshot(START_FEN)
        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_RESULT)

    def test_lock_configuration_and_temporary_exploration_preserve_target(self):
        service = FakePresentationService()
        adapter = AnalysisPresentationAdapter(service)
        adapter.enable(START_FEN)
        service.current.last_result = structural_result(
            START_FEN,
            (
                SimpleNamespace(
                    multipv=1,
                    depth=18,
                    score_kind="cp",
                    score_value=34,
                    pv=("e2e4", "e7e5"),
                ),
            ),
        )
        after_e4 = Board(START_FEN)
        after_e4.push_text("e4")

        adapter.lock_target()
        locked = adapter.snapshot(after_e4.fen())
        self.assertTrue(locked.target_locked)
        self.assertFalse(locked.stale)
        self.assertEqual(locked.fen, START_FEN)

        first = adapter.begin_exploration(after_e4.fen())
        self.assertEqual(first.san, "e4")
        second = adapter.step_exploration(1)
        self.assertEqual(second.san, "e5")
        self.assertEqual(adapter.snapshot(after_e4.fen()).exploration_ply, 2)
        adapter.return_from_exploration()

        adapter.unlock_target(after_e4.fen())
        self.assertEqual(service.updates[-1], after_e4.fen())
        self.assertFalse(adapter.target_locked)

        adapter.configure(multipv=3, depth=24)
        self.assertEqual(service.configures[-1], (3, 24))
        configured = adapter.snapshot(after_e4.fen())
        self.assertEqual((configured.multipv, configured.depth), (3, 24))

    def test_provider_details_never_cross_user_bridge_or_spoken_text(self):
        service = FakePresentationService()
        adapter = AnalysisPresentationAdapter(service)
        adapter.enable(START_FEN)
        secret = r"C:\\Users\\person\\engine.exe: provider offline"
        service.current.last_result = structural_result(START_FEN, error=secret)

        snapshot = adapter.snapshot(START_FEN)

        self.assertEqual(snapshot.error, secret)
        self.assertEqual(snapshot.as_dict()["error"], "engine_error")
        self.assertNotIn(secret, adapter.read_pv(1, START_FEN, lang="uk"))
        self.assertEqual(adapter.read_pv(1, START_FEN, lang="uk"), "Помилка Stockfish.")


if __name__ == "__main__":
    unittest.main()
