from __future__ import annotations

"""Fail-closed release inspection for the Accessible Chess Version 2 candidate.

Stage 1 keeps its existing :mod:`acs.release_preflight` contract unchanged.  V2
reuses the same package topology, Stockfish disclosure, sound-pack, inventory,
and checksum primitives, but validates the larger accepted V2 native-menu
profile.  This module does not build, publish, or mark NVDA acceptance.
"""

import argparse
import json
from pathlib import Path, PurePosixPath

from .release_preflight import (
    ReleasePreflightError,
    ReleasePreflightReport,
    _EXPECTED_RELEASE_LABEL,
    _EXPECTED_STOCKFISH_VERSION,
    _HUMAN_ONLY_UNPROVEN,
    _SHA40_RE,
    _fail,
    _inventory,
    _read_checksums,
    _read_json_object,
    _require_file,
    _sha256,
    _validate_sound_pack,
    _validate_third_party,
    _validate_topology,
)
from .stockfish_runtime import PACKAGED_STOCKFISH_RELATIVE_PATH


VERSION2_RELEASE_PROFILE = "version2"
VERSION2_NATIVE_MENU_NAME = "AccessibleChessFullProductMenu"
VERSION2_TOP_MENU_IDS: tuple[str, ...] = (
    "file",
    "game",
    "position",
    "pgn",
    "library",
    "import",
    "export",
    "engine",
    "analysis",
    "books",
    "settings",
    "help",
)


def _validate_version2_manifest(root: Path) -> tuple[str, str]:
    manifest = _read_json_object(
        _require_file(root, "RELEASE_MANIFEST.json"),
        label="release manifest",
    )
    if manifest.get("product") != "Accessible Chess":
        _fail("release manifest product identity mismatch")
    if manifest.get("release_profile") != VERSION2_RELEASE_PROFILE:
        _fail("release manifest must declare release_profile=version2")
    if manifest.get("label") != _EXPECTED_RELEASE_LABEL:
        _fail("release manifest label must remain waiting for user NVDA test")
    if manifest.get("nvda_verified") is not False:
        _fail("release manifest must state nvda_verified=false before human acceptance")
    if manifest.get("stockfish") != _EXPECTED_STOCKFISH_VERSION:
        _fail("release manifest Stockfish version mismatch")
    for field in ("native_menu_alt_arrows_enter_esc", "nvda_menu_usability"):
        if manifest.get(field) != _HUMAN_ONLY_UNPROVEN:
            _fail(
                "release manifest human-only gate must remain "
                f"{_HUMAN_ONLY_UNPROVEN}: {field}"
            )

    integration_sha = manifest.get("integration_sha")
    qa_commit = manifest.get("qa_commit")
    if (
        not isinstance(integration_sha, str)
        or not _SHA40_RE.fullmatch(integration_sha.casefold())
    ):
        _fail("release manifest integration_sha must be a 40-hex commit")
    if not isinstance(qa_commit, str) or not _SHA40_RE.fullmatch(qa_commit.casefold()):
        _fail("release manifest qa_commit must be a 40-hex commit")

    for field in (
        "strict_cross_process_uia",
        "packaged_e4_e9_clipboard_board_focus",
        "packaged_sound",
        "stockfish_runtime_lifecycle",
        "native_menu_automated_self_diagnostic",
    ):
        if manifest.get(field) != "PASS":
            _fail(f"release manifest automated gate is not PASS: {field}")
    return integration_sha.casefold(), qa_commit.casefold()


def _validate_version2_menu(root: Path) -> None:
    menu = _read_json_object(
        _require_file(root, "native-menu-self-diagnostic.json"),
        label="native menu diagnostic",
    )
    for field in (
        "host_exists",
        "menu_exists",
        "host_top_level",
        "parent_is_host",
        "main_menu_strip_is_menu",
        "installed",
    ):
        if menu.get(field) is not True:
            _fail(f"native menu diagnostic gate is not true: {field}")
    if menu.get("menu_name") != VERSION2_NATIVE_MENU_NAME:
        _fail("Version 2 native menu diagnostic menu identity mismatch")
    if not str(menu.get("accessible_role", "")).endswith("MenuBar"):
        _fail("native menu diagnostic accessible role mismatch")

    menu_ids = menu.get("menu_ids")
    if menu_ids != list(VERSION2_TOP_MENU_IDS):
        _fail("Version 2 native menu id inventory mismatch")
    commands = menu.get("commands")
    if not isinstance(commands, list) or len(commands) != len(VERSION2_TOP_MENU_IDS):
        _fail("Version 2 native menu command inventory mismatch")
    if any(not isinstance(value, str) or not value.strip() for value in commands):
        _fail("Version 2 native menu commands must be non-empty text")


