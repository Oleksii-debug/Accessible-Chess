from __future__ import annotations

import asyncio
import unittest

from acs.agent_classroom_tools import AgentClassroomTools
from acs.agent_tools import ToolCall, ToolExecutor
from acs.board_service import BoardCommandService, BoardSnapshot, MoveView
from acs.chess_agent_tools import ChessAgentToolRegistry
from acs.chesscore import Board


def _board_commands(board: Board) -> BoardCommandService:
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
    return BoardCommandService(
        BoardSnapshot(tuple(board.board), board.turn, legal, attacks, None)
    )


def _execute(executor: ToolExecutor, arguments=None):
    return asyncio.run(
        executor.execute(
            ToolCall(
                call_id="call-classroom-status",
                tool_id="classroom.status",
                arguments=arguments or {},
            )
        )
    )


class AgentClassroomToolsTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {
            "teacher": {
                "board": {
                    "orientation": "white",
                    "coordinates_visible": True,
                    "permission": "select_only",
                    "engine_visibility": "visible_to_teacher",
                },
                "pieces": (
                    {"square": "e4", "piece": "P"},
                    {"square": "e5", "piece": "p"},
                ),
                "pointer": {"square": "e4"},
                "highlights": ({"square": "e4", "purpose": "target"},),
                "arrows": (),
                "mode": "teacher_explains",
                "accessible_summary": "Вказівник e4.",
                "feedback": ("Вибрав e4",),
            },
            "education": {
                "students": (
                    {"student_id": "private-student", "pseudonym": "Private"},
                ),
                "teacher_notes": ("private note",),
            },
            "product_status": {
                "teacher_session_active": True,
                "education_available": True,
                "education_recovery_required": False,
                "remote_transport": "not_approved",
            },
        }

    def test_status_uses_only_bounded_presentation_fields(self):
        executor = ToolExecutor()
        AgentClassroomTools(lambda: self.snapshot).register(executor)

        result = _execute(executor)

        self.assertTrue(result.ok, result.error)
        self.assertEqual(
            result.output,
            {
                "available": True,
                "teacherSessionActive": True,
                "educationAvailable": True,
                "educationRecoveryRequired": False,
                "remoteTransport": "not_approved",
                "teacher": {
                    "mode": "teacher_explains",
                    "boardPermission": "select_only",
                    "engineVisibility": "visible_to_teacher",
                    "accessibleSummary": "Вказівник e4.",
                    "feedback": ["Вибрав e4"],
                },
            },
        )
        rendered = repr(result.output).casefold()
        for forbidden in (
            "private-student",
            "private note",
            "pieces",
            "pointer",
            "highlights",
            "fen",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendered)

    def test_status_is_explicit_when_final_product_surface_is_unavailable(self):
        executor = ToolExecutor()
        AgentClassroomTools(lambda: {"teacher": None}).register(executor)

        result = _execute(executor)

        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.output, {"available": False})

    def test_inactive_teacher_returns_no_teacher_context(self):
        snapshot = {
            "teacher": None,
            "education": {},
            "product_status": {
                "teacher_session_active": False,
                "education_available": True,
                "education_recovery_required": False,
                "remote_transport": "not_approved",
            },
        }
        executor = ToolExecutor()
        AgentClassroomTools(lambda: snapshot).register(executor)

        result = _execute(executor)

        self.assertTrue(result.ok, result.error)
        self.assertFalse(result.output["teacherSessionActive"])
        self.assertIsNone(result.output["teacher"])

    def test_inconsistent_or_active_snapshot_values_fail_closed(self):
        class ActiveDict(dict):
            pass

        cases = (
            ActiveDict(product_status={}),
            {
                "teacher": None,
                "product_status": ActiveDict(
                    teacher_session_active=False,
                    education_available=True,
                    education_recovery_required=False,
                    remote_transport="not_approved",
                ),
            },
            {
                "teacher": {},
                "product_status": {
                    "teacher_session_active": False,
                    "education_available": True,
                    "education_recovery_required": False,
                    "remote_transport": "not_approved",
                },
            },
            {
                "teacher": {
                    "board": {
                        "permission": "locked",
                        "engine_visibility": "hidden",
                    },
                    "mode": "teacher_explains",
                    "accessible_summary": "",
                    "feedback": (object(),),
                },
                "product_status": {
                    "teacher_session_active": True,
                    "education_available": True,
                    "education_recovery_required": False,
                    "remote_transport": "not_approved",
                },
            },
        )
        for snapshot in cases:
            with self.subTest(snapshot_type=type(snapshot).__name__):
                executor = ToolExecutor()
                AgentClassroomTools(
                    lambda snapshot=snapshot: snapshot
                ).register(executor)
                result = _execute(executor)
                self.assertFalse(result.ok)
                self.assertEqual(result.error, "tool failed")

    def test_status_rejects_model_supplied_arguments(self):
        executor = ToolExecutor()
        AgentClassroomTools(lambda: self.snapshot).register(executor)

        result = _execute(executor, {"student_id": "private-student"})

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "tool failed")

    def test_registry_reuses_existing_application_snapshot_provider(self):
        board = Board()
        executor = ToolExecutor()
        ids = {
            spec.tool_id
            for spec in ChessAgentToolRegistry(
                executor=executor,
                board_provider=lambda: board,
                board_commands_provider=lambda: _board_commands(board),
                application_snapshot_provider=lambda: self.snapshot,
            ).register_all()
        }

        self.assertIn("classroom.status", ids)
        self.assertIn("books.current", ids)
        self.assertIn("training.status", ids)

        classroom = _execute(executor)
        self.assertTrue(classroom.ok, classroom.error)
        self.assertNotIn("private-student", repr(classroom.output))

    def test_output_is_detached_from_later_snapshot_mutation(self):
        executor = ToolExecutor()
        AgentClassroomTools(lambda: self.snapshot).register(executor)
        result = _execute(executor)
        self.assertTrue(result.ok, result.error)

        self.snapshot["teacher"]["feedback"] = ("changed later",)
        self.snapshot["product_status"]["remote_transport"] = "changed"

        self.assertEqual(result.output["teacher"]["feedback"], ["Вибрав e4"])
        self.assertEqual(result.output["remoteTransport"], "not_approved")


if __name__ == "__main__":
    unittest.main()
