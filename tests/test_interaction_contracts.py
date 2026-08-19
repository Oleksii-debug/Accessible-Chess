import json
import unittest

from acs.interaction_contracts import (
    AnnotationCommand,
    AnnotationOperation,
    BoardPermissionState,
    CommandFamily,
    ContractValidationError,
    EngineVisibilityPolicy,
    MoveCommand,
    PositionEditorCommand,
    PresentationState,
    SquareHighlight,
    StudentHoverEvent,
    StudentSelectionEvent,
    TeacherPointerCommand,
    TeacherPointerState,
    VisualArrow,
    interaction_from_payload,
    interaction_to_payload,
    presentation_state_from_payload,
    presentation_state_to_payload,
)


class InteractionContractTests(unittest.TestCase):
    def test_same_text_has_distinct_explicit_move_and_pointer_families(self):
        move = MoveCommand("e4")
        pointer = TeacherPointerCommand(" E4 ")
        self.assertEqual(move.family, CommandFamily.MOVE)
        self.assertEqual(pointer.family, CommandFamily.TEACHER_POINTER)
        self.assertEqual(move.raw_text, "e4")
        self.assertEqual(pointer.square, "e4")
        self.assertNotEqual(interaction_to_payload(move), interaction_to_payload(pointer))

    def test_move_text_is_preserved_for_existing_invalid_input_recovery(self):
        command = MoveCommand("  e9  ")
        self.assertEqual(command.raw_text, "  e9  ")
        self.assertEqual(interaction_from_payload(interaction_to_payload(command)), command)

    def test_position_editor_command_is_not_inferred_as_a_move(self):
        command = PositionEditorCommand("place_piece", square=" A1 ", piece="R")
        self.assertEqual(command.family, CommandFamily.POSITION_EDITOR)
        self.assertEqual(command.square, "a1")
        self.assertNotIsInstance(command, MoveCommand)

    def test_annotation_contracts_are_presentation_only_and_fail_closed(self):
        highlight = AnnotationCommand(AnnotationOperation.SET_HIGHLIGHT, start_square="E4")
        arrow = AnnotationCommand(AnnotationOperation.ADD_ARROW, start_square="e2", end_square="e4")
        clear = AnnotationCommand(AnnotationOperation.CLEAR)
        self.assertEqual(highlight.start_square, "e4")
        self.assertEqual((arrow.start_square, arrow.end_square), ("e2", "e4"))
        self.assertIsNone(clear.start_square)
        for kwargs in (
            {"operation": AnnotationOperation.SET_HIGHLIGHT},
            {"operation": AnnotationOperation.ADD_ARROW, "start_square": "e2"},
            {"operation": AnnotationOperation.ADD_ARROW, "start_square": "e2", "end_square": "e2"},
            {"operation": AnnotationOperation.CLEAR, "start_square": "e4"},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ContractValidationError):
                    AnnotationCommand(**kwargs)

    def test_hover_and_selection_are_distinct_non_move_events(self):
        hover = StudentHoverEvent("f3", piece="N", student_id="student-1", sequence=4)
        selection = StudentSelectionEvent("f3", piece="N", student_id="student-1", sequence=5)
        self.assertEqual(hover.family, CommandFamily.STUDENT_HOVER)
        self.assertEqual(selection.family, CommandFamily.STUDENT_SELECTION)
        self.assertNotIsInstance(selection, MoveCommand)
        self.assertEqual(interaction_from_payload(interaction_to_payload(hover)), hover)
        self.assertEqual(interaction_from_payload(interaction_to_payload(selection)), selection)

    def test_every_message_round_trips_through_json_safe_v1_payload(self):
        messages = (
            MoveCommand("Nf3"),
            TeacherPointerCommand("c7"),
            PositionEditorCommand("set_turn", value="b"),
            AnnotationCommand(AnnotationOperation.SET_HIGHLIGHT, start_square="d5", tag="legal"),
            AnnotationCommand(AnnotationOperation.ADD_ARROW, start_square="c3", end_square="d5"),
            StudentHoverEvent("a1", sequence=0),
            StudentSelectionEvent("h8", student_id="student-2", sequence=1),
        )
        for message in messages:
            with self.subTest(message=message):
                payload = interaction_to_payload(message)
                copied = json.loads(json.dumps(payload))
                self.assertEqual(interaction_from_payload(copied), message)

    def test_unknown_versions_families_and_fields_are_rejected(self):
        valid = interaction_to_payload(TeacherPointerCommand("e4"))
        cases = (
            {**valid, "version": 2},
            {**valid, "family": "move_or_pointer"},
            {**valid, "position": "mutate"},
        )
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(ContractValidationError):
                    interaction_from_payload(payload)

    def test_presentation_state_excludes_position_and_round_trips(self):
        state = PresentationState(
            pointer=TeacherPointerState("f3"),
            highlights=(SquareHighlight("e4", "legal_move"),),
            arrows=(VisualArrow("e2", "e4", "candidate_move"),),
            coordinate_labels_visible=False,
            student_pointer_history=(
                StudentHoverEvent("f3", student_id="student-1", sequence=1),
                StudentSelectionEvent("e5", student_id="student-1", sequence=2),
            ),
            active_student_id="student-1",
            engine_visibility=EngineVisibilityPolicy.VISIBLE_TO_TEACHER,
            board_permission=BoardPermissionState.SELECT_ONLY,
        )
        payload = presentation_state_to_payload(state)
        self.assertNotIn("position", payload)
        self.assertNotIn("fen", payload)
        self.assertNotIn("move", payload)
        copied = json.loads(json.dumps(payload))
        self.assertEqual(presentation_state_from_payload(copied), state)

    def test_presentation_history_rejects_move_commands(self):
        state_payload = presentation_state_to_payload(PresentationState())
        state_payload["student_pointer_history"] = [interaction_to_payload(MoveCommand("e4"))]
        with self.assertRaises(ContractValidationError):
            presentation_state_from_payload(state_payload)

    def test_contract_values_are_immutable(self):
        pointer = TeacherPointerCommand("e4")
        source_highlights = [SquareHighlight("e4")]
        state = PresentationState(
            pointer=TeacherPointerState("e4"),
            highlights=source_highlights,
        )
        source_highlights.append(SquareHighlight("e5"))
        self.assertEqual(state.highlights, (SquareHighlight("e4"),))
        with self.assertRaises(AttributeError):
            pointer.square = "e5"
        with self.assertRaises(AttributeError):
            state.coordinate_labels_visible = False

    def test_required_square_messages_reject_missing_targets(self):
        for constructor in (TeacherPointerCommand, StudentHoverEvent, StudentSelectionEvent):
            with self.subTest(constructor=constructor.__name__):
                with self.assertRaises(ContractValidationError):
                    constructor(None)

    def test_text_contracts_reject_non_strings_instead_of_coercing_them(self):
        constructors = (
            lambda: MoveCommand(42),
            lambda: PositionEditorCommand(False),
            lambda: PositionEditorCommand("place_piece", piece=["Q"]),
            lambda: AnnotationCommand(AnnotationOperation.CLEAR, tag={"name": "all"}),
            lambda: StudentHoverEvent("f3", student_id=17),
            lambda: SquareHighlight("e4", purpose=True),
            lambda: PresentationState(active_student_id=["student-1"]),
        )
        for constructor in constructors:
            with self.subTest(constructor=constructor):
                with self.assertRaises(ContractValidationError):
                    constructor()


if __name__ == "__main__":
    unittest.main()
