from __future__ import annotations

"""Evidence-only one-core audit for PGN ingress consumers.

This script does not implement PGN or chess semantics. Static analysis inventories
Product call sites that reach the low-level structural ``gametree.parse_games``
primitive. Small dynamic probes then compare those consumers against the existing
canonical D06 codec contract. Product code is never modified by this QA package.
"""

import argparse
import ast
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable

from acs.acsdb import AcsDatabase
from acs.book_training import (
    BookTrainingError,
    _MAX_SOLUTION_PGN_TEXT,
    build_book_training_material,
)
from acs.bookdocument import BookDocument, Exercise
from acs.chesscore import Board
from acs.duplicate_detection import detect_pgn_duplicates
from acs.game_identity import identity_for_game
from acs.gametree import parse_games
from acs.gametree_snapshot import (
    GAMETREE_SNAPSHOT_SCHEMA_VERSION,
    GameTreeSnapshot,
    restore_game,
    snapshot_from_record,
    snapshot_to_record,
)
from acs.pgn_roundtrip import (
    MAX_PGN_TAG_VALUE_CHARS,
    MAX_PGN_TEXT_CHARS,
    PgnRoundTripError,
    PgnRoundTripErrorCode,
    parse_pgn_text,
    serialize_pgn_text,
)


AUTHORITY_SHA = "575ec0088982d2f90adb47c040a5714d68186b0e"
PRODUCT_ROOT = Path("acs")
_ATTACHED_NAG_PGN = '[Event "NAG equivalence"]\n[Result "*"]\n\n1. e4?! *\n'


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
        self.legacy_load_names: set[str] = set()
        self.parse_imports: list[ImportSite] = []
        self.legacy_imports: list[ImportSite] = []
        self.parse_calls: list[Site] = []
        self.legacy_calls: list[Site] = []
        self.canonical_ingress_calls: list[Site] = []

    @property
    def function(self) -> str:
        return self.function_stack[-1] if self.function_stack else "<module>"

    @staticmethod
    def _call_name(node: ast.AST) -> str | None:
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
                self.parse_imports.append(ImportSite(self.path, node.lineno, module, alias.name, local))
            if module.endswith("pgn") and alias.name == "load_pgn":
                self.legacy_load_names.add(local)
                self.legacy_imports.append(ImportSite(self.path, node.lineno, module, alias.name, local))
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
        is_parse = (
            isinstance(node.func, ast.Name)
            and (node.func.id in self.parse_names or node.func.id == "parse_games")
        ) or (isinstance(node.func, ast.Attribute) and node.func.attr == "parse_games")
        if is_parse:
            self.parse_calls.append(Site(self.path, node.lineno, self.function, "parse_games", "structural_parse"))

        is_legacy = (
            isinstance(node.func, ast.Name) and node.func.id in self.legacy_load_names
        ) or (isinstance(node.func, ast.Attribute) and node.func.attr == "load_pgn")
        if is_legacy:
            self.legacy_calls.append(Site(self.path, node.lineno, self.function, "load_pgn", "legacy_pgn_load"))

        if call_name in {"parse_pgn_text", "parse_pgn_bytes", "open_pgn"}:
            self.canonical_ingress_calls.append(
                Site(self.path, node.lineno, self.function, call_name, "canonical_ingress")
            )
        self.generic_visit(node)


def _inventory(path: Path) -> SourceInventory:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
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
            name = SourceInventory._call_name(child.func)
            if name in result:
                result[name].append(child.lineno)
    return result


