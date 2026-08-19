import unittest

from acs.interaction_contracts import (
    AnnotationCommand,
    AnnotationOperation,
    BoardPermissionState,
    ContractValidationError,
    MoveCommand,
    PositionEditorCommand,
    StudentHoverEvent,
    StudentSelectionEvent,
    TeacherPointerCommand,
)
from acs.interaction_router import (
    InputSource,
    InteractionEffect,
    InteractionPolicy,
    InteractionRequest,
    RoutingDecision,
    evaluate_interaction,
    evaluate_request,
    route_text_command,
    routing_decision_from_payload,
    routing_decision_to_payload,
    routing_request_from_payload,
    routing_request_to_payload,
)


class InteractionRouterTests(unittest.TestCase):
    def test_e4_routes_by_explicit_active_source_not_text_guessing(self):
        move = route_text_command(InputSource.MOVE_INPUT, "e4")
        pointer = route_text_command(InputSource.TEACHER_POINTER_EDITOR, "e4")
        self.assertIsInstance(move, MoveCommand)
        self.assertIsInstance(pointer, TeacherPointerCommand)
        self.assertTrue(evaluate_interaction(move, InputSource.MOVE_INPUT).can_create_move)
        pointer_decision = evaluate_interaction(pointer, InputSource.TEACHER_POINTER_EDITOR)
        self.assertEqual(pointer_decision.effect, InteractionEffect.PRESENTATION)
        self.assertFalse(pointer_decision.can_mutate_position)

    def test_text_only_router_rejects_structured_or_ambiguous_sources(self):
        for source in (
            InputSource.POSITION_EDITOR,
            InputSource.ANNOTATION_EDITOR,
            InputSource.STUDENT_SURFACE,
        ):
            with self.subTest(source=source):
                with self.assertRaises(ContractValidationError):
                    route_text_command(source, "e4")

    def test_cross_family_messages_are_rejected_without_side_effect_authority(self):
        cases = (
            (TeacherPointerCommand("e4"), InputSource.MOVE_INPUT),
            (MoveCommand("e4"), InputSource.TEACHER_POINTER_EDITOR),
            (AnnotationCommand(AnnotationOperation.CLEAR), InputSource.POSITION_EDITOR),
            (PositionEditorCommand("clear"), InputSource.ANNOTATION_EDITOR),
        )
        for message, source in cases:
            with self.subTest(message=message, source=source):
                decision = evaluate_interaction(message, source)
                self.assertFalse(decision.accepted)
                self.assertEqual(decision.effect, InteractionEffect.NONE)
                self.assertFalse(decision.can_mutate_position)

    def test_position_editor_is_explicit_mutation_but_never_a_chess_move(self):
        decision = evaluate_interaction(
            PositionEditorCommand("place_piece", square="e4", piece="Q"),
            InputSource.POSITION_EDITOR,
        )
        self.assertTrue(decision.accepted)
        self.assertTrue(decision.can_mutate_position)
        self.assertFalse(decision.can_create_move)
        self.assertEqual(decision.effect, InteractionEffect.POSITION_EDIT)

    def test_annotation_is_presentation_only(self):
        decision = evaluate_interaction(
            AnnotationCommand(AnnotationOperation.ADD_ARROW, start_square="e2", end_square="e4"),
            InputSource.ANNOTATION_EDITOR,
        )
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.effect, InteractionEffect.PRESENTATION)
        self.assertFalse(decision.can_mutate_position)

    def test_student_hover_and_selection_never_become_moves_implicitly(self):
        policies = (
            BoardPermissionState.LOCKED,
            BoardPermissionState.SELECT_ONLY,
            BoardPermissionState.MOVE_ALLOWED,
        )
        events = (StudentHoverEvent("f3"), StudentSelectionEvent("e4"))
        for permission in policies:
            for event in events:
                with self.subTest(permission=permission, event=event):
                    decision = evaluate_interaction(
                        event,
                        InputSource.STUDENT_SURFACE,
                        InteractionPolicy(permission),
                    )
                    self.assertTrue(decision.accepted)
                    self.assertEqual(decision.effect, InteractionEffect.OBSERVATION)
                    self.assertFalse(decision.can_mutate_position)

    def test_student_move_requires_both_explicit_move_command_and_permission(self):
        command = MoveCommand("e4")
        for permission in (BoardPermissionState.LOCKED, BoardPermissionState.SELECT_ONLY):
            with self.subTest(permission=permission):
                decision = evaluate_interaction(
                    command,
                    InputSource.STUDENT_SURFACE,
                    InteractionPolicy(permission),
                )
                self.assertFalse(decision.accepted)
                self.assertFalse(decision.can_create_move)
        allowed = evaluate_interaction(
            command,
            InputSource.STUDENT_SURFACE,
            InteractionPolicy(BoardPermissionState.MOVE_ALLOWED),
        )
        self.assertTrue(allowed.can_create_move)
        self.assertEqual(allowed.effect, InteractionEffect.CHESS_MOVE)

    def test_routing_decision_cannot_claim_effect_for_rejected_message(self):
        with self.assertRaises(ContractValidationError):
            RoutingDecision(False, InteractionEffect.CHESS_MOVE, "invalid")

    def test_unknown_source_fails_closed(self):
        decision = evaluate_interaction(MoveCommand("e4"), "unknown")
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.effect, InteractionEffect.NONE)

    def test_versioned_request_and_decision_payloads_round_trip(self):
        request = InteractionRequest(
            InputSource.STUDENT_SURFACE,
            MoveCommand("e4"),
            InteractionPolicy(BoardPermissionState.MOVE_ALLOWED),
        )
        restored = routing_request_from_payload(routing_request_to_payload(request))
        self.assertEqual(restored, request)
        decision = evaluate_request(restored)
        self.assertTrue(decision.can_create_move)
        self.assertEqual(
            routing_decision_from_payload(routing_decision_to_payload(decision)),
            decision,
        )

    def test_falsey_non_policy_is_rejected_instead_of_becoming_default(self):
        for policy in (False, 0, "", (), []):
            with self.subTest(policy=policy):
                with self.assertRaises(ContractValidationError):
                    evaluate_interaction(MoveCommand("e4"), InputSource.MOVE_INPUT, policy)

    def test_wire_decision_rejects_non_text_reason(self):
        with self.assertRaises(ContractValidationError):
            routing_decision_from_payload(
                {
                    "version": 1,
                    "kind": "decision",
                    "accepted": True,
                    "effect": "presentation",
                    "reason": ["pointer"],
                }
            )


if __name__ == "__main__":
    unittest.main()
