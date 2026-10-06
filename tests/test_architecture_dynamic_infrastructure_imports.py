from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ACS = ROOT / "acs"
PROTECTED_MODULES = (
    "chesscore.py",
    "gametree.py",
    "bookdocument.py",
    "history.py",
)

# Issue #7 explicitly requires these authorities to remain independent from
# concrete UI/storage/engine/proprietary-format implementation details.
FORBIDDEN_PREFIXES = (
    "sqlite3",
    "webview",
    "pywebview",
    "acs.acsdb",
    "acs.stockfish",
    "acs.stockfish_runtime",
    "acs.chessbase",
    "acs.chessbase_",
)


def _literal_dynamic_imports(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        dynamic = isinstance(node.func, ast.Name) and node.func.id == "__import__"
        importlib_call = (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "import_module"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "importlib"
        )
        if not (dynamic or importlib_call):
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.append((node.lineno, first.value))
    return found


def _forbidden(target: str) -> bool:
    for prefix in FORBIDDEN_PREFIXES:
        if prefix.endswith("_"):
            if target.startswith(prefix):
                return True
        elif target == prefix or target.startswith(prefix + "."):
            return True
    return False


class ArchitectureDynamicInfrastructureBoundaryTests(unittest.TestCase):
    def test_core_authorities_do_not_dynamically_reach_concrete_infrastructure(self) -> None:
        violations: list[str] = []
        for filename in PROTECTED_MODULES:
            path = ACS / filename
            self.assertTrue(path.is_file(), f"protected module disappeared: {filename}")
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for lineno, target in _literal_dynamic_imports(tree):
                if _forbidden(target):
                    violations.append(f"{path.relative_to(ROOT)}:{lineno}: {target}")

        self.assertFalse(
            violations,
            "Concrete infrastructure dependency entered protected core through a dynamic import:\n"
            + "\n".join(sorted(violations)),
        )

    def test_forbidden_prefix_classifier_is_fail_closed_for_owned_families(self) -> None:
        self.assertTrue(_forbidden("sqlite3"))
        self.assertTrue(_forbidden("webview"))
        self.assertTrue(_forbidden("acs.stockfish_runtime"))
        self.assertTrue(_forbidden("acs.stockfish.provider"))
        self.assertTrue(_forbidden("acs.chessbase_import"))
        self.assertTrue(_forbidden("acs.chessbase.reader"))
        self.assertFalse(_forbidden("acs.engine_contracts"))
        self.assertFalse(_forbidden("third_party_plugin_name"))


if __name__ == "__main__":
    unittest.main()
