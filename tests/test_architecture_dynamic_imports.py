from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ACS = ROOT / "acs"

# Keep this list aligned with the central presentation-neutral authorities
# protected by tests/test_architecture.py.  This regression closes dynamic
# import routes that ordinary Import/ImportFrom AST checks cannot see.
PROTECTED_MODULES = (
    "chesscore.py",
    "gametree.py",
    "bookdocument.py",
    "history.py",
)

FORBIDDEN_PREFIXES = (
    "acs.webapp",
    "acs.ui_",
    "acs.full_product_ui",
    "acs.library_webview",
    "acs.book_webview",
    "acs.training_webview",
    "acs.classroom_webview",
    "acs.education_webview",
)


def _literal_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _dynamic_import_targets(tree: ast.AST) -> list[tuple[int, str]]:
    targets: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue

        is_import = isinstance(node.func, ast.Name) and node.func.id == "__import__"
        is_importlib = (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "import_module"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "importlib"
        )
        if not (is_import or is_importlib):
            continue

        target = _literal_string(node.args[0])
        if target is not None:
            targets.append((node.lineno, target))
    return targets


class ArchitectureDynamicImportBoundaryTests(unittest.TestCase):
    def test_protected_core_modules_do_not_dynamically_import_presentation(self) -> None:
        violations: list[str] = []
        missing: list[str] = []

        for filename in PROTECTED_MODULES:
            path = ACS / filename
            if not path.is_file():
                missing.append(filename)
                continue

            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for lineno, target in _dynamic_import_targets(tree):
                if any(target == prefix or target.startswith(prefix + ".") for prefix in FORBIDDEN_PREFIXES):
                    violations.append(f"{path.relative_to(ROOT)}:{lineno}: {target}")

        self.assertFalse(
            missing,
            "Protected architecture authorities disappeared without updating the gate: "
            + ", ".join(sorted(missing)),
        )
        self.assertFalse(
            violations,
            "Presentation dependency entered protected core through a dynamic import:\n"
            + "\n".join(sorted(violations)),
        )

    def test_detector_catches_importlib_and_dunder_import(self) -> None:
        source = """
import importlib

def a():
    return importlib.import_module('acs.webapp')

def b():
    return __import__('acs.ui_native_menu')
"""
        found = _dynamic_import_targets(ast.parse(source))
        self.assertEqual(
            [(5, "acs.webapp"), (8, "acs.ui_native_menu")],
            found,
        )

    def test_detector_ignores_nonliteral_runtime_plugin_names(self) -> None:
        source = """
import importlib

def load(name):
    return importlib.import_module(name)
"""
        self.assertEqual([], _dynamic_import_targets(ast.parse(source)))


if __name__ == "__main__":
    unittest.main()
