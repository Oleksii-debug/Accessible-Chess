from __future__ import annotations

import ast
from pathlib import Path
import unittest

from acs.agent_model_contracts import ProviderKind
from acs.agent_ollama_provider import OllamaProvider


ROOT = Path(__file__).resolve().parents[1]
GENERIC_AGENT_MODULES = (
    "acs/universal_chess_agent.py",
    "acs/agent_tools.py",
    "acs/agent_model_gateway.py",
    "acs/agent_checkpoint.py",
    "acs/agent_retry.py",
    "acs/agent_task_state.py",
    "acs/agent_verification.py",
)


class Section21ArchitectureTests(unittest.TestCase):
    def test_generic_agent_runtime_owns_no_chess_rules_or_engine_authority(self):
        forbidden = (
            "acs.chesscore",
            "acs.board_service",
            "acs.analysis_service",
            "acs.pgn",
            "acs.gametree",
            "acs.stockfish",
        )
        for relative in GENERIC_AGENT_MODULES:
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
            imported = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                    if node.level:
                        module = "acs." + module
                    imported.append(module)
            with self.subTest(relative=relative):
                self.assertFalse(
                    any(
                        name == prefix or name.startswith(prefix + ".")
                        for name in imported
                        for prefix in forbidden
                    ),
                    imported,
                )

    def test_provider_abstraction_explicitly_allows_no_llm_local_and_cloud(self):
        self.assertEqual(
            {kind.value for kind in ProviderKind},
            {"no_llm", "local", "cloud"},
        )

    def test_local_ollama_defaults_match_product_contract(self):
        provider = OllamaProvider()
        self.assertEqual(provider.capabilities.provider_id, "ollama")
        self.assertIs(provider.capabilities.kind, ProviderKind.LOCAL)
        self.assertTrue(provider.capabilities.supports_private_data)
        self.assertFalse(provider.capabilities.supports_hard_cancellation)


if __name__ == "__main__":
    unittest.main()