def _function_loaded_names(path: Path, function_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return {
                child.id for child in ast.walk(node)
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
            }
    return set()


def _canonical_internal_call(site: Site) -> bool:
    return (
        (site.path == "acs/pgn_roundtrip.py" and site.function == "parse_pgn_text")
        or (site.path == "acs/pgn_service.py" and site.function == "_parse_file_games")
    )


def _reviewed_consumer_call(site: Site) -> bool:
    return (site.path, site.function) in {
        ("acs/acsdb.py", "import_pgn_text"),
        ("acs/book_training.py", "_canonical_steps_from_pgn"),
        ("acs/duplicate_detection.py", "detect_pgn_duplicates"),
        ("acs/gametree_snapshot.py", "restore_game"),
    }


def _allowed_parse_import(site: ImportSite) -> bool:
    return site.path in {
        "acs/pgn_roundtrip.py",
        "acs/pgn_service.py",
        "acs/acsdb.py",
        "acs/book_training.py",
        "acs/duplicate_detection.py",
        "acs/gametree_snapshot.py",
    }


def _sorted_sites(values: Iterable[Site]) -> list[dict[str, object]]:
    return [asdict(item) for item in sorted(values, key=lambda item: (item.path, item.line, item.function))]


def _sorted_imports(values: Iterable[ImportSite]) -> list[dict[str, object]]:
    return [asdict(item) for item in sorted(values, key=lambda item: (item.path, item.line, item.symbol))]


def _acsdb_probe() -> tuple[dict[str, object], list[str]]:
    oversized = "X" * (MAX_PGN_TAG_VALUE_CHARS + 1)
    text = f'[Event "{oversized}"]\n[Result "*"]\n\n*\n'
    canonical_code: str | None = None
    try:
        parse_pgn_text(text, strict=True)
    except PgnRoundTripError as exc:
        canonical_code = exc.code.value
    accepted = False
    stored_status: str | None = None
    with AcsDatabase() as database:
        try:
            report = database.import_pgn_text(text, "oversized-event.pgn")
        except Exception as exc:  # evidence classification only
            consumer_result = type(exc).__name__
        else:
            accepted = True
            row = database.get_game(report.game_ids[0]) if report.game_ids else None
            stored_status = None if row is None else str(row["import_status"])
            consumer_result = "accepted"
    blockers: list[str] = []
    if canonical_code != PgnRoundTripErrorCode.TAG_SIZE_LIMIT.value:
        blockers.append(f"oracle_control: canonical oversized-tag classification changed to {canonical_code}")
    if accepted:
        blockers.append("D07 acsdb.import_pgn_text accepts external PGN rejected by canonical D06 tag-size bound")
    return {
        "surface": "acsdb.import_pgn_text",
        "trust": "external_import_text",
        "canonical_code": canonical_code,
        "consumer_result": consumer_result,
        "consumer_accepted": accepted,
        "stored_status": stored_status,
        "tag_chars": len(oversized),
        "classification": "DIVERGENT_RESOURCE_BOUND" if accepted else "FAIL_CLOSED",
    }, blockers


def _duplicate_probe() -> tuple[dict[str, object], list[str]]:
    canonical_games = parse_pgn_text(_ATTACHED_NAG_PGN, strict=True)
    canonical_text = serialize_pgn_text(canonical_games)
    canonical_identity = identity_for_game(canonical_games[0])
    with AcsDatabase() as database:
        imported = database.import_pgn_text(canonical_text, "canonical.pgn")
        report = detect_pgn_duplicates(database, _ATTACHED_NAG_PGN)
        kinds = sorted({match.kind for match in report.matches})
        existing_source = imported.source_id
    semantic_detected = any(kind in {"record", "tree"} for kind in kinds)
    blockers: list[str] = []
    if not semantic_detected:
        blockers.append(
            "D07 duplicate_detection misses canonical-equivalent attached symbolic NAG spelling"
        )
    return {
        "surface": "duplicate_detection.detect_pgn_duplicates",
        "trust": "external_candidate_text_plus_stored_pgn",
        "canonical_tree_digest": canonical_identity.tree_digest,
        "canonical_record_digest": canonical_identity.record_digest,
        "stored_source_id": existing_source,
        "match_kinds": kinds,
        "semantic_duplicate_detected": semantic_detected,
        "classification": "CONVERGENT" if semantic_detected else "DIVERGENT_SEMANTIC_IDENTITY",
    }, blockers


def _snapshot_probe() -> tuple[dict[str, object], list[str]]:
    structural = parse_games(_ATTACHED_NAG_PGN)
    if len(structural) != 1:
        raise AssertionError("snapshot probe seed did not structurally parse as one game")
    game = structural[0]
    identity = identity_for_game(game)
    snapshot = GameTreeSnapshot(
        schema_version=GAMETREE_SNAPSHOT_SCHEMA_VERSION,
        pgn_text=_ATTACHED_NAG_PGN,
        pgn_digest=hashlib.sha256(_ATTACHED_NAG_PGN.encode("utf-8")).hexdigest(),
        tree_digest=identity.tree_digest,
        record_digest=identity.record_digest,
        source_index=game.source_index,
        warnings=tuple(game.warnings),
    )
    external = snapshot_from_record(snapshot_to_record(snapshot))
    restored = restore_game(external)
    strict_code: str | None = None
    try:
        serialize_pgn_text((restored,))
    except PgnRoundTripError as exc:
        strict_code = exc.code.value
    blockers: list[str] = []
    if strict_code is not None:
        blockers.append(
            "D06 gametree_snapshot restores self-consistent external snapshot to non-strict GameTree"
        )
    return {
        "surface": "gametree_snapshot.restore_game",
        "trust": "external_versioned_snapshot_record",
        "external_record_validated": True,
        "restored_san": restored.line.moves[0].san if restored.line.moves else None,
        "restored_nags": list(restored.line.moves[0].nags) if restored.line.moves else [],
        "strict_serialize_code": strict_code,
        "classification": "CONVERGENT" if strict_code is None else "DIVERGENT_NON_STRICT_RESTORE",
    }, blockers


def _book_training_probe() -> tuple[dict[str, object], list[str]]:
    exercise = Exercise(
        fen=Board.START,
        prompt="QA attached annotation",
        solution_pgn=_ATTACHED_NAG_PGN,
        block_id="qa-attached-nag",
    )
    book = BookDocument("QA", blocks=[exercise])
    accepted = False
    error_code: str | None = None
    try:
        build_book_training_material(book, "block:qa-attached-nag")
    except BookTrainingError as exc:
        error_code = exc.code.value
    else:
        accepted = True
    blockers: list[str] = []
    if _MAX_SOLUTION_PGN_TEXT > MAX_PGN_TEXT_CHARS:
        blockers.append("D08 solution PGN local bound exceeds canonical D06 text ceiling")
    if accepted:
        blockers.append("D08 book training silently accepts annotated PGN outside its declared plain-mainline grammar")
    return {
        "surface": "book_training._canonical_steps_from_pgn",
        "trust": "bounded_exercise_solution_subgrammar",
        "local_text_limit": _MAX_SOLUTION_PGN_TEXT,
        "canonical_text_limit": MAX_PGN_TEXT_CHARS,
        "attached_annotation_accepted": accepted,
        "error_code": error_code,
        "classification": "DIVERGENT_SILENT_ACCEPT" if accepted else "FAIL_CLOSED_DECLARED_SUBGRAMMAR",
    }, blockers


def _dynamic_probes() -> tuple[list[dict[str, object]], list[str]]:
    results: list[dict[str, object]] = []
    blockers: list[str] = []
    for probe in (_acsdb_probe, _duplicate_probe, _snapshot_probe, _book_training_probe):
        result, found = probe()
        results.append(result)
        blockers.extend(found)
    return results, blockers


def run(*, report_path: Path | None = None, enforce: bool = True) -> int:
    if not PRODUCT_ROOT.is_dir():
        raise AssertionError("acs Product root is unavailable")

    inventories = [_inventory(path) for path in sorted(PRODUCT_ROOT.rglob("*.py"))]
    parse_imports = [item for inv in inventories for item in inv.parse_imports]
    parse_calls = [item for inv in inventories for item in inv.parse_calls]
    legacy_imports = [item for inv in inventories for item in inv.legacy_imports]
    legacy_calls = [item for inv in inventories for item in inv.legacy_calls]
    canonical_calls = [item for inv in inventories for item in inv.canonical_ingress_calls]

    blockers: list[str] = []
    for item in parse_imports:
        if not _allowed_parse_import(item):
            blockers.append(f"unclassified parse_games import: {item.path}:{item.line} ({item.module})")
    for item in parse_calls:
        if not (_canonical_internal_call(item) or _reviewed_consumer_call(item)):
            blockers.append(
                f"unclassified parse_games call: {item.path}:{item.line} function={item.function}"
            )

    roundtrip_path = Path("acs/pgn_roundtrip.py")
    roundtrip_calls = _function_call_lines(roundtrip_path, "parse_pgn_text", {"_preflight_text", "parse_games"})
    if len(roundtrip_calls["_preflight_text"]) != 1 or len(roundtrip_calls["parse_games"]) != 1:
        blockers.append("canonical parse_pgn_text no longer has exactly one bounded preflight and one structural parse")
    elif roundtrip_calls["_preflight_text"][0] >= roundtrip_calls["parse_games"][0]:
        blockers.append("canonical parse_pgn_text structural parse precedes bounded text preflight")

    service_path = Path("acs/pgn_service.py")
    service_calls = _function_call_lines(service_path, "_parse_file_games", {"parse_pgn_text", "parse_games"})
    service_names = _function_loaded_names(service_path, "_parse_file_games")
    if len(service_calls["parse_pgn_text"]) != 1 or len(service_calls["parse_games"]) != 1:
        blockers.append("file recovery helper no longer has exactly one canonical parse and one structural fallback")
    elif service_calls["parse_pgn_text"][0] >= service_calls["parse_games"][0]:
        blockers.append("file recovery structural parse precedes canonical D06 normalization")
    if "_RESOURCE_LIMIT_CODES" not in service_names:
        blockers.append("file recovery helper no longer guards structural fallback with resource-limit codes")

    dynamic_results, dynamic_blockers = _dynamic_probes()
    blockers.extend(dynamic_blockers)

    report = {
        "schema": 2,
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
        "consumer_classifications": dynamic_results,
        "blocking_findings": sorted(set(blockers)),
        "product_mutation": "NONE",
    }

    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)
    if report_path is not None:
        report_path.write_text(encoded + "\n", encoding="utf-8", newline="\n")
    print("D06_INGRESS_CONVERGENCE=" + json.dumps(report, ensure_ascii=False, sort_keys=True))

    if blockers:
        for blocker in sorted(set(blockers)):
            print("D06_INGRESS_BLOCKER=" + blocker)
        if enforce:
            raise AssertionError(f"{len(set(blockers))} canonical-ingress convergence blocker(s)")
        print("D06 CANONICAL PGN INGRESS EVIDENCE CAPTURED WITH BLOCKERS")
        return 0

    print("D06 CANONICAL PGN INGRESS CONSUMER CONVERGENCE PASS")
    return 0


