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
    DEFAULT_SOUND_MANIFEST,
    DEFAULT_SOUND_RELATIVE_DIR,
    PackagedSoundAssetResolver,
    SOUND_MANIFEST_SCHEMA_VERSION,
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
    Path("web") / "version2_release_bootstrap.js",
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

    try:
        return json.loads(text, object_pairs_hook=hook)
    except Version2ReleasePayloadError:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise Version2ReleasePayloadError(f"{label} is invalid JSON") from exc


def _validate_sound_pack(product_dir: Path) -> None:
    manifest_path = product_dir / DEFAULT_SOUND_RELATIVE_DIR / DEFAULT_SOUND_MANIFEST
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
    if len(expected_events) != 9 or set(mapping) != expected_events:
        raise Version2ReleasePayloadError(
            "sound manifest must declare exactly all nine semantic sound events"
        )

    seen_assets: set[str] = set()
    for event in SoundEvent:
        value = mapping.get(event.value)
        if not isinstance(value, str) or not value.strip() or "\\" in value or "\x00" in value:
            raise Version2ReleasePayloadError(f"sound manifest entry is invalid: {event.value}")
        token = PurePosixPath(value)
        if token.is_absolute() or ".." in token.parts or token.as_posix() != value:
            raise Version2ReleasePayloadError(f"sound asset path is unsafe: {event.value}")
        if token.suffix.casefold() != ".wav":
            raise Version2ReleasePayloadError(f"sound asset is not WAV: {event.value}")
        folded = token.as_posix().casefold()
        if folded in seen_assets:
            raise Version2ReleasePayloadError("sound events must use distinct WAV assets")
        seen_assets.add(folded)

    try:
        manifest = PackagedSoundAssetResolver(product_dir).load_manifest()
    except Exception as exc:
        raise Version2ReleasePayloadError(
            "sound pack does not satisfy the production resolver contract"
        ) from exc
    if set(manifest.files) != set(SoundEvent):
        raise Version2ReleasePayloadError("production sound resolver did not resolve all events")

    for path in manifest.files.values():
        try:
            with wave.open(str(path), "rb") as reader:
                channels = reader.getnchannels()
                frame_count = reader.getnframes()
                if reader.getcomptype() != "NONE" or reader.getsampwidth() != 2:
                    raise Version2ReleasePayloadError("release sounds must be 16-bit PCM WAV")
                if channels <= 0 or frame_count <= 0 or reader.getframerate() <= 0:
                    raise Version2ReleasePayloadError("release sound WAV is empty or invalid")
                frames = reader.readframes(frame_count)
                if len(frames) != frame_count * channels * 2:
                    raise Version2ReleasePayloadError("release sound WAV is truncated")
        except Version2ReleasePayloadError:
            raise
        except (OSError, EOFError, wave.Error) as exc:
            raise Version2ReleasePayloadError("release sound WAV is unreadable") from exc


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
    if len(expected_events) != 9 or set(events) != expected_events:
        raise Version2ReleasePayloadError(
            "sound provenance must declare exactly all nine semantic sound events"
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


def _reject_raw_source(product_dir: Path) -> None:
    for path in product_dir.rglob("*"):
        if path.is_file() and path.suffix.casefold() in _RAW_SOURCE_SUFFIXES:
            raise Version2ReleasePayloadError("prepared standalone contains raw Python source")


def _require_standalone_contract(standalone: Path) -> None:
    executable = standalone / "AccessibleChess.exe"
    if not executable.is_file() or executable.stat().st_size <= 0:
        raise Version2ReleasePayloadError("standalone AccessibleChess.exe is missing or empty")
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
    ``manifest.json``, provenance identity, and exactly all nine WAV events.
    """

    standalone = Path(standalone_dir)
    stockfish_archive = Path(stockfish_release_archive)
    sounds = Path(sound_pack_dir)
    output = Path(output_root)

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
        _validate_sound_pack(product)
        _publish_sound_provenance(product, notices)

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