def _validate_shared_packaged_uia(root: Path, integration_sha: str) -> None:
    """Require the same proven Stage-1 board UIA contract inside the V2 host."""

    summary = _read_json_object(
        _require_file(root, "packaged-uia-strict-summary.json"),
        label="packaged UIA strict summary",
    )
    if summary.get("product_sha") != integration_sha:
        _fail("packaged UIA summary product_sha does not match release integration_sha")
    if summary.get("classification") != "A" or summary.get("evidence_complete") is not True:
        _fail("packaged UIA summary is not classification A with complete evidence")
    app_pid = summary.get("app_pid")
    if isinstance(app_pid, bool) or not isinstance(app_pid, int) or app_pid <= 0:
        _fail("packaged UIA summary app_pid must be a positive integer")
    move_runtime_id = summary.get("move_runtime_id")
    if not isinstance(move_runtime_id, str) or not move_runtime_id.strip():
        _fail("packaged UIA summary move runtime identity is missing")

    expected = {
        "e4_fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        "black_e5_fen": "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2",
        "clipboard": "e9",
    }
    for field, value in expected.items():
        if summary.get(field) != value:
            _fail(f"packaged UIA summary evidence mismatch: {field}")
    for field in ("invalid_e9_fen_unchanged", "board_focus_continuity"):
        if summary.get(field) is not True:
            _fail(f"packaged UIA summary gate is not true: {field}")
    square_count = summary.get("semantic_square_count")
    if isinstance(square_count, bool) or square_count != 64:
        _fail("packaged UIA summary must prove exactly 64 semantic squares")
    if summary.get("raw_exception_noise") is not False:
        _fail("packaged UIA summary must prove no raw exception noise")


def inspect_version2_release_package(root: str | Path) -> ReleasePreflightReport:
    root_path = Path(root)
    if not root_path.is_dir():
        _fail("release package root is missing or not a directory")
    if root_path.is_symlink():
        _fail("release package root must not be a symbolic link")
    root_path = root_path.resolve()

    inventory = _inventory(root_path)
    _validate_topology(root_path, inventory)
    _require_file(root_path, "AccessibleChess/AccessibleChess.exe")
    stockfish_rel = PurePosixPath(
        "AccessibleChess", *PACKAGED_STOCKFISH_RELATIVE_PATH.parts
    ).as_posix()
    _require_file(root_path, stockfish_rel)
    _validate_sound_pack(root_path / "AccessibleChess")
    _validate_third_party(root_path)

    integration_sha, qa_commit = _validate_version2_manifest(root_path)
    _validate_version2_menu(root_path)
    _validate_shared_packaged_uia(root_path, integration_sha)

    checksums = _read_checksums(root_path)
    expected_checksum_paths = set(inventory) - {"SHA256SUMS.txt"}
    if set(checksums) != expected_checksum_paths:
        missing = sorted(expected_checksum_paths - set(checksums))
        unexpected = sorted(set(checksums) - expected_checksum_paths)
        detail: list[str] = []
        if missing:
            detail.append("missing=" + ",".join(missing))
        if unexpected:
            detail.append("unexpected=" + ",".join(unexpected))
        _fail("SHA256SUMS inventory mismatch: " + "; ".join(detail))
    for relative in sorted(checksums, key=str.casefold):
        path = root_path.joinpath(*PurePosixPath(relative).parts)
        if not path.is_file() or path.is_symlink():
            _fail(f"checksum target is missing or unsafe: {relative}")
        if _sha256(path) != checksums[relative]:
            _fail(f"checksum mismatch: {relative}")

    return ReleasePreflightReport(
        integration_sha,
        qa_commit,
        inventory,
        len(checksums),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect an assembled Accessible Chess Version 2 release tree"
    )
    parser.add_argument("package_root")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)
    try:
        report = inspect_version2_release_package(args.package_root)
    except ReleasePreflightError as exc:
        if args.json_output:
            print(
                json.dumps(
                    {"result": "FAIL", "error": str(exc)},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        else:
            print(f"VERSION 2 RELEASE PREFLIGHT FAIL: {exc}")
        return 2
    if args.json_output:
        payload = report.as_dict()
        payload["release_profile"] = VERSION2_RELEASE_PROFILE
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(
            "VERSION 2 RELEASE PREFLIGHT PASS: "
            f"{len(report.inventory)} files; {report.checksums_verified} checksums"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
