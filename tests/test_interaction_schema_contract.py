from __future__ import annotations

import json
from pathlib import Path
import unittest

from acs.interaction_contracts import (
    CommandFamily,
    ContractValidationError,
    PositionEditorOperation,
    interaction_from_payload,
    interaction_to_payload,
    presentation_state_from_payload,
    presentation_state_to_payload,
)
from acs.interaction_router import (
    InputSource,
    InteractionEffect,
    evaluate_request,
    routing_decision_from_payload,
    routing_decision_to_payload,
    routing_request_from_payload,
    routing_request_to_payload,
)
from acs.squares import iter_square_names


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
FIXTURES = ROOT / "tests" / "fixtures" / "interaction_contracts" / "v1"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class InteractionSchemaContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.interaction_schema = load_json(SCHEMAS / "interaction-message-v1.schema.json")
        cls.presentation_schema = load_json(SCHEMAS / "presentation-state-v1.schema.json")
        cls.routing_schema = load_json(SCHEMAS / "interaction-routing-v1.schema.json")
        cls.distinct_square_pair_schema = load_json(
            SCHEMAS / "distinct-square-pair-v1.schema.json"
        )
        cls.message_fixture = load_json(FIXTURES / "messages.json")
        cls.presentation_fixture = load_json(FIXTURES / "presentation-state.json")
        cls.routing_fixture = load_json(FIXTURES / "routing.json")
        cls.invalid_messages = load_json(FIXTURES / "invalid-messages.json")
        cls.invalid_presentations = load_json(FIXTURES / "invalid-presentation-states.json")
        cls.invalid_routing = load_json(FIXTURES / "invalid-routing.json")

    def test_schemas_are_versioned_json_schema_2020_12_documents(self):
        for schema in (
            self.interaction_schema,
            self.presentation_schema,
            self.routing_schema,
            self.distinct_square_pair_schema,
        ):
            with self.subTest(title=schema["title"]):
                self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertTrue(schema["$id"].endswith("v1.schema.json"))

    def test_interaction_schema_exposes_every_runtime_family_once(self):
        refs = [item["$ref"] for item in self.interaction_schema["oneOf"]]
        self.assertEqual(
            refs,
            [
                "#/$defs/move",
                "#/$defs/teacherPointer",
                "#/$defs/positionEditor",
                "#/$defs/annotation",
                "#/$defs/studentHover",
                "#/$defs/studentSelection",
            ],
        )
        fixture_families = {item["family"] for item in self.message_fixture["messages"]}
        self.assertEqual(fixture_families, {family.value for family in CommandFamily})

    def test_position_editor_schema_operations_match_runtime_exactly(self):
        operations = self.interaction_schema["$defs"]["positionEditor"]["properties"][
            "operation"
        ]["enum"]
        self.assertEqual(operations, [operation.value for operation in PositionEditorOperation])

    def test_distinct_square_pair_schema_covers_all_and_only_same_square_pairs(self):
        exclusions = self.distinct_square_pair_schema["not"]["anyOf"]
        actual = {
            (
                item["properties"]["start_square"]["const"],
                item["properties"]["end_square"]["const"],
            )
            for item in exclusions
        }
        expected = {(square, square) for square in iter_square_names()}
        self.assertEqual(actual, expected)
        self.assertEqual(len(exclusions), 64)
        self.assertEqual(
            self.interaction_schema["$defs"]["arrowAnnotation"]["allOf"],
            [{"$ref": "distinct-square-pair-v1.schema.json"}],
        )
        self.assertEqual(
            self.presentation_schema["$defs"]["arrow"]["allOf"],
            [{"$ref": "distinct-square-pair-v1.schema.json"}],
        )

    def test_golden_messages_round_trip_without_loss_or_family_guessing(self):
        for payload in self.message_fixture["messages"]:
            with self.subTest(family=payload["family"], operation=payload.get("operation")):
                message = interaction_from_payload(payload)
                self.assertEqual(interaction_to_payload(message), payload)
                self.assertEqual(json.loads(json.dumps(payload)), payload)

    def test_golden_message_keys_match_fail_closed_schema_shapes(self):
        definitions = self.interaction_schema["$defs"]
        family_definition = {
            "move": "move",
            "teacher_pointer": "teacherPointer",
            "position_editor": "positionEditor",
            "student_hover": "studentHover",
            "student_selection": "studentSelection",
        }
        annotation_definition = {
            "set_highlight": "highlightAnnotation",
            "add_arrow": "arrowAnnotation",
            "clear": "clearAnnotation",
        }
        for payload in self.message_fixture["messages"]:
            name = (
                annotation_definition[payload["operation"]]
                if payload["family"] == "annotation"
                else family_definition[payload["family"]]
            )
            definition = definitions[name]
            with self.subTest(definition=name):
                self.assertFalse(definition["additionalProperties"])
                self.assertEqual(set(definition["required"]), set(payload))
                self.assertEqual(definition["properties"]["family"]["const"], payload["family"])

    def test_presentation_fixture_round_trips_and_contains_no_chess_state(self):
        state = presentation_state_from_payload(self.presentation_fixture)
        self.assertEqual(presentation_state_to_payload(state), self.presentation_fixture)
        serialized = json.dumps(self.presentation_fixture, sort_keys=True).lower()
        for forbidden in ('"position"', '"fen"', '"legal_moves"', '"move_history"'):
            self.assertNotIn(forbidden, serialized)

    def test_presentation_schema_and_fixture_have_the_same_closed_topology(self):
        self.assertFalse(self.presentation_schema["additionalProperties"])
        self.assertEqual(set(self.presentation_schema["required"]), set(self.presentation_fixture))
        history_refs = self.presentation_schema["properties"]["student_pointer_history"]["items"]["oneOf"]
        self.assertEqual(
            [item["$ref"] for item in history_refs],
            [
                "interaction-message-v1.schema.json#/$defs/studentHover",
                "interaction-message-v1.schema.json#/$defs/studentSelection",
            ],
        )

    def test_schema_policy_values_match_golden_payload(self):
        properties = self.presentation_schema["properties"]
        self.assertIn(self.presentation_fixture["engine_visibility"], properties["engine_visibility"]["enum"])
        self.assertIn(self.presentation_fixture["board_permission"], properties["board_permission"]["enum"])

    def test_routing_fixture_round_trips_and_matches_canonical_decisions(self):
        for case in self.routing_fixture["cases"]:
            with self.subTest(name=case["name"]):
                request = routing_request_from_payload(case["request"])
                self.assertEqual(routing_request_to_payload(request), case["request"])
                expected = routing_decision_from_payload(case["decision"])
                self.assertEqual(evaluate_request(request), expected)
                self.assertEqual(routing_decision_to_payload(expected), case["decision"])

    def test_routing_schema_enums_match_runtime_values(self):
        request = self.routing_schema["$defs"]["request"]
        decision = self.routing_schema["$defs"]["decision"]
        self.assertEqual(
            set(request["properties"]["source"]["enum"]),
            {source.value for source in InputSource},
        )
        self.assertEqual(
            set(decision["properties"]["effect"]["enum"]),
            {effect.value for effect in InteractionEffect},
        )

    def test_negative_conformance_fixtures_fail_closed_in_runtime_readers(self):
        for case in self.invalid_messages["cases"]:
            with self.subTest(kind="interaction", name=case["name"]):
                with self.assertRaises(ContractValidationError):
                    interaction_from_payload(case["payload"])
        for case in self.invalid_presentations["cases"]:
            with self.subTest(kind="presentation", name=case["name"]):
                with self.assertRaises(ContractValidationError):
                    presentation_state_from_payload(case["payload"])
        for case in self.invalid_routing["cases"]:
            with self.subTest(kind="routing", name=case["name"]):
                reader = (
                    routing_request_from_payload
                    if case["payload"].get("kind") == "request"
                    else routing_decision_from_payload
                )
                with self.assertRaises(ContractValidationError):
                    reader(case["payload"])

    def test_json_schema_accepts_positive_and_rejects_negative_conformance_fixtures(self):
        try:
            from jsonschema import Draft202012Validator
            from referencing import Registry, Resource
        except ImportError:
            self.skipTest("jsonschema is not installed in this test environment")

        for schema in (
            self.distinct_square_pair_schema,
            self.interaction_schema,
            self.presentation_schema,
            self.routing_schema,
        ):
            Draft202012Validator.check_schema(schema)
        registry = Registry()
        for schema in (self.distinct_square_pair_schema, self.interaction_schema):
            registry = registry.with_resource(
                schema["$id"],
                Resource.from_contents(schema),
            )
        interaction_validator = Draft202012Validator(
            self.interaction_schema,
            registry=registry,
        )
        presentation_validator = Draft202012Validator(
            self.presentation_schema,
            registry=registry,
        )
        routing_validator = Draft202012Validator(
            self.routing_schema,
            registry=registry,
        )
        for payload in self.message_fixture["messages"]:
            with self.subTest(kind="positive-interaction", family=payload["family"]):
                self.assertTrue(interaction_validator.is_valid(payload))
        self.assertTrue(presentation_validator.is_valid(self.presentation_fixture))
        for case in self.routing_fixture["cases"]:
            with self.subTest(kind="positive-routing", name=case["name"]):
                self.assertTrue(routing_validator.is_valid(case["request"]))
                self.assertTrue(routing_validator.is_valid(case["decision"]))
        for case in self.invalid_messages["cases"]:
            with self.subTest(kind="interaction", name=case["name"]):
                self.assertFalse(interaction_validator.is_valid(case["payload"]))
        for case in self.invalid_presentations["cases"]:
            with self.subTest(kind="presentation", name=case["name"]):
                self.assertFalse(presentation_validator.is_valid(case["payload"]))
        for case in self.invalid_routing["cases"]:
            with self.subTest(kind="routing", name=case["name"]):
                self.assertFalse(routing_validator.is_valid(case["payload"]))
        for square in iter_square_names():
            annotation = {
                "version": 1,
                "family": "annotation",
                "operation": "add_arrow",
                "start_square": square,
                "end_square": square,
                "tag": None,
            }
            presentation = {
                **self.presentation_fixture,
                "arrows": [
                    {
                        "start_square": square,
                        "end_square": square,
                        "purpose": "candidate_move",
                    }
                ],
            }
            with self.subTest(kind="same-square-interaction", square=square):
                self.assertFalse(interaction_validator.is_valid(annotation))
            with self.subTest(kind="same-square-presentation", square=square):
                self.assertFalse(presentation_validator.is_valid(presentation))

    def test_negative_fixture_names_are_unique_and_versioned(self):
        for fixture in (self.invalid_messages, self.invalid_presentations, self.invalid_routing):
            self.assertEqual(fixture["schema_version"], 1)
            names = [case["name"] for case in fixture["cases"]]
            self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
