from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ACS = ROOT / "acs"
PROTECTED_MODULES = ("chesscore.py", "gametree.py", "bookdocument.py", "history.py")
FORBIDDEN_PREFIXES = (
    "acs.webapp",
    "acs.ui_",
    "acs.full_product_ui",
    "acs.library_webview",
    "acs.book_webview",
    "acs.training_webview",
    "acs.classroom_webview",
    "acs.education_webview",
    "sqlite3",
    "webview",
    "pywebview",
    "acs.acsdb",
    "acs.stockfish",
    "acs.stockfish_runtime",
    "acs.chessbase",
    "acs.chessbase_",
)


def _forbidden(target: str) -> bool:
    for prefix in FORBIDDEN_PREFIXES:
        if prefix.endswith("_"):
            if target.startswith(prefix):
                return True
        elif target == prefix or target.startswith(prefix + "."):
            return True
    return False


def _literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _aliased_dynamic_imports(tree: ast.Module) -> list[tuple[int, str]]:
    importlib_modules: set[str] = set()
    import_module_functions: set[str] = set()
    builtins_modules: set[str] = set()

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib":
                    importlib_modules.add(alias.asname or "importlib")
                elif alias.name == "builtins":
                    builtins_modules.add(alias.asname or "builtins")
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            for alias in node.names:
                if alias.name == "import_module":
                    import_module_functions.add(alias.asname or "import_module")

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue

        matched = False
        if isinstance(node.func, ast.Name):
            matched = node.func.id in import_module_functions or node.func.id == "__import__"
        elif isinstance(node.func, ast.Attribute):
            if (
                node.func.attr == "import_module"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in importlib_modules
            ):
                matched = True
            elif (
                node.func.attr == "__import__"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in builtins_modules
            ):
                matched = True

        if matched:
            target = _literal(node.args[0])
            if target is not None:
                found.append((node.lineno, target))
    return found


class ArchitectureDynamicImportAliasTests(unittest.TestCase):
    def test_protected_core_has_no_aliased_literal_dynamic_dependency_escape(self) -> None:
        violations: list[str] = []
        for filename in PROTECTED_MODULES:
            path = ACS / filename
            self.assertTrue(path.is_file(), f"protected module disappeared: {filename}")
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for lineno, target in _aliased_dynamic_imports(tree):
                if _forbidden(target):
                    violations.append(f"{path.relative_to(ROOT)}:{lineno}: {target}")
        self.assertFalse(
            violations,
            "Aliased dynamic import bypasses the core dependency boundary:\n"
            + "\n".join(sorted(violations)),
        )

    def test_detector_catches_importlib_alias_function_alias_and_builtins(self) -> None:
        source = """
import importlib as il
import builtins as bi
from importlib import import_module as load

def a(): return il.import_module('acs.webapp')
def b(): return load('sqlite3')
def c(): return bi.__import__('acs.stockfish_runtime')
"""
        tree = ast.parse(source)
        self.assertEqual(
            [
                (6, "acs.webapp"),
                (7, "sqlite3"),
                (8, "acs.stockfish_runtime"),
            ],
            _aliased_dynamic_imports(tree),
        )

    def test_nonliteral_plugin_target_is_not_rejected(self) -> None:
        source = """
from importlib import import_module as load

def load_plugin(name): return load(name)
"""
        self.assertEqual([], _aliased_dynamic_imports(ast.parse(source)))


if __name__ == "__main__":
    unittest.main()
