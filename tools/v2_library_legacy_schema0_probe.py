from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import io
import json
import re
import subprocess
import zipfile
from pathlib import Path
from typing import Any

RC3_COMMIT = "1a8934a0f7125262cfdb9854e459ffcd22e55348"
RC3_CHUNKS = (
    "build_snapshot_exact/group00.b64",
    "build_snapshot_exact/group01.b64",
    "build_parts10k/part04.b64",
    "build_parts10k/part05.b64",
    "build_parts10k/part06.b64",
    "build_parts10k/part07.b64",
)
EXPECTED_B64_LENGTH = 77128
EXPECTED_ZIP_SIZE = 57844
EXPECTED_ZIP_SHA256 = "cb0a897286d0dce6ff9d05d985169d42e4f9540203115611356e6f831de2bce7"
EXPECTED_STORAGE_CRC32 = 0x2DD0CBA0
EXPECTED_STORAGE_SIZE = 762

_INTERESTING_STRING = re.compile(
    r"(?:library|sqlite|\.db\b|\.sqlite\b|appdata|accessible.?chess)", re.IGNORECASE
)


def _git_show(repo: Path, commit: str, path: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repo), "show", f"{commit}:{path}"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def reconstruct_stage1_zip(repo: Path) -> bytes:
    encoded = b"".join(_git_show(repo, RC3_COMMIT, path) for path in RC3_CHUNKS)
    encoded = re.sub(rb"\s+", b"", encoded)
    if len(encoded) != EXPECTED_B64_LENGTH:
        raise RuntimeError(
            f"unexpected pinned Stage1 Base64 length: {len(encoded)} != {EXPECTED_B64_LENGTH}"
        )
    try:
        payload = base64.b64decode(encoded, validate=True)
    except Exception as exc:  # pragma: no cover - exact failure text is intentionally hidden
        raise RuntimeError("pinned Stage1 Base64 payload is invalid") from exc
    digest = hashlib.sha256(payload).hexdigest()
    if len(payload) != EXPECTED_ZIP_SIZE:
        raise RuntimeError(
            f"unexpected pinned Stage1 ZIP size: {len(payload)} != {EXPECTED_ZIP_SIZE}"
        )
    if digest != EXPECTED_ZIP_SHA256:
        raise RuntimeError("pinned Stage1 ZIP SHA-256 mismatch")
    return payload


