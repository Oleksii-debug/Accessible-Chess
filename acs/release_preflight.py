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
_ALLOWED_TOP_LEVEL_FILES = {
    "RELEASE_MANIFEST.json", "SHA256SUMS.txt", "native-menu-self-diagnostic.json",
    "packaged-uia-strict-summary.json", "nuitka-compilation-report.xml",
}
_ALLOWED_TOP_LEVEL_DIRS = {"AccessibleChess", "THIRD_PARTY_NOTICES"}
_REQUIRED_SOUND_EVENTS = tuple(event.value for event in SoundEvent)
_EXPECTED_RELEASE_LABEL = "NVDA TEST CANDIDATE — WAITING FOR USER TEST"
_EXPECTED_STOCKFISH_VERSION = "18"
_STOCKFISH_SOURCE_ROOT = "Stockfish-sf_18"
_HUMAN_ONLY_UNPROVEN = "HUMAN-ONLY UNPROVEN"


class ReleasePreflightError(RuntimeError):
    """Raised when a package violates a release composition invariant."""


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


def _validate_relative_token(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail(f"{label} must be non-empty text")
    normalized = value.replace("\\", "/")
    token = PurePosixPath(normalized)
    if token.is_absolute() or normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        _fail(f"{label} must be relative")
    if any(part in {"", ".", ".."} for part in token.parts):
        _fail(f"{label} contains unsafe path components")
    canonical = token.as_posix()
    if canonical != normalized:
        _fail(f"{label} is not canonical")
    return canonical


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json_object(path: Path, *, label: str) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _fail(f"{label} is unreadable or invalid JSON: {type(exc).__name__}")
    if not isinstance(data, dict):
        _fail(f"{label} must be a JSON object")
    return data


def _inventory(root: Path) -> tuple[str, ...]:
    entries: list[str] = []
    for path in root.rglob("*"):
        relative = _relative_posix(root, path)
        parts = PurePosixPath(relative).parts
        if path.is_symlink():
            _fail(f"symbolic link is forbidden in release tree: {relative}")
        if any(part.casefold() in _FORBIDDEN_COMPONENTS for part in parts):
            _fail(f"stale/build/source component is forbidden: {relative}")
        if path.is_file():
            if path.suffix.casefold() in _SOURCE_SUFFIXES:
                _fail(f"raw product source is forbidden: {relative}")
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


def _validate_sound_pack(product_root: Path) -> None:
    resolver = PackagedSoundAssetResolver(product_root)
    try:
        manifest = resolver.load_manifest()
    except Exception as exc:
        _fail(f"sound package is invalid: {type(exc).__name__}")
    manifest_path = product_root / "assets" / "sounds" / "manifest.json"
    data = _read_json_object(manifest_path, label="sound manifest")
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
    try:
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            if not infos or archive.testzip() is not None:
                _fail("Stockfish source archive is empty or corrupt")
            names = [_zip_member_token(info) for info in infos]
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
    if str(manifest.get("stockfish", "")) != _EXPECTED_STOCKFISH_VERSION:
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


def _read_checksums(root: Path) -> dict[str, str]:
    path = _require_file(root, "SHA256SUMS.txt")
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as exc:
        _fail(f"SHA256SUMS is unreadable: {type(exc).__name__}")
    result: dict[str, str] = {}
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
    _require_file(root_path, "native-menu-self-diagnostic.json")
    _require_file(root_path, "packaged-uia-strict-summary.json")
    _validate_sound_pack(root_path / "AccessibleChess")
    _validate_third_party(root_path)
    integration_sha, qa_commit = _validate_manifest(root_path)
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
