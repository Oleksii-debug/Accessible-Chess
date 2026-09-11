from __future__ import annotations

import ast
from pathlib import Path
import unittest

from acs.acsdb import AcsDatabase
from acs.pgn_roundtrip import parse_pgn_text


class _RawParseCallVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.aliases: set[str] = set()
        self.calls: list[str] = []
        self._functions: list[str] = []

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "gametree":
            for alias in node.names:
                if alias.name == "parse_games":
                    self.aliases.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._functions.append(node.name)
        self.generic_visit(node)
        self._functions.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._functions.append(node.name)
        self.generic_visit(node)
        self._functions.pop()

    def visit_Call(self, node: ast.Call) -> None:
        is_raw = isinstance(node.func, ast.Name) and node.func.id in self.aliases
        if isinstance(node.func, ast.Attribute) and node.func.attr == "parse_games":
            is_raw = True
        if is_raw:
            self.calls.append(self._functions[-1] if self._functions else "<module>")
        self.generic_visit(node)


class D07CanonicalIngressSuccessorTests(unittest.TestCase):
    def test_product_raw_parse_games_inventory_has_no_d07_bypass(self) -> None:
        root = Path(__file__).resolve().parents[1]
        observed: set[tuple[str, str]] = set()
        for path in sorted((root / "acs").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            visitor = _RawParseCallVisitor()
            visitor.visit(tree)
            observed.update((path.relative_to(root).as_posix(), function) for function in visitor.calls)

        self.assertEqual(
            observed,
            {
                ("acs/pgn_roundtrip.py", "parse_pgn_text"),
                ("acs/pgn_service.py", "_parse_file_games"),
            },
            "raw parse_games inventory changed; D07 must delegate to bounded canonical D06",
        )

    def test_acsdb_recovery_semantics_still_come_from_canonical_d06(self) -> None:
        text = '[Event "Damaged"]\n[Result "*"]\n\n1. e4 e5\n'
        canonical = parse_pgn_text(text, strict=False)
        self.assertEqual(len(canonical), 1)
        self.assertTrue(canonical[0].warnings)

        with AcsDatabase() as database:
            report = database.import_pgn_text(text, "damaged-recovery.pgn")
            self.assertEqual(report.total, 1)
            self.assertEqual(report.warning, 1)
            self.assertEqual(report.full, 0)
            self.assertEqual(report.damaged, 0)
            attempt = database.get_import_attempt(report.attempt_id)
            self.assertIsNotNone(attempt)
            self.assertEqual(attempt["status"], "warning")
            self.assertEqual(attempt["game_count"], 1)
            self.assertEqual(attempt["warning_count"], 1)
            self.assertIsNone(attempt["error_message"])
            stored = database.get_game(report.game_ids[0])
            self.assertIsNotNone(stored)
            self.assertEqual(stored["import_status"], "warning")


if __name__ == "__main__":
    unittest.main()