def enforce_report(path: Path) -> int:
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("authority_sha") != AUTHORITY_SHA:
        raise AssertionError("convergence report authority changed")
    blockers = report.get("blocking_findings")
    if type(blockers) is not list:
        raise AssertionError("convergence report has no exact blocking_findings list")
    if blockers:
        for blocker in blockers:
            print("D06_INGRESS_BLOCKER=" + str(blocker))
        raise AssertionError(f"{len(blockers)} canonical-ingress convergence blocker(s)")
    print("D06 CANONICAL PGN INGRESS CONSUMER CONVERGENCE PASS")
    return 0


def _selftest() -> None:
    arbitrary = Site("acs/example.py", 7, "open", "parse_games", "structural_parse")
    if _canonical_internal_call(arbitrary) or _reviewed_consumer_call(arbitrary):
        raise AssertionError("selftest: arbitrary consumer was accidentally classified")
    allowed = Site("acs/pgn_roundtrip.py", 10, "parse_pgn_text", "parse_games", "structural_parse")
    if not _canonical_internal_call(allowed):
        raise AssertionError("selftest: canonical codec implementation was not classified")
    reviewed = Site("acs/acsdb.py", 10, "import_pgn_text", "parse_games", "structural_parse")
    if not _reviewed_consumer_call(reviewed):
        raise AssertionError("selftest: reviewed external consumer was not classified")
    print("D06 INGRESS CONVERGENCE ORACLE SELFTEST PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--no-enforce", action="store_true")
    parser.add_argument("--enforce-report", type=Path)
    args = parser.parse_args()
    if args.selftest:
        _selftest()
        return 0
    if args.enforce_report is not None:
        return enforce_report(args.enforce_report)
    return run(report_path=args.report, enforce=not args.no_enforce)


if __name__ == "__main__":
    raise SystemExit(main())
