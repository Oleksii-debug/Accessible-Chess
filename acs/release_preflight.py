from __future__ import annotations

"""Fail-closed inspection of an assembled Accessible Chess release tree.

This module does not build or publish a candidate. It validates the filesystem
composition produced by the Windows release chain before an archive may be
considered a candidate: required resources, manifest truth, third-party source,
source-leak hygiene and complete deterministic SHA256 inventory.
"""

from dataclasses import dataclass
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import wave
import zipfile

from .sound_events import SoundEvent
from .sound_windows import PackagedSoundAssetResolver
from .stockfish_runtime import PACKAGED_STOCKFISH_RELATIVE_PATH


_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_SUFFIXES = {".py", ".pyc", ".pyo", ".ipynb"}
_FORBIDDEN_COMPONENTS = {
    ".git", ".pytest_cache", "__pycache__", "build", "build_parts10k",
    "build_snapshot_exact", "build_snapshot_parts", "dist", "package",
    "source", "tests",
}
_FORBIDDEN_BUILD_DEBUG_NAMES = {
    "nuitka-compilation-report.xml",
    "nuitka-crash-report.xml",
}
_FORBIDDEN_BUILD_DEBUG_SUFFIXES = {".pdb", ".dmp", ".log"}
_WINDOWS_RESERVED_BASENAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
_WINDOWS_FORBIDDEN_FILENAME_CHARS = frozenset('<>"|?*')
_ALLOWED_TOP_LEVEL_FILES = {
    "RELEASE_MANIFEST.json", "SHA256SUMS.txt", "native-menu-self-diagnostic.json",
    "packaged-uia-strict-summary.json",
}
_ALLOWED_TOP_LEVEL_DIRS = {"AccessibleChess", "THIRD_PARTY_NOTICES"}
_REQUIRED_SOUND_EVENTS = tuple(event.value for event in SoundEvent)
_REQUIRED_WEB_RESOURCES = (
    "web/index.html",
    "web/stage1_release_bootstrap.js",
    "web/stage1_board_actions.js",
)
_EXPECTED_RELEASE_LABEL = "NVDA TEST CANDIDATE — WAITING FOR USER TEST"
_EXPECTED_STOCKFISH_VERSION = "18"
_STOCKFISH_SOURCE_ROOT = "Stockfish-sf_18"
_MAX_STOCKFISH_SOURCE_ZIP_BYTES = 8 * 1024 * 1024
_MAX_STOCKFISH_SOURCE_ENTRIES = 4096
_MAX_STOCKFISH_SOURCE_MEMBER_BYTES = 16 * 1024 * 1024
_MAX_STOCKFISH_SOURCE_TOTAL_BYTES = 64 * 1024 * 1024
_HUMAN_ONLY_UNPROVEN = "HUMAN-ONLY UNPROVEN"


class ReleasePreflightError(RuntimeError):
    """Raised when a package violates a release composition invariant."""


class _DuplicateJsonObjectKey(ValueError):
    """Internal signal for ambiguous JSON object names at any depth."""


@dataclass(frozen=True)
class ReleasePreflightReport:
    integration_sha: str
    qa_commit: str
    inventory: tuple[str, ...]
    checksums_verified: int

    def as_dict(self) -> dict[str, object]:
        return {
            "integration_sha": self.integration_sha,
            "qa_commit": self.qa_commit,
            "inventory": list(self.inventory),
            "inventory_count": len(self.inventory),
            "checksums_verified": self.checksums_verified,
            "nvda_verified": False,
            "result": "PASS",
        }


def _fail(message: str):
    raise ReleasePreflightError(message)


