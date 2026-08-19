from __future__ import annotations

import json
from pathlib import Path
import unittest

from acs.interaction_contracts import (
    CommandFamily,
    ContractValidationError,
    interaction_from_payload,
    interaction_to_payload,
    presentation_state_from_payload,
    presentation_state_to_payload,
)


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
        cls.message_fixture = load_json(FIXTURES / "messages.json")
        cls.presentation_fixture = load_json(FIXTURES / "presentation-state.json")
        cls.invalid_messages = load_json(FIXTURES / "invalid-messages.json")
        cls.invalid_presentations = load_json(FIXTURES / "invalid-presentation-states.json")

    def test_schemas_are_versioned_json_schema_2020_12_documents(self):
        for schema in (self.interaction_schema, self.presentation_schema):
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

    def test_negative_conformance_fixtures_fail_closed_in_runtime_readers(self):
        for case in self.invalid_messages["cases"]:
            with self.subTest(kind="interaction", name=case["name"]):
                with self.assertRaises(ContractValidationError):
                    interaction_from_payload(case["payload"])
        for case in self.invalid_presentations["cases"]:
            with self.subTest(kind="presentation", name=case["name"]):
                with self.assertRaises(ContractValidationError):
                    presentation_state_from_payload(case["payload"])

    def test_negative_conformance_fixtures_are_rejected_by_json_schema(self):
        try:
            from jsonschema import Draft202012Validator
            from referencing import Registry, Resource
        except ImportError:
            self.skipTest("jsonschema is not installed in this test environment")

        interaction_validator = Draft202012Validator(self.interaction_schema)
        registry = Registry().with_resource(
            self.interaction_schema["$id"],
            Resource.from_contents(self.interaction_schema),
        )
        presentation_validator = Draft202012Validator(
            self.presentation_schema,
            registry=registry,
        )
        for case in self.invalid_messages["cases"]:
            with self.subTest(kind="interaction", name=case["name"]):
                self.assertFalse(interaction_validator.is_valid(case["payload"]))
        for case in self.invalid_presentations["cases"]:
            with self.subTest(kind="presentation", name=case["name"]):
                self.assertFalse(presentation_validator.is_valid(case["payload"]))

    def test_negative_fixture_names_are_unique_and_versioned(self):
        for fixture in (self.invalid_messages, self.invalid_presentations):
            self.assertEqual(fixture["schema_version"], 1)
            names = [case["name"] for case in fixture["cases"]]
            self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
