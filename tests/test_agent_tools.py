import unittest

from acs.agent_tools import (
    AgentToolArgument,
    AgentToolConfirmationRequired,
    AgentToolError,
    AgentToolRegistry,
    AgentToolResult,
    AgentToolRisk,
    AgentToolSpec,
    DuplicateAgentToolError,
    InvalidAgentToolArguments,
    MissingAgentCapabilityError,
    UnknownAgentToolError,
    register_board_read_tools,
)
from acs.board_service import BoardCommandService, BoardSnapshot, EngineSnapshot, MoveView
from acs.squares import parse_square


class AgentToolRegistryTests(unittest.TestCase):
    def read_tool(self, **overrides):
        values = {
            "name": "test.read",
            "description": "Read a value.",
            "handler": lambda: AgentToolResult("ready", {"ready": True}),
        }
        values.update(overrides)
        return AgentToolSpec(**values)

    def test_registry_rejects_duplicate_and_unknown_tools(self):
        registry = AgentToolRegistry()
        registry.register(self.read_tool())
        with self.assertRaises(DuplicateAgentToolError):
            registry.register(self.read_tool())
        with self.assertRaises(UnknownAgentToolError):
            registry.invoke("missing")
        with self.assertRaises(UnknownAgentToolError):
            registry.invoke(1)

    def test_arguments_are_validated_before_handler_runs(self):
        calls = []

        def handler(square):
            calls.append(square)
            return AgentToolResult("ok", {"square": square})

        registry = AgentToolRegistry()
        registry.register(
            AgentToolSpec(
                "board.square",
                "Read a square.",
                handler,
                (AgentToolArgument("square", (str, int)),),
            )
        )
        for arguments in (
            {},
            {"square": True},
            {"square": None},
            {"square": "e4", "extra": 1},
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(InvalidAgentToolArguments):
                    registry.invoke("board.square", arguments)
        self.assertEqual(calls, [])
        self.assertEqual(registry.invoke("board.square", {"square": "e4"}).data["square"], "e4")
        self.assertEqual(calls, ["e4"])

    def test_capability_gate_precedes_execution(self):
        calls = []

        def handler():
            calls.append(True)
            return AgentToolResult("ok")

        registry = AgentToolRegistry()
        registry.register(
            AgentToolSpec(
                "library.search",
                "Search the canonical library.",
                handler,
                required_capabilities=frozenset({"library.read"}),
            )
        )
        with self.assertRaises(MissingAgentCapabilityError):
            registry.invoke("library.search")
        self.assertEqual(calls, [])
        registry.invoke("library.search", capabilities=frozenset({"library.read"}))
        self.assertEqual(calls, [True])

    def test_mutating_and_destructive_tools_require_explicit_confirmation(self):
        for risk in (AgentToolRisk.MUTATING, AgentToolRisk.DESTRUCTIVE):
            calls = []
            registry = AgentToolRegistry()
            registry.register(
                AgentToolSpec(
                    "game.save",
                    "Save game state.",
                    lambda: calls.append(True) or AgentToolResult("saved"),
                    risk=risk,
                )
            )
            with self.subTest(risk=risk):
                with self.assertRaises(AgentToolConfirmationRequired):
                    registry.invoke("game.save")
                self.assertEqual(calls, [])
                registry.invoke("game.save", confirmed=True)
                self.assertEqual(calls, [True])

    def test_read_only_tools_never_need_confirmation(self):
        registry = AgentToolRegistry()
        registry.register(self.read_tool())
        self.assertEqual(registry.invoke("test.read").text, "ready")

    def test_registry_rejects_invalid_handler_result(self):
        registry = AgentToolRegistry()
        registry.register(
            AgentToolSpec("test.bad", "Bad result.", lambda: "not a result")
        )
        with self.assertRaises(AgentToolError):
            registry.invoke("test.bad")

    def test_schemas_are_deterministic_and_do_not_expose_handlers(self):
        registry = AgentToolRegistry()
        registry.register(self.read_tool(name="z.read"))
        registry.register(
            self.read_tool(
                name="a.read",
                arguments=(AgentToolArgument("square", (str, int), description="Square."),),
                required_capabilities=frozenset({"z", "a"}),
            )
        )
        schemas = registry.schemas()
        self.assertEqual([schema["name"] for schema in schemas], ["a.read", "z.read"])
        self.assertEqual(schemas[0]["required_capabilities"], ("a", "z"))
        self.assertEqual(schemas[0]["arguments"][0]["types"], ("str", "int"))
        self.assertNotIn("handler", schemas[0])
        with self.assertRaises(TypeError):
            schemas[0]["name"] = "changed"

    def test_spec_and_argument_shapes_fail_closed(self):
        with self.assertRaises(ValueError):
            AgentToolArgument("", (str,))
        with self.assertRaises(TypeError):
            AgentToolArgument("square", ())
        with self.assertRaises(TypeError):
            AgentToolArgument("square", ("str",))
        with self.assertRaises(ValueError):
            self.read_tool(name="Board Read")
        with self.assertRaises(ValueError):
            self.read_tool(
                arguments=(
                    AgentToolArgument("square", (str,)),
                    AgentToolArgument("square", (str,)),
                )
            )
        with self.assertRaises(TypeError):
            AgentToolResult("ok", {"value": 1}).data["value"] = 2


class BoardAgentToolsTests(unittest.TestCase):
    def sample(self):
        pieces = [None] * 64
        pieces[parse_square("e4")] = "P"
        pieces[parse_square("d5")] = "p"
        legal = (
            MoveView(parse_square("e4"), parse_square("e5"), "e5"),
            MoveView(parse_square("e4"), parse_square("d5"), "exd5", True),
        )
        return BoardCommandService(
            BoardSnapshot(tuple(pieces), "w", legal),
            engine=EngineSnapshot("+0.42", "Nf3"),
        )

    def registry(self):
        registry = AgentToolRegistry()
        register_board_read_tools(registry, self.sample())
        return registry

    def invoke(self, registry, name, arguments=None):
        return registry.invoke(
            name,
            arguments,
            capabilities=frozenset({"board.read"}),
        )

    def test_board_tools_are_read_only_and_deterministically_discoverable(self):
        registry = self.registry()
        schemas = registry.schemas()
        self.assertEqual(
            [item["name"] for item in schemas],
            [
                "board.best_move",
                "board.current",
                "board.evaluation",
                "board.legal_moves",
                "board.material",
            ],
        )
        self.assertTrue(all(item["risk"] == "read_only" for item in schemas))
        self.assertTrue(all(item["required_capabilities"] == ("board.read",) for item in schemas))

    def test_board_current_delegates_to_canonical_board_service(self):
        registry = self.registry()
        result = self.invoke(registry, "board.current", {"square": "e4"})
        self.assertEqual(result.text, "e4: P")
        self.assertEqual(dict(result.data), {"square": "e4", "piece": "P"})
        empty = self.invoke(registry, "board.current", {"square": "a1"})
        self.assertEqual(empty.text, "a1: empty")

    def test_legal_moves_are_serialized_from_canonical_service_only(self):
        registry = self.registry()
        result = self.invoke(registry, "board.legal_moves", {"square": "e4"})
        self.assertEqual(result.text, "Legal moves from e4: e5, exd5")
        self.assertEqual([move["san"] for move in result.data["moves"]], ["e5", "exd5"])
        self.assertEqual(result.data["moves"][1]["is_capture"], True)
        no_moves = self.invoke(registry, "board.legal_moves", {"square": "a1"})
        self.assertEqual(no_moves.text, "Legal moves from a1: none")

    def test_material_and_engine_snapshot_tools_preserve_authoritative_values(self):
        registry = self.registry()
        material = self.invoke(registry, "board.material")
        self.assertEqual(material.data["white_points"], 1)
        self.assertEqual(material.data["black_points"], 1)
        self.assertEqual(material.data["balance"], 0)
        self.assertEqual(self.invoke(registry, "board.evaluation").data["evaluation"], "+0.42")
        self.assertEqual(self.invoke(registry, "board.best_move").data["best_move"], "Nf3")

    def test_board_capability_is_mandatory_and_bad_square_never_mutates_state(self):
        registry = self.registry()
        with self.assertRaises(MissingAgentCapabilityError):
            registry.invoke("board.current", {"square": "e4"})
        with self.assertRaises(ValueError):
            self.invoke(registry, "board.current", {"square": "z9"})
        self.assertEqual(self.invoke(registry, "board.current", {"square": "e4"}).data["piece"], "P")

    def test_board_registration_rejects_parallel_noncanonical_service(self):
        registry = AgentToolRegistry()
        with self.assertRaises(TypeError):
            register_board_read_tools(registry, object())
        with self.assertRaises(ValueError):
            register_board_read_tools(registry, self.sample(), capability="")


if __name__ == "__main__":
    unittest.main()
