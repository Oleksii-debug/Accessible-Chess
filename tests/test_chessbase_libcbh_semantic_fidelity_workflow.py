from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "chessbase-libcbh-semantic-fidelity-current.yml"
BRIDGE = ROOT / "tools" / "optional" / "libcbh_json_bridge.cpp"
ORACLE = ROOT / "tests" / "test_chessbase_libcbh_external_fixture.py"


class ChessBaseLibcbhSemanticFidelityWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.bridge = BRIDGE.read_text(encoding="utf-8")
        cls.oracle = ORACLE.read_text(encoding="utf-8")

    def test_real_gate_is_pinned_to_exact_libcbh_evidence_commit(self) -> None:
        commit = "9641c5c3949d8fb210b17dd9aa54455645843696"
        self.assertIn(f"LIBCBH_COMMIT: {commit}", self.workflow)
        self.assertIn("repository: rolandlo/libcbh", self.workflow)
        self.assertIn("LIBCBH_ANNOTATION_FIXTURE_DIR", self.workflow)
        self.assertIn("gtest/Annotation", self.workflow)
        self.assertIn("gtest/WithVariations", self.workflow)

    def test_bridge_normalizes_only_fixture_qualified_pinned_commit(self) -> None:
        for token in (
            "PINNED_LIBCBH_NAG_COMMIT",
            "std::string_view(LIBCBH_SOURCE_COMMIT) != PINNED_LIBCBH_NAG_COMMIT",
            "case 10: return 11;",
            "case 33: return 32;",
            "case 37: return 36;",
            "case 41: return 40;",
            "case 45: return 44;",
            "case 133: return 132;",
            "case 136:",
            "case 137:",
            "return 138;",
            "default:",
            "return static_cast<unsigned int>(value);",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.bridge)
        self.assertIn("canonical_evaluation_nag(value.evaluation)", self.bridge)

    def test_real_oracle_compares_recursive_nags_with_independent_export(self) -> None:
        for token in (
            "TestBase.cbh",
            "TestBaseExport.pgn",
            "_nag_line_signature",
            "tuple(move.nags)",
            "decoded_signatures",
            "reference_signatures",
            '{"$11", "$32", "$40", "$132", "$138"}',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.oracle)

    def test_gate_builds_external_backend_without_shipping_it(self) -> None:
        build = self.workflow.index("Build current Accessible Chess bridge")
        oracle = self.workflow.index("Run pinned variation and annotation semantic oracles")
        boundary = self.workflow.index("Verify mapping scope and default-package boundary")
        self.assertLess(build, oracle)
        self.assertLess(oracle, boundary)
        self.assertIn("test ! -e libcbh-json-bridge", self.workflow)
        self.assertIn("test ! -e libcbh.so", self.workflow)
        self.assertIn("git status --porcelain --untracked-files=no", self.workflow)


if __name__ == "__main__":
    unittest.main()
