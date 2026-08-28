from __future__ import annotations

"""Evidence-only one-core audit for PGN ingress consumers.

This script does not parse PGN and does not implement chess semantics. It scans
Product Python source with ``ast`` and proves that the low-level structural
``gametree.parse_games`` primitive is reachable only from the canonical D06
codec implementation and the explicitly bounded file-recovery fallback.

The audit exists because two independent real-corpus campaigns previously found
consumer bypasses of canonical D06 normalization: professional file ingress and
Books embedded PGN. A future third consumer must fail this gate rather than
silently creating another semantic ingress path.
"""

import argparse
import ast
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Iterable


AUTHORITY_SHA = "575ec0088982d2f90adb47c040a5714d68186b0e"
PRODUCT_ROOT = Path("acs")


@dataclass(frozen=True, slots=True)
class Site:
    path: str
    line: int
    function: str
    symbol: str
    kind: str


@dataclass(frozen=True, slots=True)
class ImportSite:
    path: str
    line: int
    module: str
    symbol: str
    local_name: str


class SourceInventory(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path.as_posix()
        self.function_stack: list[str] = []
        self.parse_names: set[str] = set()
        self.gametree_modules: set[str] = set()
        self.legacy_load_names: set[str] = set()
        self.legacy_pgn_modules: set[str] = set()
        self.parse_imports: list[ImportSite] = []
        self.legacy_imports: list[ImportSite] = []
        self.parse_calls: list[Site] = []
        self.legacy_calls: list[Site] = []
        self.canonical_ingress_calls: list[Site] = []
        self._discover_import_aliases = True

    @property
    def function(self) -> str:
        return self.function_stack[-1] if self.function_stack else "<module>"

    def _call_name(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            local = alias.asname or alias.name
            if module.endswith("gametree") and alias.name == "parse_games":
                self.parse_names.add(local)
                self.parse_imports.append(
                    ImportSite(self.path, node.lineno, module, alias.name, local)
                )
            if module == "" and alias.name == "gametree":
                self.gametree_modules.add(local)
            if module.endswith("pgn") and alias.name == "load_pgn":
                self.legacy_load_names.add(local)
                self.legacy_imports.append(
                    ImportSite(self.path, node.lineno, module, alias.name, local)
                )
            if module == "" and alias.name == "pgn":
                self.legacy_pgn_modules.add(local)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local = alias.asname or alias.name.split(".", 1)[0]
            if alias.name.endswith(".gametree") or alias.name == "gametree":
                self.gametree_modules.add(local)
            if alias.name.endswith(".pgn") or alias.name == "pgn":
                self.legacy_pgn_modules.add(local)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        call_name = self._call_name(node.func)
        is_parse = False
        if isinstance(node.func, ast.Name) and node.func.id in self.parse_names:
            is_parse = True
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "parse_games":
            # Attribute form is intentionally conservative. Any Product call to
            # something named parse_games deserves classification even if an
            # aliasing pattern changes.
            is_parse = True
        elif isinstance(node.func, ast.Name) and node.func.id == "parse_games":
            # Covers the defining module itself without requiring an import.
            is_parse = True

        if is_parse:
            self.parse_calls.append(
                Site(self.path, node.lineno, self.function, "parse_games", "structural_parse")
            )

        is_legacy_load = False
        if isinstance(node.func, ast.Name) and node.func.id in self.legacy_load_names:
            is_legacy_load = True
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "load_pgn":
            is_legacy_load = True
        if is_legacy_load:
            self.legacy_calls.append(
                Site(self.path, node.lineno, self.function, "load_pgn", "legacy_pgn_load")
            )

        if call_name in {"parse_pgn_text", "parse_pgn_bytes", "open_pgn"}:
            self.canonical_ingress_calls.append(
                Site(self.path, node.lineno, self.function, call_name, "canonical_ingress")
            )
        self.generic_visit(node)


def _inventory(path: Path) -> SourceInventory:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=path.as_posix())
    inventory = SourceInventory(path)
    inventory.visit(tree)
    return inventory


def _function_call_lines(path: Path, function_name: str, symbols: set[str]) -> dict[str, list[int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    result = {symbol: [] for symbol in symbols}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name != function_name:
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            name: str | None = None
            if isinstance(child.func, ast.Name):
                name = child.func.id
            elif isinstance(child.func, ast.Attribute):
                name = child.func.attr
            if name in result:
                result[name].append(child.lineno)
    return result


def _function_loaded_names(path: Path, function_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return {
                child.id
                for child in ast.walk(node)
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
            }
    return set()


def _allowed_parse_call(site: Site) -> bool:
    if site.path == "acs/gametree.py":
        return True
    if site.path == "acs/pgn_roundtrip.py" and site.function == "parse_pgn_text":
        return True
    if site.path == "acs/pgn_service.py" and site.function == "_parse_file_games":
        return True
    return False


def _allowed_parse_import(site: ImportSite) -> bool:
    return site.path in {"acs/pgn_roundtrip.py", "acs/pgn_service.py"}


def _sorted_sites(values: Iterable[Site]) -> list[dict[str, object]]:
    return [asdict(item) for item in sorted(values, key=lambda item: (item.path, item.line, item.function))]


def _sorted_imports(values: Iterable[ImportSite]) -> list[dict[str, object]]:
    return [asdict(item) for item in sorted(values, key=lambda item: (item.path, item.line, item.symbol))]


def run(*, report_path: Path | None = None) -> int:
    if not PRODUCT_ROOT.is_dir():
        raise AssertionError("acs Product root is unavailable")

    inventories = [_inventory(path) for path in sorted(PRODUCT_ROOT.rglob("*.py"))]
    parse_imports = [item for inv in inventories for item in inv.parse_imports]
    parse_calls = [item for inv in inventories for item in inv.parse_calls]
    legacy_imports = [item for inv in inventories for item in inv.legacy_imports]
    legacy_calls = [item for inv in inventories for item in inv.legacy_calls]
    canonical_calls = [item for inv in inventories for item in inv.canonical_ingress_calls]

    violations: list[str] = []
    for item in parse_imports:
        if not _allowed_parse_import(item):
            violations.append(
                f"unclassified parse_games import: {item.path}:{item.line} ({item.module})"
            )
    for item in parse_calls:
        if not _allowed_parse_call(item):
            violations.append(
                f"unclassified parse_games call: {item.path}:{item.line} function={item.function}"
            )

    roundtrip_path = Path("acs/pgn_roundtrip.py")
    roundtrip_calls = _function_call_lines(
        roundtrip_path, "parse_pgn_text", {"_preflight_text", "parse_games"}
    )
    if len(roundtrip_calls["_preflight_text"]) != 1 or len(roundtrip_calls["parse_games"]) != 1:
        violations.append(
            "canonical parse_pgn_text no longer has exactly one bounded preflight and one structural parse"
        )
    elif roundtrip_calls["_preflight_text"][0] >= roundtrip_calls["parse_games"][0]:
        violations.append("canonical parse_pgn_text structural parse precedes bounded text preflight")

    service_path = Path("acs/pgn_service.py")
    service_calls = _function_call_lines(
        service_path, "_parse_file_games", {"parse_pgn_text", "parse_games"}
    )
    service_names = _function_loaded_names(service_path, "_parse_file_games")
    if len(service_calls["parse_pgn_text"]) != 1 or len(service_calls["parse_games"]) != 1:
        violations.append(
            "file recovery helper no longer has exactly one canonical parse and one structural fallback"
        )
    elif service_calls["parse_pgn_text"][0] >= service_calls["parse_games"][0]:
        violations.append("file recovery structural parse precedes canonical D06 normalization")
    if "_RESOURCE_LIMIT_CODES" not in service_names:
        violations.append("file recovery helper no longer guards structural fallback with resource-limit codes")

    report = {
        "schema": 1,
        "authority_sha": AUTHORITY_SHA,
        "product_python_files_scanned": len(inventories),
        "structural_parse_imports": _sorted_imports(parse_imports),
        "structural_parse_calls": _sorted_sites(parse_calls),
        "canonical_ingress_calls": _sorted_sites(canonical_calls),
        "legacy_load_pgn_imports_inventory_only": _sorted_imports(legacy_imports),
        "legacy_load_pgn_calls_inventory_only": _sorted_sites(legacy_calls),
        "canonical_codec_contract": roundtrip_calls,
        "file_recovery_contract": {
            "calls": service_calls,
            "resource_limit_guard_observed": "_RESOURCE_LIMIT_CODES" in service_names,
        },
        "violations": sorted(violations),
        "product_mutation": "NONE",
    }

    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)
    if report_path is not None:
        report_path.write_text(encoded + "\n", encoding="utf-8", newline="\n")
    print("D06_INGRESS_CONVERGENCE=" + json.dumps(report, ensure_ascii=False, sort_keys=True))

    if violations:
        for violation in violations:
            print("D06_INGRESS_VIOLATION=" + violation)
        raise AssertionError(f"{len(violations)} unclassified canonical-ingress convergence violation(s)")

    print("D06 CANONICAL PGN INGRESS CONSUMER CONVERGENCE PASS")
    return 0


def _selftest() -> None:
    # Exercise only the oracle's deterministic data model; repository-level
    # classification is deliberately performed by run() against the checked-out
    # exact authority tree.
    sample = Site("acs/example.py", 7, "open", "parse_games", "structural_parse")
    if _allowed_parse_call(sample):
        raise AssertionError("selftest: arbitrary consumer was accidentally allowlisted")
    allowed = Site("acs/pgn_roundtrip.py", 10, "parse_pgn_text", "parse_games", "structural_parse")
    if not _allowed_parse_call(allowed):
        raise AssertionError("selftest: canonical codec implementation was not allowlisted")
    recovery = Site("acs/pgn_service.py", 10, "_parse_file_games", "parse_games", "structural_parse")
    if not _allowed_parse_call(recovery):
        raise AssertionError("selftest: bounded recovery fallback was not allowlisted")
    print("D06 INGRESS CONVERGENCE ORACLE SELFTEST PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.selftest:
        _selftest()
        return 0
    return run(report_path=args.report)


if __name__ == "__main__":
    raise SystemExit(main())
