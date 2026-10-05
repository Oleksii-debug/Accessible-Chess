from __future__ import annotations

import asyncio
import unittest

from acs.acsdb import AcsDatabase
from acs.agent_tools import ToolCall, ToolExecutor
from acs.analysis_service import AnalysisService
from acs.chess_agent_tools import ChessAgentToolRegistry, MediaAgentBridge
from acs.chesscore import Board
from acs.media_foundation import (
    MediaClock,
    MediaPositionBinding,
    MediaPositionTimeline,
    MediaSessionState,
    MediaSourceKind,
)
from acs.search_service import GameSearchService


PGN = """[Event "Agent Fixture"]
[Site "Test"]
[Date "2026.10.05"]
[Round "1"]
[White "Alpha"]
[Black "Beta"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 1-0
"""

AFTER_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"


class FakeEngine:
    def analyze(self, fen, multipv=5, depth=16):
        return [(depth, ("cp", 25), ["e2e4", "e7e5"])][:multipv]

    def close(self):
        pass


class FakePlayback:
    def __init__(self):
        self.calls = []

    def play(self):
        self.calls.append(("play", None))

    def pause(self):
        self.calls.append(("pause", None))

    def seek(self, position_ms):
        self.calls.append(("seek", position_ms))


class ChessAgentToolsCrossRepoTests(unittest.TestCase):
    def setUp(self):
        self.board = Board()
        self.database = AcsDatabase()
        self.database.import_pgn_text(PGN, source_name="agent-fixture.pgn")
        self.analysis = AnalysisService(lambda: FakeEngine())
        self.search = GameSearchService(self.database)
        self.clock = MediaClock(
            MediaSessionState(
                session_id="session-1",
                source_id="media-1",
                source_kind=MediaSourceKind.LOCAL_FILE,
                position_ms=1500,
                duration_ms=5000,
            )
        )
        self.timeline = MediaPositionTimeline(
            (
                MediaPositionBinding(0, 1000, Board.START),
                MediaPositionBinding(1000, 5000, AFTER_E4, tree_path=(0,)),
            )
        )
        self.playback = FakePlayback()
        self.media = MediaAgentBridge(
            clock=self.clock,
            timeline=self.timeline,
            board_set_fen=lambda fen: self.board.set_fen(fen),
            playback=self.playback,
        )
        self.executor = ToolExecutor()
        ChessAgentToolRegistry(
            executor=self.executor,
            board_provider=lambda: self.board,
            analysis_service=self.analysis,
            search_service=self.search,
            media=self.media,
        ).register_all()

    def tearDown(self):
        self.analysis.close()
        self.database.close()

    def execute(self, tool_id, arguments=None):
        return asyncio.run(
            self.executor.execute(
                ToolCall(
                    call_id=f"call-{tool_id}",
                    tool_id=tool_id,
                    arguments=arguments or {},
                )
            )
        )

    def test_board_tools_read_real_canonical_board(self):
        current = self.execute("board.current")
        self.assertTrue(current.ok)
        self.assertEqual(current.output["fen"], Board().fen())
        self.assertEqual(current.output["legalMoveCount"], 20)

        square = self.execute("board.square", {"square": "e2"})
        self.assertTrue(square.ok)
        self.assertEqual(square.output["piece"], "P")

        legal = self.execute("board.legal_moves")
        self.assertTrue(legal.ok)
        self.assertIn("e4", legal.output["moves"])

    def test_engine_tool_uses_existing_analysis_service(self):
        result = self.execute("engine.analyze", {"multipv": 1, "depth": 12})
        self.assertTrue(result.ok)
        self.assertEqual(result.output["fen"], Board().fen())
        self.assertEqual(result.output["lines"][0]["depth"], 12)
        self.assertEqual(result.output["lines"][0]["scoreKind"], "cp")

    def test_library_tool_uses_real_acsdb_search_service(self):
        result = self.execute("library.search", {"player": "Alpha"})
        self.assertTrue(result.ok)
        self.assertEqual(len(result.output["items"]), 1)
        self.assertEqual(result.output["items"][0]["white"], "Alpha")
        self.assertEqual(result.output["items"][0]["black"], "Beta")

    def test_restore_media_position_overrides_only_through_validated_fen(self):
        self.board.push_text("d4")
        self.assertNotEqual(self.board.fen(), AFTER_E4)
        result = self.execute("media.restore_position")
        self.assertTrue(result.ok)
        self.assertTrue(result.output["restored"])
        self.assertEqual(self.board.fen(), AFTER_E4)

    def test_media_controls_delegate_to_attached_provider(self):
        self.assertTrue(self.execute("media.pause").ok)
        self.assertTrue(self.execute("media.play").ok)
        self.assertTrue(
            self.execute("media.seek", {"position_ms": 2500}).ok
        )
        self.assertEqual(
            self.playback.calls,
            [("pause", None), ("play", None), ("seek", 2500)],
        )

    def test_tool_registry_exposes_expected_cross_product_capabilities(self):
        ids = {spec.tool_id for spec in self.executor.specs()}
        self.assertTrue(
            {
                "board.current",
                "board.square",
                "board.legal_moves",
                "engine.analyze",
                "library.search",
                "media.status",
                "media.restore_position",
                "media.play",
                "media.pause",
                "media.seek",
            }.issubset(ids)
        )


if __name__ == "__main__":
    unittest.main()