def _names_in_expr(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    return {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}


def _safe_unparse(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return None


def _assignment_map(tree: ast.AST) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            targets: list[ast.expr]
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            else:
                targets = [node.target]
            for target in targets:
                for name_node in ast.walk(target):
                    if isinstance(name_node, ast.Name):
                        result.setdefault(name_node.id, []).append(
                            {
                                "line": getattr(node, "lineno", None),
                                "expr": _safe_unparse(value),
                                "dependencies": sorted(_names_in_expr(value)),
                            }
                        )
    for entries in result.values():
        entries.sort(key=lambda item: item["line"] or 0)
    return result


def _dependency_chain(
    assignments: dict[str, list[dict[str, Any]]],
    names: set[str],
    *,
    before_line: int,
    max_depth: int = 5,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    queue: list[tuple[str, int]] = [(name, 0) for name in sorted(names)]
    rows: list[dict[str, Any]] = []
    while queue:
        name, depth = queue.pop(0)
        if name in seen or depth > max_depth:
            continue
        seen.add(name)
        candidates = [
            item for item in assignments.get(name, ()) if (item["line"] or 0) <= before_line
        ]
        if not candidates:
            continue
        item = candidates[-1]
        row = {"name": name, "line": item["line"], "expr": item["expr"]}
        rows.append(row)
        for dependency in item["dependencies"]:
            if dependency != name:
                queue.append((dependency, depth + 1))
    rows.sort(key=lambda item: (item["line"] or 0, item["name"]))
    return rows


def _source_window(lines: list[str], lineno: int, radius: int = 4) -> list[dict[str, Any]]:
    start = max(1, lineno - radius)
    end = min(len(lines), lineno + radius)
    return [{"line": n, "text": lines[n - 1]} for n in range(start, end + 1)]


def inspect_python_member(member: str, source: str) -> dict[str, Any]:
    lines = source.splitlines()
    try:
        tree = ast.parse(source, filename=member)
    except SyntaxError as exc:
        return {"member": member, "syntax_error": f"line {exc.lineno}"}

    assignments = _assignment_map(tree)
    library_aliases: set[str] = set()
    storage_aliases: set[str] = set()
    imports: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {"storage", "acs.storage"}:
            for alias in node.names:
                imports.append(
                    {
                        "line": node.lineno,
                        "module": node.module,
                        "name": alias.name,
                        "asname": alias.asname,
                    }
                )
                if alias.name == "Library":
                    library_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"storage", "acs.storage"}:
                    imports.append(
                        {
                            "line": node.lineno,
                            "module": alias.name,
                            "name": None,
                            "asname": alias.asname,
                        }
                    )
                    storage_aliases.add(alias.asname or alias.name.split(".")[-1])

    calls: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        is_library = isinstance(node.func, ast.Name) and node.func.id in library_aliases
        is_storage_library = (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "Library"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in storage_aliases
        )
        if not (is_library or is_storage_library):
            continue
        arg = node.args[0] if node.args else None
        calls.append(
            {
                "line": node.lineno,
                "call": _safe_unparse(node),
                "path_arg": _safe_unparse(arg),
                "dependency_assignments": _dependency_chain(
                    assignments,
                    _names_in_expr(arg),
                    before_line=node.lineno,
                ),
                "source_window": _source_window(lines, node.lineno),
            }
        )

    interesting_strings: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _INTERESTING_STRING.search(node.value):
                interesting_strings.append(
                    {"line": getattr(node, "lineno", None), "value": node.value}
                )
    interesting_strings.sort(key=lambda item: item["line"] or 0)

    return {
        "member": member,
        "imports": imports,
        "library_calls": calls,
        "interesting_strings": interesting_strings,
    }


def build_evidence(repo: Path) -> dict[str, Any]:
    payload = reconstruct_stage1_zip(repo)
    with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
        infos = {info.filename: info for info in archive.infolist()}
        required = {"acs/main.py", "acs/storage.py", "run_accessible_chess.py"}
        missing = sorted(required.difference(infos))
        if missing:
            raise RuntimeError(f"pinned Stage1 source missing required members: {missing}")

        storage_info = infos["acs/storage.py"]
        if storage_info.file_size != EXPECTED_STORAGE_SIZE:
            raise RuntimeError("pinned acs/storage.py size mismatch")
        if storage_info.CRC != EXPECTED_STORAGE_CRC32:
            raise RuntimeError("pinned acs/storage.py CRC32 mismatch")
        storage_text = archive.read("acs/storage.py").decode("utf-8")
        if "CREATE TABLE IF NOT EXISTS games(id INTEGER PRIMARY KEY, title TEXT, pgn TEXT, created_at TEXT)" not in storage_text:
            raise RuntimeError("pinned legacy schema-0 SQL contract mismatch")

        python_members = sorted(name for name in infos if name.endswith(".py"))
        inspection: list[dict[str, Any]] = []
        for member in python_members:
            source = archive.read(member).decode("utf-8-sig")
            item = inspect_python_member(member, source)
            if item.get("imports") or item.get("library_calls") or item.get("interesting_strings"):
                inspection.append(item)

        library_calls = [
            {"member": item["member"], **call}
            for item in inspection
            for call in item.get("library_calls", ())
        ]
        imports = [
            {"member": item["member"], **entry}
            for item in inspection
            for entry in item.get("imports", ())
        ]

        return {
            "evidence_schema": 1,
            "rc3_commit": RC3_COMMIT,
            "stage1_source_zip": {
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
                "member_count": len(infos),
            },
            "legacy_storage": {
                "member": "acs/storage.py",
                "size": storage_info.file_size,
                "crc32": f"{storage_info.CRC:08x}",
                "schema": "games(id INTEGER PRIMARY KEY, title TEXT, pgn TEXT, created_at TEXT)",
            },
            "storage_imports": imports,
            "library_calls": library_calls,
            "inspection": inspection,
            "runtime_reachability_proven": bool(library_calls),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    evidence = build_evidence(args.repo.resolve())
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    if not evidence["runtime_reachability_proven"]:
        raise SystemExit("legacy Library runtime call site was not proven in the pinned RC3 source")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
