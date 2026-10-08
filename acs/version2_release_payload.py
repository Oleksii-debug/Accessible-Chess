from __future__ import annotations

"""Prepare release-critical Version 2 runtime payloads before package assembly.

This module is deliberately narrower than the package assembler. It does not
build the Windows executable, download anything, create a release manifest/ZIP,
or publish an artifact. It takes already-produced local inputs, verifies the
pinned Stockfish release archive and canonical sound-pack contract, and stages
one immutable product/notices pair for the existing Version 2 package assembler.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import struct
import tempfile
import wave
import zipfile

from .sound_events import SoundEvent
from .sound_windows import (
    DEFAULT_SOUND_LAYERS_MANIFEST,
    DEFAULT_SOUND_MANIFEST,
    DEFAULT_SOUND_RELATIVE_DIR,
    DEFAULT_SOUND_VARIANTS_MANIFEST,
    PackagedSoundAssetResolver,
    SOUND_MANIFEST_SCHEMA_VERSION,
)
from .version2_package_preflight import (
    Version2PackagePreflightError,
    _passive_path,
    validate_winforms_accessibility_app_config,
)
from .stockfish_runtime import (
    PACKAGED_STOCKFISH_RELATIVE_PATH,
    StockfishRuntimeConfig,
    resolve_stockfish_path,
)


OFFICIAL_STOCKFISH_18_TAG = "sf_18"
OFFICIAL_STOCKFISH_18_COMMIT = "cb3d4ee9b47d0c5aae855b12379378ea1439675c"
OFFICIAL_STOCKFISH_18_WINDOWS_X64_ARCHIVE = "stockfish-windows-x86-64.zip"
OFFICIAL_STOCKFISH_18_WINDOWS_X64_SHA256 = (
    "40cc975817e7eee270b03f354810d20956df565420d320f6dd37d454dc81a139"
)

_PREPARED_PRODUCT_DIR = "prepared-product"
_PREPARED_NOTICES_DIR = "third-party-notices"
_STOCKFISH_SOURCE_NOTICE = "Stockfish-18-source.zip"
_STOCKFISH_LICENSE_NOTICE = "Stockfish-COPYING.txt"
_STOCKFISH_TEXT_NOTICE = "Stockfish-NOTICE.txt"
_STOCKFISH_PROVENANCE = "STOCKFISH_PROVENANCE.json"
_SOUND_PROVENANCE_SOURCE = "provenance.json"
_SOUND_PROVENANCE_NOTICE = "SOUND_PROVENANCE.json"
_SOUND_PROVENANCE_SCHEMA_VERSION = 1
_SOUND_INVENTORY_SOURCE = "inventory.json"
_SOUND_INVENTORY_NOTICE = "SOUND_INVENTORY.json"
_SOUND_INVENTORY_SCHEMA_VERSION = 1
_USER_SOUND_EXPECTED_WAV_COUNT = 330
_USER_SOUND_EXPECTED_INVENTORY_SHA256 = (
    "41f3223040e0720b2268e5c28f3ccec140a4f9d3386c12ffa7a82fc283a1f920"
)
_USER_SOUND_SOURCE = "urn:accessible-chess:user-upload:sound-archive:2026-10-03"
_USER_SOUND_LICENSE_ID = "USER_PROVIDED"
_USER_SOUND_CREATOR = "User-provided legacy chess sound archive"
_MAX_SOUND_INVENTORY_BYTES = 4 * 1024 * 1024
_MAX_SOUND_LIBRARY_WAV_BYTES = 512 * 1024 * 1024
_MAX_SOUND_FILE_BYTES = 64 * 1024 * 1024
_PROVENANCE_PLACEHOLDERS = frozenset({"unknown", "unlicensed", "tbd", "todo", "none", "n/a"})
_MAX_STOCKFISH_ARCHIVE_FILES = 8192
_MAX_STOCKFISH_ARCHIVE_UNCOMPRESSED = 2 * 1024 * 1024 * 1024
_RAW_SOURCE_SUFFIXES = {".py", ".pyc", ".pyo"}
_SOURCE_CODE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".inc",
}
_REQUIRED_WINFORMS_APPCONFIG = Path("AccessibleChess.exe.config")
_REQUIRED_WEB_FILES = (
    Path("web") / "index.html",
    Path("web") / "stage1_release_bootstrap.js",
    Path("web") / "stage1_board_actions.js",
    Path("web") / "full_product_pgn.js",
    Path("web") / "full_product_library.js",
    Path("web") / "full_product_books_training.js",
    Path("web") / "full_product_teacher.js",
    Path("web") / "full_product_education.js",
    Path("web") / "version2_final_product_bootstrap.js",
    Path("web") / "version2_local_profile.js",
    Path("web") / "p0_accessibility_runtime.js",
    Path("web") / "version2_release_bootstrap.js",
    Path("web") / "protection_locked.html",
    Path("web") / "protection_locked.js",
    Path("web") / "docs" / "ACCESSIBLE_CHESS_HOTKEYS_UK.txt",
    Path("web") / "docs" / "ACCESSIBLE_CHESS_CAPABILITIES_TESTING_UK.txt",
)
_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


class Version2ReleasePayloadError(RuntimeError):
    """Raised when release payload preparation cannot fail closed."""


@dataclass(frozen=True)
class PreparedVersion2ReleasePayload:
    root: Path
    product_dir: Path
    notices_dir: Path
    stockfish_executable: Path


@dataclass(frozen=True)
class _StockfishArchiveContents:
    executable: zipfile.ZipInfo
    license: zipfile.ZipInfo
    source_members: tuple[zipfile.ZipInfo, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_clean_source_tree(root: Path, *, label: str) -> None:
    if not root.is_dir():
        raise Version2ReleasePayloadError(f"{label} directory is missing")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise Version2ReleasePayloadError(f"{label} contains a symlink")


def _copy_tree_without_links(source: Path, destination: Path) -> None:
    _require_clean_source_tree(source, label="source")
    shutil.copytree(source, destination, symlinks=False)


def _safe_zip_name(info: zipfile.ZipInfo) -> PurePosixPath:
    name = info.filename
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or "\x00" in name
        or info.flag_bits & 0x1
    ):
        raise Version2ReleasePayloadError("Stockfish archive contains an unsafe member name")

    normalized_name = name[:-1] if info.is_dir() and name.endswith("/") else name
    if not normalized_name:
        raise Version2ReleasePayloadError("Stockfish archive contains an unsafe member name")
    raw_parts = normalized_name.split("/")
    if any(
        not part
        or part in {".", ".."}
        or ":" in part
        or part.rstrip(" .") != part
        or any(ord(character) < 32 or ord(character) == 127 for character in part)
        for part in raw_parts
    ):
        if ".." in raw_parts:
            raise Version2ReleasePayloadError("Stockfish archive contains path traversal")
        raise Version2ReleasePayloadError("Stockfish archive contains an unsafe member name")

    path = PurePosixPath(normalized_name)
    if path.is_absolute() or ".." in path.parts:
        raise Version2ReleasePayloadError("Stockfish archive contains path traversal")

    for part in path.parts:
        stem = part.split(".", 1)[0].casefold()
        if stem in _WINDOWS_RESERVED_NAMES:
            raise Version2ReleasePayloadError("Stockfish archive contains a Windows device path")

    mode = info.external_attr >> 16
    if mode and stat.S_ISLNK(mode):
        raise Version2ReleasePayloadError("Stockfish archive contains a symlink")
    return path


def _require_windows_x64_pe(data: bytes) -> None:
    if len(data) < 64 or data[:2] != b"MZ":
        raise Version2ReleasePayloadError("Stockfish executable is not a Windows PE image")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if pe_offset < 64 or pe_offset > len(data) - 26:
        raise Version2ReleasePayloadError("Stockfish executable has an invalid PE header offset")
    if data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise Version2ReleasePayloadError("Stockfish executable is missing the PE signature")

    coff_offset = pe_offset + 4
    machine, sections = struct.unpack_from("<HH", data, coff_offset)
    optional_size = struct.unpack_from("<H", data, coff_offset + 16)[0]
    characteristics = struct.unpack_from("<H", data, coff_offset + 18)[0]
    optional_offset = coff_offset + 20
    if machine != 0x8664:
        raise Version2ReleasePayloadError("Stockfish executable is not Windows x86-64")
    if sections <= 0 or not (characteristics & 0x0002):
        raise Version2ReleasePayloadError("Stockfish executable is not marked executable")
    if optional_size < 2 or optional_offset + optional_size > len(data):
        raise Version2ReleasePayloadError("Stockfish executable optional header is invalid")
    if struct.unpack_from("<H", data, optional_offset)[0] != 0x20B:
        raise Version2ReleasePayloadError("Stockfish executable is not PE32+ x86-64")


def _inspect_stockfish_archive(archive: Path) -> _StockfishArchiveContents:
    if not archive.is_file():
        raise Version2ReleasePayloadError("Stockfish release archive is missing")
    if _sha256(archive) != OFFICIAL_STOCKFISH_18_WINDOWS_X64_SHA256:
        raise Version2ReleasePayloadError("Stockfish release archive SHA-256 mismatch")

    try:
        handle = zipfile.ZipFile(archive, "r")
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise Version2ReleasePayloadError("Stockfish release archive is invalid") from exc

    with handle:
        entries = handle.infolist()
        if not entries or len(entries) > _MAX_STOCKFISH_ARCHIVE_FILES:
            raise Version2ReleasePayloadError("Stockfish archive entry-count limit exceeded")

        names: set[str] = set()
        files: list[zipfile.ZipInfo] = []
        for info in entries:
            path = _safe_zip_name(info)
            folded = path.as_posix().casefold()
            if folded in names:
                raise Version2ReleasePayloadError("Stockfish archive has duplicate member names")
            names.add(folded)
            if not info.is_dir():
                files.append(info)

        if not files:
            raise Version2ReleasePayloadError("Stockfish archive contains no files")
        total = sum(info.file_size for info in files)
        if total <= 0 or total > _MAX_STOCKFISH_ARCHIVE_UNCOMPRESSED:
            raise Version2ReleasePayloadError("Stockfish archive size limit exceeded")

        executables: list[zipfile.ZipInfo] = []
        licenses: list[zipfile.ZipInfo] = []
        source_members: list[zipfile.ZipInfo] = []
        has_source_code = False

        for info in files:
            path = _safe_zip_name(info)
            basename = path.name.casefold()
            if path.suffix.casefold() == ".exe":
                executables.append(info)
            if basename in {"copying.txt", "copying", "license.txt", "license"}:
                licenses.append(info)
            if "src" in {part.casefold() for part in path.parts}:
                source_members.append(info)
                if path.suffix.casefold() in _SOURCE_CODE_SUFFIXES:
                    has_source_code = True

        if len(executables) != 1:
            raise Version2ReleasePayloadError(
                "Stockfish archive must contain exactly one Windows engine executable"
            )
        executable = executables[0]
        executable_path = _safe_zip_name(executable)
        if not executable_path.name.casefold().startswith("stockfish"):
            raise Version2ReleasePayloadError("Stockfish archive executable identity is invalid")
        if not licenses:
            raise Version2ReleasePayloadError("Stockfish archive is missing its license")
        if not source_members or not has_source_code:
            raise Version2ReleasePayloadError("Stockfish archive is missing corresponding source")

        try:
            executable_bytes = handle.read(executable)
            license_bytes = handle.read(licenses[0])
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise Version2ReleasePayloadError("Stockfish archive payload is unreadable") from exc
        _require_windows_x64_pe(executable_bytes)
        if not license_bytes.strip():
            raise Version2ReleasePayloadError("Stockfish license payload is empty")

        return _StockfishArchiveContents(
            executable=executable,
            license=licenses[0],
            source_members=tuple(source_members),
        )


def _write_corresponding_source_archive(
    upstream: zipfile.ZipFile,
    source_members: tuple[zipfile.ZipInfo, ...],
    destination: Path,
) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for info in sorted(source_members, key=lambda item: item.filename.casefold()):
            path = _safe_zip_name(info)
            try:
                data = upstream.read(info)
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                raise Version2ReleasePayloadError(
                    "Stockfish corresponding source payload is unreadable"
                ) from exc
            member = zipfile.ZipInfo(path.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            member.compress_type = zipfile.ZIP_DEFLATED
            member.create_system = 3
            member.external_attr = 0o100644 << 16
            output.writestr(member, data)


def _copy_verified_stockfish(
    archive: Path,
    product_dir: Path,
    notices_dir: Path,
) -> Path:
    inspected = _inspect_stockfish_archive(archive)
    destination = product_dir / PACKAGED_STOCKFISH_RELATIVE_PATH
    destination.parent.mkdir(parents=True, exist_ok=False)

    with zipfile.ZipFile(archive, "r") as handle:
        try:
            executable_bytes = handle.read(inspected.executable)
            license_bytes = handle.read(inspected.license)
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise Version2ReleasePayloadError("Stockfish archive payload is unreadable") from exc
        _require_windows_x64_pe(executable_bytes)
        if not license_bytes.strip():
            raise Version2ReleasePayloadError("Stockfish license payload is empty")
        source_notice = notices_dir / _STOCKFISH_SOURCE_NOTICE
        _write_corresponding_source_archive(
            handle,
            inspected.source_members,
            source_notice,
        )

    destination.write_bytes(executable_bytes)
    (notices_dir / _STOCKFISH_LICENSE_NOTICE).write_bytes(license_bytes)
    notice = (
        "Stockfish 18\n"
        "License: GNU General Public License (GPL).\n"
        f"Upstream release tag: {OFFICIAL_STOCKFISH_18_TAG}\n"
        f"Upstream commit: {OFFICIAL_STOCKFISH_18_COMMIT}\n"
        f"Original release asset: {OFFICIAL_STOCKFISH_18_WINDOWS_X64_ARCHIVE}\n"
        f"Original release asset SHA-256: {OFFICIAL_STOCKFISH_18_WINDOWS_X64_SHA256}\n"
        f"Corresponding source: {_STOCKFISH_SOURCE_NOTICE}\n"
        f"License text: {_STOCKFISH_LICENSE_NOTICE}\n"
        "The corresponding source archive is derived only from the verified official "
        "release asset and preserves the upstream source file bytes.\n"
    )
    (notices_dir / _STOCKFISH_TEXT_NOTICE).write_text(notice, encoding="utf-8")

    provenance = {
        "schema_version": 1,
        "product": "Stockfish",
        "version": 18,
        "tag": OFFICIAL_STOCKFISH_18_TAG,
        "upstream_commit": OFFICIAL_STOCKFISH_18_COMMIT,
        "release_asset": OFFICIAL_STOCKFISH_18_WINDOWS_X64_ARCHIVE,
        "release_asset_sha256": OFFICIAL_STOCKFISH_18_WINDOWS_X64_SHA256,
        "packaged_executable_sha256": hashlib.sha256(executable_bytes).hexdigest(),
        "corresponding_source": _STOCKFISH_SOURCE_NOTICE,
        "corresponding_source_sha256": _sha256(notices_dir / _STOCKFISH_SOURCE_NOTICE),
        "license": _STOCKFISH_LICENSE_NOTICE,
        "notice": _STOCKFISH_TEXT_NOTICE,
    }
    (notices_dir / _STOCKFISH_PROVENANCE).write_text(
        json.dumps(provenance, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def _json_no_duplicates(text: str, *, label: str = "sound manifest") -> object:
    def hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise Version2ReleasePayloadError(f"{label} contains duplicate JSON keys")
            value[key] = item
        return value

    def reject_nonfinite(value: str) -> object:
        raise Version2ReleasePayloadError(
            f"{label} contains non-finite JSON number: {value}"
        )

    try:
        return json.loads(
            text,
            object_pairs_hook=hook,
            parse_constant=reject_nonfinite,
        )
    except Version2ReleasePayloadError:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise Version2ReleasePayloadError(f"{label} is invalid JSON") from exc


def _sound_inventory_token(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise Version2ReleasePayloadError("sound inventory file path is invalid")
    token = PurePosixPath(value)
    if (
        token.is_absolute()
        or token.as_posix() != value
        or len(token.parts) < 2
        or token.parts[0] != "library"
        or ".." in token.parts
    ):
        raise Version2ReleasePayloadError("sound inventory file path is unsafe")
    for part in token.parts:
        if (
            not part
            or part in {".", ".."}
            or ":" in part
            or part.rstrip(" .") != part
            or any(ord(character) < 32 or ord(character) == 127 for character in part)
            or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES
        ):
            raise Version2ReleasePayloadError("sound inventory file path is not Windows-portable")
    if token.suffix.casefold() != ".wav":
        raise Version2ReleasePayloadError("sound inventory entry is not WAV")
    return token.as_posix()


def _sound_inventory_sha256(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise Version2ReleasePayloadError("sound inventory SHA-256 is invalid")
    return value


def _validate_sound_inventory(
    sound_root: Path,
    runtime_paths: set[Path],
) -> dict[str, object] | None:
    inventory_path = sound_root / _SOUND_INVENTORY_SOURCE
    variants_present = (sound_root / DEFAULT_SOUND_VARIANTS_MANIFEST).is_file()
    inventory_present = inventory_path.is_file()
    if not inventory_present:
        if variants_present:
            raise Version2ReleasePayloadError(
                "sound variant catalog requires canonical sound inventory"
            )
        return None

    try:
        inventory_size = inventory_path.stat().st_size
    except OSError as exc:
        raise Version2ReleasePayloadError("sound inventory is unreadable") from exc
    if inventory_size <= 0 or inventory_size > _MAX_SOUND_INVENTORY_BYTES:
        raise Version2ReleasePayloadError("sound inventory size is invalid")
    try:
        raw = _json_no_duplicates(
            inventory_path.read_text(encoding="utf-8-sig"),
            label="sound inventory",
        )
    except OSError as exc:
        raise Version2ReleasePayloadError("sound inventory is unreadable") from exc
    if not isinstance(raw, dict):
        raise Version2ReleasePayloadError("sound inventory root must be an object")

    required_root = {
        "schema_version",
        "source",
        "license_id",
        "creator",
        "file_count",
        "source_inventory_sha256",
        "files",
    }
    optional_archive = {"source_archive_sha256", "source_archive_bytes"}
    keys = set(raw)
    if not required_root.issubset(keys) or not keys.issubset(required_root | optional_archive):
        raise Version2ReleasePayloadError("sound inventory root contract is invalid")
    archive_keys = keys & optional_archive
    if archive_keys and archive_keys != optional_archive:
        raise Version2ReleasePayloadError("sound inventory archive identity is incomplete")
    if type(raw.get("schema_version")) is not int or raw.get("schema_version") != _SOUND_INVENTORY_SCHEMA_VERSION:
        raise Version2ReleasePayloadError("sound inventory schema is invalid")
    if raw.get("source") != _USER_SOUND_SOURCE:
        raise Version2ReleasePayloadError("sound inventory source identity is invalid")
    if raw.get("license_id") != _USER_SOUND_LICENSE_ID:
        raise Version2ReleasePayloadError("sound inventory license identity is invalid")
    if raw.get("creator") != _USER_SOUND_CREATOR:
        raise Version2ReleasePayloadError("sound inventory creator identity is invalid")

    file_count = raw.get("file_count")
    files = raw.get("files")
    if type(file_count) is not int or file_count != _USER_SOUND_EXPECTED_WAV_COUNT:
        raise Version2ReleasePayloadError("sound inventory file count is invalid")
    if not isinstance(files, list) or len(files) != file_count:
        raise Version2ReleasePayloadError("sound inventory files list is invalid")
    declared_inventory_sha = _sound_inventory_sha256(raw.get("source_inventory_sha256"))
    if declared_inventory_sha != _USER_SOUND_EXPECTED_INVENTORY_SHA256:
        raise Version2ReleasePayloadError("sound inventory source identity does not match approved archive")

    normalized_files: list[dict[str, object]] = []
    by_path: dict[str, dict[str, object]] = {}
    total_bytes = 0
    sound_root_resolved = sound_root.resolve()

    for entry in files:
        expected_fields = {
            "file",
            "sha256",
            "bytes",
            "channels",
            "sample_width_bytes",
            "sample_rate",
            "frames",
            "duration_seconds",
            "compression",
        }
        if not isinstance(entry, dict) or set(entry) != expected_fields:
            raise Version2ReleasePayloadError("sound inventory entry contract is invalid")

        file_name = _sound_inventory_token(entry.get("file"))
        folded = file_name.casefold()
        if folded in by_path:
            raise Version2ReleasePayloadError("sound inventory contains duplicate file paths")
        digest = _sound_inventory_sha256(entry.get("sha256"))

        byte_count = entry.get("bytes")
        channels = entry.get("channels")
        sample_width = entry.get("sample_width_bytes")
        sample_rate = entry.get("sample_rate")
        frames = entry.get("frames")
        duration = entry.get("duration_seconds")
        compression = entry.get("compression")
        if (
            type(byte_count) is not int
            or byte_count < 45
            or byte_count > _MAX_SOUND_FILE_BYTES
            or type(channels) is not int
            or not 1 <= channels <= 64
            or type(sample_width) is not int
            or not 1 <= sample_width <= 8
            or type(sample_rate) is not int
            or not 1 <= sample_rate <= 768000
            or type(frames) is not int
            or frames < 1
            or isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or duration <= 0
            or not isinstance(compression, str)
            or not compression
            or len(compression) > 32
        ):
            raise Version2ReleasePayloadError("sound inventory audio metadata is invalid")
        expected_duration = round(frames / sample_rate, 6)
        if abs(float(duration) - expected_duration) > 0.000001:
            raise Version2ReleasePayloadError("sound inventory duration metadata is invalid")

        asset = sound_root.joinpath(*PurePosixPath(file_name).parts)
        try:
            if not asset.is_file() or asset.stat().st_size != byte_count:
                raise Version2ReleasePayloadError("sound inventory byte size mismatch")
            actual_digest = _sha256(asset)
        except OSError as exc:
            raise Version2ReleasePayloadError("sound inventory asset is unreadable") from exc
        if actual_digest != digest:
            raise Version2ReleasePayloadError("sound inventory SHA-256 mismatch")

        try:
            with wave.open(str(asset), "rb") as reader:
                actual_channels = reader.getnchannels()
                actual_sample_width = reader.getsampwidth()
                actual_sample_rate = reader.getframerate()
                actual_frames = reader.getnframes()
                actual_compression = reader.getcomptype()
                frame_bytes = reader.readframes(actual_frames)
        except (OSError, EOFError, wave.Error) as exc:
            raise Version2ReleasePayloadError("sound inventory WAV is unreadable") from exc
        if (
            actual_channels != channels
            or actual_sample_width != sample_width
            or actual_sample_rate != sample_rate
            or actual_frames != frames
            or actual_compression != compression
        ):
            raise Version2ReleasePayloadError("sound inventory WAV metadata mismatch")
        if len(frame_bytes) != actual_frames * actual_channels * actual_sample_width:
            raise Version2ReleasePayloadError("sound inventory WAV is truncated")

        total_bytes += byte_count
        if total_bytes > _MAX_SOUND_LIBRARY_WAV_BYTES:
            raise Version2ReleasePayloadError("sound inventory library byte limit exceeded")

        normalized = {
            "file": file_name,
            "sha256": digest,
            "bytes": byte_count,
            "channels": channels,
            "sample_width_bytes": sample_width,
            "sample_rate": sample_rate,
            "frames": frames,
            "duration_seconds": float(duration),
            "compression": compression,
        }
        by_path[folded] = normalized
        normalized_files.append(normalized)

    actual_wavs: dict[str, str] = {}
    library = sound_root / "library"
    if not library.is_dir():
        raise Version2ReleasePayloadError("sound inventory library directory is missing")
    for path in library.rglob("*"):
        if not path.is_file() or path.suffix.casefold() != ".wav":
            continue
        try:
            relative = path.resolve().relative_to(sound_root_resolved).as_posix()
        except (OSError, ValueError) as exc:
            raise Version2ReleasePayloadError("sound inventory library path is unsafe") from exc
        canonical = _sound_inventory_token(relative)
        folded = canonical.casefold()
        if folded in actual_wavs:
            raise Version2ReleasePayloadError("sound library contains case-colliding WAV paths")
        actual_wavs[folded] = canonical
    if set(actual_wavs) != set(by_path):
        raise Version2ReleasePayloadError("sound inventory does not exactly cover packaged WAV library")

    fingerprint_rows = []
    for item in sorted(normalized_files, key=lambda current: str(current["file"]).casefold()):
        source_relative = str(item["file"]).removeprefix("library/")
        fingerprint_rows.append(
            f'{source_relative}\0{item["sha256"]}\n'.encode("utf-8")
        )
    calculated_inventory_sha = hashlib.sha256(b"".join(fingerprint_rows)).hexdigest()
    if (
        calculated_inventory_sha != declared_inventory_sha
        or calculated_inventory_sha != _USER_SOUND_EXPECTED_INVENTORY_SHA256
    ):
        raise Version2ReleasePayloadError("sound inventory fingerprint mismatch")

    for path in runtime_paths:
        try:
            relative = path.resolve().relative_to(sound_root_resolved).as_posix()
        except (OSError, ValueError) as exc:
            raise Version2ReleasePayloadError("runtime sound asset escapes canonical inventory") from exc
        if _sound_inventory_token(relative).casefold() not in by_path:
            raise Version2ReleasePayloadError("runtime sound asset is absent from canonical inventory")

    normalized_root: dict[str, object] = {
        "schema_version": _SOUND_INVENTORY_SCHEMA_VERSION,
        "source": _USER_SOUND_SOURCE,
        "license_id": _USER_SOUND_LICENSE_ID,
        "creator": _USER_SOUND_CREATOR,
        "file_count": file_count,
        "source_inventory_sha256": declared_inventory_sha,
        "files": sorted(normalized_files, key=lambda item: str(item["file"]).casefold()),
    }
    if optional_archive.issubset(keys):
        archive_sha = _sound_inventory_sha256(raw.get("source_archive_sha256"))
        archive_bytes = raw.get("source_archive_bytes")
        if type(archive_bytes) is not int or archive_bytes < 1:
            raise Version2ReleasePayloadError("sound inventory source archive size is invalid")
        normalized_root["source_archive_sha256"] = archive_sha
        normalized_root["source_archive_bytes"] = archive_bytes
    return normalized_root


def _validate_sound_pack(product_dir: Path) -> dict[str, object] | None:
    sound_root = product_dir / DEFAULT_SOUND_RELATIVE_DIR
    manifest_path = sound_root / DEFAULT_SOUND_MANIFEST
    try:
        raw = _json_no_duplicates(manifest_path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise Version2ReleasePayloadError("sound manifest is unreadable") from exc
    if not isinstance(raw, dict):
        raise Version2ReleasePayloadError("sound manifest root must be an object")
    schema = raw.get("schema_version")
    if type(schema) is not int or schema != SOUND_MANIFEST_SCHEMA_VERSION:
        raise Version2ReleasePayloadError("sound manifest schema is invalid")
    mapping = raw.get("files")
    if not isinstance(mapping, dict):
        raise Version2ReleasePayloadError("sound manifest files must be an object")

    expected_events = {event.value for event in SoundEvent}
    if set(mapping) != expected_events:
        raise Version2ReleasePayloadError(
            "sound manifest must declare exactly all semantic sound events"
        )

    for event in SoundEvent:
        value = mapping.get(event.value)
        if not isinstance(value, str) or not value.strip() or "\\" in value or "\x00" in value:
            raise Version2ReleasePayloadError(f"sound manifest entry is invalid: {event.value}")
        token = PurePosixPath(value)
        if token.is_absolute() or ".." in token.parts or token.as_posix() != value:
            raise Version2ReleasePayloadError(f"sound asset path is unsafe: {event.value}")
        if token.suffix.casefold() != ".wav":
            raise Version2ReleasePayloadError(f"sound asset is not WAV: {event.value}")

    try:
        resolver = PackagedSoundAssetResolver(product_dir)
        manifest = resolver.load_manifest()
        variants = resolver.load_variant_catalog()
        layers = resolver.load_layer_catalog()
    except Exception as exc:
        raise Version2ReleasePayloadError(
            "sound pack does not satisfy the production resolver contract"
        ) from exc
    if set(manifest.files) != set(SoundEvent):
        raise Version2ReleasePayloadError("production sound resolver did not resolve all events")
    if set(variants) != set(SoundEvent):
        raise Version2ReleasePayloadError(
            "production sound variant catalog did not resolve all events"
        )

    runtime_paths = {
        *manifest.files.values(),
        *(option.path for options in variants.values() for option in options),
        *(
            path
            for by_variant in layers.values()
            for sequence in by_variant.values()
            for path in sequence
        ),
    }
    for path in runtime_paths:
        try:
            with wave.open(str(path), "rb") as reader:
                channels = reader.getnchannels()
                sample_width = reader.getsampwidth()
                frame_count = reader.getnframes()
                if reader.getcomptype() != "NONE" or sample_width not in {1, 2}:
                    raise Version2ReleasePayloadError(
                        "release sounds must be 8-bit or 16-bit PCM WAV"
                    )
                if channels <= 0 or frame_count <= 0 or reader.getframerate() <= 0:
                    raise Version2ReleasePayloadError("release sound WAV is empty or invalid")
                frames = reader.readframes(frame_count)
                if len(frames) != frame_count * channels * sample_width:
                    raise Version2ReleasePayloadError("release sound WAV is truncated")
        except Version2ReleasePayloadError:
            raise
        except (OSError, EOFError, wave.Error) as exc:
            raise Version2ReleasePayloadError("release sound WAV is unreadable") from exc

    return _validate_sound_inventory(sound_root, runtime_paths)


def _provenance_text(value: object, *, label: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise Version2ReleasePayloadError(f"sound provenance {label} must be text")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > max_length
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise Version2ReleasePayloadError(f"sound provenance {label} is invalid")
    return normalized


def _publish_sound_provenance(product_dir: Path, notices_dir: Path) -> None:
    sound_root = product_dir / DEFAULT_SOUND_RELATIVE_DIR
    provenance_path = sound_root / _SOUND_PROVENANCE_SOURCE
    manifest_path = sound_root / DEFAULT_SOUND_MANIFEST
    try:
        raw = _json_no_duplicates(
            provenance_path.read_text(encoding="utf-8-sig"),
            label="sound provenance",
        )
        manifest_raw = _json_no_duplicates(
            manifest_path.read_text(encoding="utf-8-sig"),
            label="sound manifest",
        )
    except OSError as exc:
        raise Version2ReleasePayloadError("sound provenance is missing or unreadable") from exc

    if not isinstance(raw, dict) or set(raw) != {"schema_version", "events"}:
        raise Version2ReleasePayloadError("sound provenance root contract is invalid")
    if raw.get("schema_version") != _SOUND_PROVENANCE_SCHEMA_VERSION:
        raise Version2ReleasePayloadError("sound provenance schema is invalid")
    events = raw.get("events")
    if not isinstance(events, dict):
        raise Version2ReleasePayloadError("sound provenance events must be an object")

    expected_events = {event.value for event in SoundEvent}
    if set(events) != expected_events:
        raise Version2ReleasePayloadError(
            "sound provenance must declare exactly all semantic sound events"
        )
    if not isinstance(manifest_raw, dict) or not isinstance(manifest_raw.get("files"), dict):
        raise Version2ReleasePayloadError("sound manifest files must be an object")
    mapping = manifest_raw["files"]

    normalized_events: dict[str, dict[str, str]] = {}
    for event in SoundEvent:
        entry = events.get(event.value)
        if not isinstance(entry, dict) or set(entry) != {
            "file",
            "sha256",
            "license_id",
            "source",
            "creator",
        }:
            raise Version2ReleasePayloadError(
                f"sound provenance entry contract is invalid: {event.value}"
            )

        file_name = _provenance_text(entry.get("file"), label="file", max_length=255)
        if file_name != mapping.get(event.value):
            raise Version2ReleasePayloadError(
                f"sound provenance file does not match manifest: {event.value}"
            )
        token = PurePosixPath(file_name)
        if token.is_absolute() or ".." in token.parts or token.as_posix() != file_name:
            raise Version2ReleasePayloadError(
                f"sound provenance file path is unsafe: {event.value}"
            )
        asset_path = sound_root / Path(*token.parts)

        digest = _provenance_text(entry.get("sha256"), label="sha256", max_length=64)
        if (
            len(digest) != 64
            or digest != digest.lower()
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise Version2ReleasePayloadError(
                f"sound provenance SHA-256 is invalid: {event.value}"
            )
        if not asset_path.is_file() or _sha256(asset_path) != digest:
            raise Version2ReleasePayloadError(
                f"sound provenance SHA-256 mismatch: {event.value}"
            )

        license_id = _provenance_text(
            entry.get("license_id"), label="license_id", max_length=128
        )
        if license_id.casefold() in _PROVENANCE_PLACEHOLDERS:
            raise Version2ReleasePayloadError(
                f"sound provenance license identity is unresolved: {event.value}"
            )
        source = _provenance_text(entry.get("source"), label="source", max_length=1024)
        if not (source.startswith("https://") or source.startswith("urn:")):
            raise Version2ReleasePayloadError(
                f"sound provenance source must be an HTTPS URL or URN: {event.value}"
            )
        creator = _provenance_text(entry.get("creator"), label="creator", max_length=512)
        if creator.casefold() in _PROVENANCE_PLACEHOLDERS:
            raise Version2ReleasePayloadError(
                f"sound provenance creator identity is unresolved: {event.value}"
            )

        normalized_events[event.value] = {
            "file": file_name,
            "sha256": digest,
            "license_id": license_id,
            "source": source,
            "creator": creator,
        }

    notice = {
        "schema_version": _SOUND_PROVENANCE_SCHEMA_VERSION,
        "events": normalized_events,
    }
    (notices_dir / _SOUND_PROVENANCE_NOTICE).write_text(
        json.dumps(notice, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    provenance_path.unlink()


def _publish_sound_inventory(
    notices_dir: Path,
    inventory: dict[str, object] | None,
) -> None:
    if inventory is None:
        return
    (notices_dir / _SOUND_INVENTORY_NOTICE).write_text(
        json.dumps(inventory, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _reject_raw_source(product_dir: Path) -> None:
    for path in product_dir.rglob("*"):
        if path.is_file() and path.suffix.casefold() in _RAW_SOURCE_SUFFIXES:
            raise Version2ReleasePayloadError("prepared standalone contains raw Python source")


def _require_standalone_contract(standalone: Path) -> None:
    executable = standalone / "AccessibleChess.exe"
    if not executable.is_file() or executable.stat().st_size <= 0:
        raise Version2ReleasePayloadError("standalone AccessibleChess.exe is missing or empty")
    app_config = standalone / _REQUIRED_WINFORMS_APPCONFIG
    if not app_config.is_file() or app_config.stat().st_size <= 0:
        raise Version2ReleasePayloadError(
            "standalone WinForms accessibility app-config is missing or empty"
        )
    try:
        validate_winforms_accessibility_app_config(app_config)
    except Version2PackagePreflightError as exc:
        raise Version2ReleasePayloadError(
            "standalone WinForms accessibility app-config is invalid"
        ) from exc
    for relative in _REQUIRED_WEB_FILES:
        path = standalone / relative
        if not path.is_file() or path.stat().st_size <= 0:
            raise Version2ReleasePayloadError(
                f"standalone required web resource is missing or empty: {relative.as_posix()}"
            )
    if (standalone / "engines" / "stockfish").exists():
        raise Version2ReleasePayloadError("standalone already contains a Stockfish payload")
    if (standalone / "assets" / "sounds").exists():
        raise Version2ReleasePayloadError("standalone already contains a sound payload")
    for path in standalone.rglob("*"):
        if path.is_file() and path.suffix.casefold() == ".exe":
            if path.name.casefold().startswith("stockfish"):
                raise Version2ReleasePayloadError(
                    "standalone contains a conflicting Stockfish executable"
                )
    _reject_raw_source(standalone)


def _reject_output_inside_input(output: Path, source: Path, *, label: str) -> None:
    output_resolved = output.resolve(strict=False)
    source_resolved = source.resolve(strict=False)
    if output_resolved == source_resolved or source_resolved in output_resolved.parents:
        raise Version2ReleasePayloadError(f"output payload root cannot be inside {label}")


def prepare_version2_release_payload(
    standalone_dir: str | Path,
    stockfish_release_archive: str | Path,
    sound_pack_dir: str | Path,
    output_root: str | Path,
) -> PreparedVersion2ReleasePayload:
    """Atomically stage one complete runtime payload for the V2 package assembler.

    Inputs are local, already-produced artifacts. The Stockfish archive is pinned
    to the official Stockfish 18 generic Windows x86-64 release digest; callers
    cannot override that identity. ``sound_pack_dir`` must contain the canonical
    ``manifest.json``, provenance identity, and the complete semantic sound-event set.
    """

    standalone = _passive_path(standalone_dir, label="standalone directory")
    stockfish_archive = _passive_path(
        stockfish_release_archive,
        label="Stockfish release archive",
    )
    sounds = _passive_path(sound_pack_dir, label="sound-pack directory")
    output = _passive_path(output_root, label="release payload output")

    if output.exists():
        raise Version2ReleasePayloadError("output payload root already exists")
    _require_clean_source_tree(standalone, label="standalone")
    _require_clean_source_tree(sounds, label="sound pack")
    _reject_output_inside_input(output, standalone, label="standalone")
    _reject_output_inside_input(output, sounds, label="sound pack")
    _require_standalone_contract(standalone)

    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.payload-", dir=parent))
    try:
        product = staging / _PREPARED_PRODUCT_DIR
        notices = staging / _PREPARED_NOTICES_DIR
        _copy_tree_without_links(standalone, product)
        notices.mkdir()

        sound_destination = product / DEFAULT_SOUND_RELATIVE_DIR
        sound_destination.parent.mkdir(parents=True, exist_ok=True)
        _copy_tree_without_links(sounds, sound_destination)
        sound_inventory = _validate_sound_pack(product)
        _publish_sound_provenance(product, notices)
        _publish_sound_inventory(notices, sound_inventory)

        stockfish_executable = _copy_verified_stockfish(
            stockfish_archive,
            product,
            notices,
        )
        resolved = resolve_stockfish_path(StockfishRuntimeConfig(application_dir=product))
        if resolved != stockfish_executable.resolve():
            raise Version2ReleasePayloadError(
                "packaged Stockfish resolver disagrees with staged payload"
            )
        _reject_raw_source(product)

        staging.replace(output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return PreparedVersion2ReleasePayload(
        root=output,
        product_dir=output / _PREPARED_PRODUCT_DIR,
        notices_dir=output / _PREPARED_NOTICES_DIR,
        stockfish_executable=output / _PREPARED_PRODUCT_DIR / PACKAGED_STOCKFISH_RELATIVE_PATH,
    )


__all__ = [
    "OFFICIAL_STOCKFISH_18_COMMIT",
    "OFFICIAL_STOCKFISH_18_TAG",
    "OFFICIAL_STOCKFISH_18_WINDOWS_X64_ARCHIVE",
    "OFFICIAL_STOCKFISH_18_WINDOWS_X64_SHA256",
    "PreparedVersion2ReleasePayload",
    "Version2ReleasePayloadError",
    "prepare_version2_release_payload",
]
