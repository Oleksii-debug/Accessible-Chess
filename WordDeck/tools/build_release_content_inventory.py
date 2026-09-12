#!/usr/bin/env python3
"""Build an exact WordDeck commercial-content inventory from a packaged release.

A commercial package must contain an explicit CONTENT_ASSET_INDEX.json that maps
stable provenance asset IDs to relative packaged content paths and declares the
content roots that must be exhaustively covered. This tool hashes the actual
packaged bytes and fails closed when a content file is unindexed, an indexed
file is missing, a path escapes the package root, or IDs/paths are ambiguous.

It intentionally does not decide legal clearance. Its output is consumed by
validate_content_provenance_strict.py, which binds the package bytes to the
canonical rights/provenance manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Mapping, Sequence, Tuple


class InventoryFailure(Exception):
    pass


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise InventoryFailure(f"missing asset index: {path}") from exc
    except json.JSONDecodeError as exc:
        raise InventoryFailure(f"invalid JSON in asset index {path}: {exc}") from exc


def _normal_relative(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InventoryFailure(f"{field}: required non-empty relative path")
    normalized = value.strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or normalized.startswith("/") or any(part in ("", ".", "..") for part in path.parts):
        raise InventoryFailure(f"{field}: unsafe/non-normal relative path {value!r}")
    return path.as_posix()


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_inventory(release_root: Path, asset_index: Any, release_id: str,
                    channel: str) -> Tuple[Dict[str, Any], List[str]]:
    errors: List[str] = []
    root = release_root.resolve()
    if not root.is_dir():
        return {}, [f"release root is not a directory: {release_root}"]
    if not isinstance(asset_index, dict):
        return {}, ["asset index: required JSON object"]
    if asset_index.get("schema_version") != "1.0":
        errors.append("asset index.schema_version: expected '1.0'")

    raw_roots = asset_index.get("content_roots")
    if not isinstance(raw_roots, list) or not raw_roots:
        errors.append("asset index.content_roots: required non-empty array")
        raw_roots = []
    content_roots: List[str] = []
    for i, value in enumerate(raw_roots):
        try:
            normalized = _normal_relative(value, f"content_roots[{i}]")
        except InventoryFailure as exc:
            errors.append(str(exc))
            continue
        if normalized in content_roots:
            errors.append(f"content_roots[{i}]: duplicate root {normalized!r}")
        else:
            content_roots.append(normalized)

    raw_assets = asset_index.get("assets")
    if not isinstance(raw_assets, list):
        errors.append("asset index.assets: required array")
        raw_assets = []

    by_path: Dict[str, str] = {}
    by_id: Dict[str, str] = {}
    for i, item in enumerate(raw_assets):
        prefix = f"asset index.assets[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: required object")
            continue
        asset_id = item.get("asset_id")
        if not isinstance(asset_id, str) or not asset_id.strip():
            errors.append(f"{prefix}.asset_id: required stable asset ID")
            continue
        asset_id = asset_id.strip()
        try:
            rel = _normal_relative(item.get("path"), f"{prefix}.path")
        except InventoryFailure as exc:
            errors.append(str(exc))
            continue
        if asset_id in by_id:
            errors.append(f"{prefix}.asset_id: duplicate asset ID {asset_id!r}")
        else:
            by_id[asset_id] = rel
        if rel in by_path:
            errors.append(f"{prefix}.path: duplicate packaged path {rel!r}")
        else:
            by_path[rel] = asset_id
        if content_roots and not any(rel == content_root or rel.startswith(content_root + "/") for content_root in content_roots):
            errors.append(f"{prefix}.path: {rel!r} is outside declared content_roots")

    discovered: Dict[str, Path] = {}
    for content_root in content_roots:
        directory = (root / Path(content_root)).resolve()
        if not _inside(root, directory):
            errors.append(f"content root escapes release root: {content_root!r}")
            continue
        if not directory.is_dir():
            errors.append(f"declared content root is missing/not a directory: {content_root!r}")
            continue
        for file_path in directory.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.is_symlink():
                errors.append(f"packaged content symlink is forbidden: {file_path}")
                continue
            resolved = file_path.resolve()
            if not _inside(root, resolved):
                errors.append(f"packaged content path escapes release root: {file_path}")
                continue
            rel = resolved.relative_to(root).as_posix()
            discovered[rel] = resolved

    for rel in sorted(discovered):
        if rel not in by_path:
            errors.append(f"unregistered packaged content file: {rel}")
    for rel in sorted(by_path):
        if rel not in discovered:
            errors.append(f"indexed packaged content file is missing: {rel}")

    if errors:
        return {}, errors

    inventory_assets = [
        {
            "asset_id": by_path[rel],
            "content_hash_sha256": _sha256(discovered[rel]),
            "package_path": rel,
        }
        for rel in sorted(discovered)
    ]
    inventory = {
        "release_id": release_id,
        "channel": channel,
        "package_inventory_source": "CONTENT_ASSET_INDEX.json+actual_packaged_bytes",
        "assets": inventory_assets,
    }
    return inventory, []


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", required=True, type=Path)
    parser.add_argument("--asset-index", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--channel", required=True)
    args = parser.parse_args(argv)
    try:
        index = _load_json(args.asset_index)
        inventory, errors = build_inventory(args.release_root, index, args.release_id, args.channel)
    except InventoryFailure as exc:
        print(f"CONTENT_PACKAGE_INVENTORY_FAIL: {exc}", file=sys.stderr)
        return 2
    if errors:
        print("CONTENT_PACKAGE_INVENTORY_FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"CONTENT_PACKAGE_INVENTORY_PASS assets={len(inventory['assets'])} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
