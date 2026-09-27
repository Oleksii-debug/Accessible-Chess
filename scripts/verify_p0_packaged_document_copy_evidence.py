from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any


MAX_JSON_BYTES = 64 * 1024
MAX_CHECKSUM_BYTES = 4 * 1024 * 1024
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
CHECKSUM_PATH = "AccessibleChess/AccessibleChess.exe"


class EvidenceError(RuntimeError):
    pass


def _no_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise EvidenceError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def _read_json(path: Path) -> dict[str, Any]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise EvidenceError("required JSON file is unavailable") from exc
    if size <= 0 or size > MAX_JSON_BYTES:
        raise EvidenceError("JSON file size is outside the accepted bound")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise EvidenceError("required JSON file is not readable UTF-8") from exc
    try:
        value = json.loads(text, object_pairs_hook=_no_duplicate_object)
    except EvidenceError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise EvidenceError("invalid JSON evidence") from exc
    if not isinstance(value, dict):
        raise EvidenceError("JSON evidence root must be an object")
    return value


def _require_true(obj: dict[str, Any], key: str) -> None:
    if obj.get(key) is not True:
        raise EvidenceError(f"required evidence flag is not true: {key}")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                h.update(block)
    except OSError as exc:
        raise EvidenceError("packaged executable is unreadable") from exc
    return h.hexdigest()


def _canonical_expected_sha(value: str) -> str:
    lowered = value.strip().lower()
    if not HEX40.fullmatch(lowered):
        raise EvidenceError("product SHA must be one exact 40-hex commit")
    return lowered


def _verify_package_binding(product_root: Path, expected_sha: str) -> None:
    try:
        root = product_root.resolve(strict=True)
    except OSError as exc:
        raise EvidenceError("product root is unavailable") from exc
    if not root.is_dir():
        raise EvidenceError("product root must be a directory")

    exe = root / "AccessibleChess.exe"
    if not exe.is_file() or exe.is_symlink():
        raise EvidenceError("AccessibleChess.exe must be a direct regular file")

    package_root = root.parent
    manifest = _read_json(package_root / "RELEASE_MANIFEST.json")
    manifest_sha = manifest.get("integration_sha")
    if not isinstance(manifest_sha, str) or manifest_sha.lower() != expected_sha:
        raise EvidenceError("release manifest integration_sha does not match expected product SHA")
    for key in ("human_tested", "nvda_verified"):
        if manifest.get(key) is not False:
            raise EvidenceError(f"release manifest must explicitly declare {key}=false")

    checksums = package_root / "SHA256SUMS.txt"
    if not checksums.is_file() or checksums.is_symlink():
        raise EvidenceError("SHA256SUMS.txt must be a direct regular file")
    try:
        checksum_size = checksums.stat().st_size
    except OSError as exc:
        raise EvidenceError("SHA256SUMS.txt size is unavailable") from exc
    if checksum_size <= 0 or checksum_size > MAX_CHECKSUM_BYTES:
        raise EvidenceError("SHA256SUMS.txt size is outside the accepted bound")
    try:
        text = checksums.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise EvidenceError("SHA256SUMS.txt is unavailable or invalid UTF-8") from exc

    matches: list[str] = []
    seen_paths: set[str] = set()
    for raw_line in text.splitlines():
        if not raw_line:
            continue
        if "  " not in raw_line:
            raise EvidenceError("SHA256SUMS.txt contains a malformed line")
        digest, rel = raw_line.split("  ", 1)
        digest = digest.lower()
        if not HEX64.fullmatch(digest) or not rel:
            raise EvidenceError("SHA256SUMS.txt contains a malformed entry")
        if rel in seen_paths:
            raise EvidenceError(f"SHA256SUMS.txt contains duplicate path: {rel}")
        seen_paths.add(rel)
        if rel == CHECKSUM_PATH:
            matches.append(digest)
    if len(matches) != 1:
        raise EvidenceError("checksum inventory must contain exactly one AccessibleChess.exe entry")

    actual = _sha256_file(exe)
    if actual != matches[0]:
        raise EvidenceError("AccessibleChess.exe does not match canonical checksum inventory")


def _verify_evidence(evidence: dict[str, Any], expected_sha: str) -> None:
    evidence_sha = evidence.get("product_sha")
    if not isinstance(evidence_sha, str) or evidence_sha.lower() != expected_sha:
        raise EvidenceError("evidence product_sha does not match expected product SHA")

    for key in (
        "static_document_outside_edit",
        "static_text_visible_rectangle",
        "native_copy_focus_verified",
        "foreground_product_verified",
        "manifest_product_sha_verified",
        "executable_checksum_verified",
        "textpattern_selection_supported",
        "textpattern_target_selected",
        "ctrl_c_exact_clipboard",
        "move_input_focus_verified",
        "move_input_native_ctrl_a_ctrl_c",
    ):
        _require_true(evidence, key)

    copied = evidence.get("static_document_text")
    if not isinstance(copied, str) or not copied.strip() or len(copied) > 4096:
        raise EvidenceError("static document copy evidence text is missing or unbounded")

    if (
        evidence.get("textpattern_selection_equality")
        != "UIA exact range endpoints and case-sensitive text equality"
    ):
        raise EvidenceError("TextPattern selection equality contract is not exact")

    if evidence.get("clipboard_equality") != "case-sensitive exact string equality":
        raise EvidenceError("clipboard equality contract is not exact")

    for key in ("human_tested", "nvda_verified"):
        if evidence.get(key) is not False:
            raise EvidenceError(f"machine evidence must explicitly declare {key}=false")


def verify(evidence_path: Path, product_root: Path, product_sha: str) -> None:
    expected_sha = _canonical_expected_sha(product_sha)
    _verify_package_binding(product_root, expected_sha)
    evidence = _read_json(evidence_path)
    _verify_evidence(evidence, expected_sha)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify P0 packaged semantic document-copy evidence")
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--product-root", required=True, type=Path)
    parser.add_argument("--product-sha", required=True)
    args = parser.parse_args()
    try:
        verify(args.evidence, args.product_root, args.product_sha)
    except EvidenceError as exc:
        print(f"P0 PACKAGED DOCUMENT COPY EVIDENCE FAIL: {exc}")
        return 1
    print("P0 PACKAGED DOCUMENT COPY EVIDENCE VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
