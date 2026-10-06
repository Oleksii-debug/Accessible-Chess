from __future__ import annotations

import asyncio
import unittest

from acs.acsdb import AcsDatabase
from acs.agent_tools import ToolCall, ToolExecutor
from acs.analysis_service import AnalysisService
from acs.board_service import BoardCommandService, BoardSnapshot, MoveView
from acs.chess_agent_tools import ChessAgentToolRegistry, MediaAgentBridge
from acs.chesscore import Board
from acs.media_application import (
    MediaApplicationError,
    MediaApplicationService,
)
from acs.media_core import (
    MediaChessLink,
    MediaChessSession,
    MediaCursor,
    MediaLinkStatus,
    MediaPositionTimeline,
    MediaSource,
    MediaSourceKind as CoreMediaSourceKind,
)
from acs.media_foundation import (
    MediaClock,
    MediaSessionState,
    MediaSourceKind as RuntimeMediaSourceKind,
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
    def board_commands(self):
        board = self.board
        legal = tuple(
            MoveView(
                move.frm,
                move.to,
                board.san(move),
                bool(board.board[move.to]) or move.en_passant,
            )
            for move in board.legal_moves()
        )
        attacks = {}
        for target in range(64):
            origins = tuple(board.attackers_of(target))
            if origins:
                attacks[target] = origins
        last = board.last_move
        last_view = (
            None
            if last is None
            else MoveView(last.frm, last.to)
        )
        return BoardCommandService(
            BoardSnapshot(
                tuple(board.board),
                board.turn,
                legal,
                attacks,
                last_view,
            )
        )

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
                source_kind=RuntimeMediaSourceKind.LOCAL_FILE,
                position_ms=1500,
                duration_ms=5000,
            )
        )
        self.timeline = MediaPositionTimeline(
            "media-1",
            (
                MediaChessLink(
                    "media-1",
                    0,
                    "tree:start",
                    status=MediaLinkStatus.CONFIRMED,
                    confidence=1.0,
                    evidence="agent fixture",
                ),
                MediaChessLink(
                    "media-1",
                    1000,
                    "tree:e4",
                    status=MediaLinkStatus.CONFIRMED,
                    confidence=1.0,
                    evidence="agent fixture",
                ),
            ),
        )
        self.restored_refs = []

        def restore_chess_ref(chess_ref):
            self.restored_refs.append(chess_ref)
            if chess_ref == "tree:start":
                self.board.set_fen(Board.START)
                return
            if chess_ref == "tree:e4":
                self.board.set_fen(AFTER_E4)
                return
            raise ValueError("unknown canonical fixture reference")

        self.application = MediaApplicationService(
            source=MediaSource(
                source_id="media-1",
                title="Agent media fixture",
                kind=CoreMediaSourceKind.LOCAL_FILE,
                duration_ms=5000,
            ),
            timeline=self.timeline,
            session=MediaChessSession(MediaCursor("media-1", 0)),
            restore_chess_ref=restore_chess_ref,
        )
        self.playback = FakePlayback()
        self.media = MediaAgentBridge(
            clock=self.clock,
            application=self.application,
            playback=self.playback,
        )
        self.executor = ToolExecutor()
        ChessAgentToolRegistry(
            executor=self.executor,
            board_provider=lambda: self.board,
            board_commands_provider=self.board_commands,
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

        material = self.execute("board.material")
        self.assertTrue(material.ok)
        self.assertEqual(material.output["whitePoints"], 39)
        self.assertEqual(material.output["blackPoints"], 39)
        self.assertEqual(material.output["balance"], 0)

    def test_board_semantics_do_not_fall_back_to_raw_board_provider(self):
        executor = ToolExecutor()

        def forbidden_board():
            raise AssertionError("raw Board provider must not service board semantic tools")

        ChessAgentToolRegistry(
            executor=executor,
            board_provider=forbidden_board,
            board_commands_provider=self.board_commands,
        ).register_all()

        for tool_id, arguments in (
            ("board.square", {"square": "e2"}),
            ("board.legal_moves", {}),
            ("board.material", {}),
        ):
            with self.subTest(tool_id=tool_id):
                result = asyncio.run(
                    executor.execute(
                        ToolCall(
                            call_id=f"authority-{tool_id}",
                            tool_id=tool_id,
                            arguments=arguments,
                        )
                    )
                )
                self.assertTrue(result.ok, result.error)

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

    def test_restore_media_position_delegates_opaque_canonical_reference(self):
        self.board.push_text("d4")
        self.assertNotEqual(self.board.fen(), AFTER_E4)
        result = self.execute("media.restore_position")
        self.assertTrue(result.ok, result.error)
        self.assertTrue(result.output["restored"])
        self.assertEqual(result.output["chessRef"], "tree:e4")
        self.assertNotIn("fen", result.output)
        self.assertNotIn("treePath", result.output)
        self.assertEqual(self.restored_refs, ["tree:e4"])
        self.assertEqual(self.board.fen(), AFTER_E4)

    def test_media_status_exposes_reference_not_parallel_fen_authority(self):
        result = self.execute("media.status")
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.output["synchronizedChessRef"], "tree:e4")
        self.assertEqual(result.output["synchronizedAnchorMs"], 1000)
        self.assertEqual(result.output["qualification"], "confirmed")
        self.assertFalse(result.output["synchronizationAmbiguous"])
        self.assertNotIn("synchronizedFen", result.output)
        self.assertNotIn("synchronizedTreePath", result.output)

    def test_ambiguous_media_position_fails_before_restore_callback(self):
        timeline = MediaPositionTimeline(
            "media-1",
            (
                MediaChessLink(
                    "media-1",
                    1000,
                    "tree:e4",
                    status=MediaLinkStatus.CONFIRMED,
                    confidence=1.0,
                ),
                MediaChessLink(
                    "media-1",
                    1000,
                    "tree:d4",
                    status=MediaLinkStatus.CONFIRMED,
                    confidence=1.0,
                ),
            ),
        )
        application = MediaApplicationService(
            source=MediaSource(
                source_id="media-1",
                title="Ambiguous Agent media fixture",
                kind=CoreMediaSourceKind.LOCAL_FILE,
                duration_ms=5000,
            ),
            timeline=timeline,
            session=MediaChessSession(MediaCursor("media-1", 0)),
            restore_chess_ref=lambda chess_ref: self.restored_refs.append(chess_ref),
        )
        bridge = MediaAgentBridge(
            clock=self.clock,
            application=application,
        )
        with self.assertRaises(MediaApplicationError):
            bridge.restore()
        self.assertEqual(self.restored_refs, [])

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
                "board.material",
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