def _relative_posix(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        _fail("package entry escapes release root")
    return PurePosixPath(*relative.parts).as_posix()


def _validate_windows_portable_component(part: str, *, label: str) -> None:
    if (
        part.endswith((" ", "."))
        or ":" in part
        or any(character in _WINDOWS_FORBIDDEN_FILENAME_CHARS for character in part)
        or any(ord(character) < 32 for character in part)
    ):
        _fail(f"{label} must be Windows-portable")
    basename = part.split(".", 1)[0].casefold()
    if basename in _WINDOWS_RESERVED_BASENAMES:
        _fail(f"{label} must be Windows-portable")


def _validate_relative_token(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail(f"{label} must be non-empty text")
    normalized = value.replace("\\", "/")
    token = PurePosixPath(normalized)
    if token.is_absolute() or normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        _fail(f"{label} must be relative")
    if any(part in {"", ".", ".."} for part in token.parts):
        _fail(f"{label} contains unsafe path components")
    for part in token.parts:
        _validate_windows_portable_component(part, label=label)
    canonical = token.as_posix()
    if canonical != normalized:
        _fail(f"{label} is not canonical")
    return canonical


def _validate_release_artifact_path(relative: str) -> None:
    path = PurePosixPath(relative)
    name = path.name.casefold()
    suffix = path.suffix.casefold()
    if name in _FORBIDDEN_BUILD_DEBUG_NAMES or suffix in _FORBIDDEN_BUILD_DEBUG_SUFFIXES:
        _fail("build/debug/privacy artifact is forbidden in release tree")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_object_without_duplicates(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonObjectKey
        result[key] = value
    return result


def _read_json_object(path: Path, *, label: str) -> dict[str, object]:
    try:
        data = json.loads(
            path.read_text(encoding="utf-8-sig"),
            object_pairs_hook=_json_object_without_duplicates,
        )
    except _DuplicateJsonObjectKey:
        _fail(f"{label} contains duplicate object keys")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _fail(f"{label} is unreadable or invalid JSON: {type(exc).__name__}")
    if not isinstance(data, dict):
        _fail(f"{label} must be a JSON object")
    return data


def _inventory(root: Path) -> tuple[str, ...]:
    entries: list[str] = []
    casefold_paths: dict[str, str] = {}
    for path in root.rglob("*"):
        relative = _validate_relative_token(_relative_posix(root, path), label="release path")
        parts = PurePosixPath(relative).parts
        if path.is_symlink():
            _fail(f"symbolic link is forbidden in release tree: {relative}")
        if any(part.casefold() in _FORBIDDEN_COMPONENTS for part in parts):
            _fail(f"stale/build/source component is forbidden: {relative}")
        folded = relative.casefold()
        previous = casefold_paths.get(folded)
        if previous is not None and previous != relative:
            _fail("case-insensitive path collision is forbidden in release tree")
        casefold_paths[folded] = relative
        if path.is_file():
            if path.suffix.casefold() in _SOURCE_SUFFIXES:
                _fail(f"raw product source is forbidden: {relative}")
            if "/" in relative:
                _validate_release_artifact_path(relative)
            entries.append(relative)
    return tuple(sorted(entries, key=lambda value: value.casefold()))


def _validate_topology(root: Path, inventory: tuple[str, ...]) -> None:
    top_dirs = {path.name for path in root.iterdir() if path.is_dir()}
    top_files = {path.name for path in root.iterdir() if path.is_file()}
    unexpected_dirs = sorted(top_dirs - _ALLOWED_TOP_LEVEL_DIRS)
    unexpected_files = sorted(top_files - _ALLOWED_TOP_LEVEL_FILES)
    if unexpected_dirs:
        _fail("unexpected top-level directories: " + ", ".join(unexpected_dirs))
    if unexpected_files:
        _fail("unexpected top-level files: " + ", ".join(unexpected_files))
    if (root / "AccessibleChess" / "AccessibleChess").exists():
        _fail("accidental double AccessibleChess directory nesting detected")
    exe_hits = [item for item in inventory if PurePosixPath(item).name.casefold() == "accessiblechess.exe"]
    if exe_hits != ["AccessibleChess/AccessibleChess.exe"]:
        _fail("release must contain exactly one canonical AccessibleChess.exe")


def _require_file(root: Path, relative: str, *, nonempty: bool = True) -> Path:
    relative = _validate_relative_token(relative, label="required release path")
    path = root.joinpath(*PurePosixPath(relative).parts)
    if not path.is_file():
        _fail(f"required release file missing: {relative}")
    if path.is_symlink():
        _fail(f"required release file must not be a symbolic link: {relative}")
    if nonempty and path.stat().st_size <= 0:
        _fail(f"required release file is empty: {relative}")
    return path


def _validate_web_resources(product_root: Path) -> None:
    for relative in _REQUIRED_WEB_RESOURCES:
        _require_file(product_root, relative)


def _validate_sound_pack(product_root: Path) -> None:
    manifest_path = product_root / "assets" / "sounds" / "manifest.json"
    data = _read_json_object(manifest_path, label="sound manifest")
    resolver = PackagedSoundAssetResolver(product_root)
    try:
        manifest = resolver.load_manifest()
    except Exception as exc:
        _fail(f"sound package is invalid: {type(exc).__name__}")
    mapping = data.get("files")
    if not isinstance(mapping, dict):
        _fail("sound manifest files must be an object")
    keys = tuple(sorted(str(key) for key in mapping))
    if keys != tuple(sorted(_REQUIRED_SOUND_EVENTS)):
        _fail("sound manifest must declare exactly the nine Stage1 events")
    resolved_names: set[str] = set()
    for event in SoundEvent:
        declared = mapping.get(event.value)
        canonical = _validate_relative_token(declared, label=f"sound asset {event.value}")
        if "/" in canonical:
            _fail(f"sound asset must be a direct file: {event.value}")
        if canonical.casefold() in resolved_names:
            _fail("sound manifest contains duplicate asset filenames")
        resolved_names.add(canonical.casefold())
        path = manifest.files[event]
        try:
            with wave.open(str(path), "rb") as wav:
                if wav.getnchannels() <= 0 or wav.getframerate() <= 0 or wav.getnframes() <= 0:
                    _fail(f"sound WAV has invalid audio metadata: {event.value}")
        except (wave.Error, EOFError, OSError):
            _fail(f"sound WAV is invalid: {event.value}")


def _zip_member_token(info: zipfile.ZipInfo) -> str:
    raw = info.filename[:-1] if info.is_dir() and info.filename.endswith("/") else info.filename
    canonical = _validate_relative_token(raw, label="Stockfish source ZIP entry")
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    if stat.S_IFMT(unix_mode) == stat.S_IFLNK:
        _fail(f"Stockfish source ZIP contains symbolic link: {canonical}")
    return canonical


def _validate_third_party(root: Path) -> None:
    source = _require_file(root, "THIRD_PARTY_NOTICES/Stockfish-18-source.zip")
    notice = _require_file(root, "THIRD_PARTY_NOTICES/NOTICE.txt")
    readme = _require_file(root, "THIRD_PARTY_NOTICES/README.txt")
    if source.stat().st_size > _MAX_STOCKFISH_SOURCE_ZIP_BYTES:
        _fail("Stockfish source archive is too large")
    try:
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            if not infos:
                _fail("Stockfish source archive is empty or corrupt")
            if len(infos) > _MAX_STOCKFISH_SOURCE_ENTRIES:
                _fail("Stockfish source archive has too many entries")
            total_uncompressed = 0
            for info in infos:
                if info.file_size > _MAX_STOCKFISH_SOURCE_MEMBER_BYTES:
                    _fail("Stockfish source archive member is too large")
                total_uncompressed += info.file_size
                if total_uncompressed > _MAX_STOCKFISH_SOURCE_TOTAL_BYTES:
                    _fail("Stockfish source archive uncompressed payload is too large")
            if archive.testzip() is not None:
                _fail("Stockfish source archive is empty or corrupt")
            names = [_zip_member_token(info) for info in infos]
            seen_names: set[str] = set()
            casefold_names: dict[str, str] = {}
            for name in names:
                if name in seen_names:
                    _fail("duplicate Stockfish source ZIP entry")
                seen_names.add(name)
                folded = name.casefold()
                previous = casefold_names.get(folded)
                if previous is not None and previous != name:
                    _fail("case-insensitive Stockfish source ZIP collision")
                casefold_names[folded] = name
            if any(
                name != _STOCKFISH_SOURCE_ROOT
                and not name.startswith(_STOCKFISH_SOURCE_ROOT + "/")
                for name in names
            ):
                _fail("Stockfish source archive must use the sf_18 source root")
            copying = f"{_STOCKFISH_SOURCE_ROOT}/Copying.txt"
            has_source_file = any(
                name.startswith(f"{_STOCKFISH_SOURCE_ROOT}/src/") and not info.is_dir()
                for name, info in zip(names, infos)
            )
            if copying not in names or not has_source_file:
                _fail("Stockfish source archive is incomplete for sf_18")
            license_text = archive.read(copying).decode("utf-8", errors="replace")
            if "GNU GENERAL PUBLIC LICENSE" not in license_text or "Version 3" not in license_text:
                _fail("Stockfish source archive GPLv3 license is missing")
    except (OSError, zipfile.BadZipFile):
        _fail("Stockfish source archive is not a valid ZIP")

    notices = (
        notice.read_text(encoding="utf-8-sig", errors="replace")
        + "\n"
        + readme.read_text(encoding="utf-8-sig", errors="replace")
    ).casefold()
    for token in ("stockfish", "18", "gpl", "source"):
        if token not in notices:
            _fail("Stockfish third-party notice/source disclosure is incomplete")


def _validate_manifest(root: Path) -> tuple[str, str]:
    manifest = _read_json_object(_require_file(root, "RELEASE_MANIFEST.json"), label="release manifest")
    if manifest.get("product") != "Accessible Chess":
        _fail("release manifest product identity mismatch")
    if manifest.get("label") != _EXPECTED_RELEASE_LABEL:
        _fail("release manifest label must remain waiting for user NVDA test")
    if manifest.get("nvda_verified") is not False:
        _fail("release manifest must state nvda_verified=false before human acceptance")
    if manifest.get("stockfish") != _EXPECTED_STOCKFISH_VERSION:
        _fail("release manifest Stockfish version mismatch")
    for field in ("native_menu_alt_arrows_enter_esc", "nvda_menu_usability"):
        if manifest.get(field) != _HUMAN_ONLY_UNPROVEN:
            _fail(f"release manifest human-only gate must remain {_HUMAN_ONLY_UNPROVEN}: {field}")
    integration_sha = manifest.get("integration_sha")
    qa_commit = manifest.get("qa_commit")
    if not isinstance(integration_sha, str) or not _SHA40_RE.fullmatch(integration_sha.casefold()):
        _fail("release manifest integration_sha must be a 40-hex commit")
    if not isinstance(qa_commit, str) or not _SHA40_RE.fullmatch(qa_commit.casefold()):
        _fail("release manifest qa_commit must be a 40-hex commit")
    for field in (
        "strict_cross_process_uia", "packaged_e4_e9_clipboard_board_focus", "packaged_sound",
        "stockfish_runtime_lifecycle", "native_menu_automated_self_diagnostic",
    ):
        if manifest.get(field) != "PASS":
            _fail(f"release manifest automated gate is not PASS: {field}")
    return integration_sha.casefold(), qa_commit.casefold()


def _validate_release_evidence(root: Path, integration_sha: str) -> None:
    menu = _read_json_object(
        _require_file(root, "native-menu-self-diagnostic.json"),
        label="native menu diagnostic",
    )
    for field in (
        "host_exists", "menu_exists", "host_top_level", "parent_is_host",
        "main_menu_strip_is_menu", "installed",
    ):
        if menu.get(field) is not True:
            _fail(f"native menu diagnostic gate is not true: {field}")
    if menu.get("menu_name") != "AccessibleChessMainMenu":
        _fail("native menu diagnostic menu identity mismatch")
    if not str(menu.get("accessible_role", "")).endswith("MenuBar"):
        _fail("native menu diagnostic accessible role mismatch")
    if menu.get("commands") != ["File", "Game", "Board", "Analysis", "Settings", "Help"]:
        _fail("native menu diagnostic command inventory mismatch")

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


def _read_checksums(root: Path) -> dict[str, str]:
    path = _require_file(root, "SHA256SUMS.txt")
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as exc:
        _fail(f"SHA256SUMS is unreadable: {type(exc).__name__}")
    result: dict[str, str] = {}
    casefold_paths: dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(r"([0-9A-Fa-f]{64})  (.+)", line)
        if match is None:
            _fail("SHA256SUMS contains a malformed line")
        digest = match.group(1).casefold()
        relative = _validate_relative_token(match.group(2), label="checksum path")
        if relative == "SHA256SUMS.txt":
            _fail("SHA256SUMS must not checksum itself")
        if relative in result:
            _fail(f"SHA256SUMS contains duplicate path: {relative}")
        folded = relative.casefold()
        previous = casefold_paths.get(folded)
        if previous is not None and previous != relative:
            _fail("case-insensitive path collision is forbidden in SHA256SUMS")
        casefold_paths[folded] = relative
        if not _SHA256_RE.fullmatch(digest):
            _fail("SHA256SUMS contains invalid digest")
        result[relative] = digest
    return result


def inspect_release_package(root: str | Path) -> ReleasePreflightReport:
    root_path = Path(root)
    if not root_path.is_dir():
        _fail("release package root is missing or not a directory")
    if root_path.is_symlink():
        _fail("release package root must not be a symbolic link")
    root_path = root_path.resolve()
    inventory = _inventory(root_path)
    _validate_topology(root_path, inventory)
    _require_file(root_path, "AccessibleChess/AccessibleChess.exe")
    stockfish_rel = PurePosixPath("AccessibleChess", *PACKAGED_STOCKFISH_RELATIVE_PATH.parts).as_posix()
    _require_file(root_path, stockfish_rel)
    _validate_web_resources(root_path / "AccessibleChess")
    _validate_sound_pack(root_path / "AccessibleChess")
    _validate_third_party(root_path)
    integration_sha, qa_commit = _validate_manifest(root_path)
    _validate_release_evidence(root_path, integration_sha)
    checksums = _read_checksums(root_path)
    expected_checksum_paths = set(inventory) - {"SHA256SUMS.txt"}
    if set(checksums) != expected_checksum_paths:
        missing = sorted(expected_checksum_paths - set(checksums))
        unexpected = sorted(set(checksums) - expected_checksum_paths)
        detail = []
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
    return ReleasePreflightReport(integration_sha, qa_commit, inventory, len(checksums))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect an assembled Accessible Chess release tree")
    parser.add_argument("package_root")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)
    try:
        report = inspect_release_package(args.package_root)
    except ReleasePreflightError as exc:
        if args.json_output:
            print(json.dumps({"result": "FAIL", "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        else:
            print(f"RELEASE PREFLIGHT FAIL: {exc}")
        return 2
    if args.json_output:
        print(json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True))
    else:
        print(f"RELEASE PREFLIGHT PASS: {len(report.inventory)} files; {report.checksums_verified} checksums")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
