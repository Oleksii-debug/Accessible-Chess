from __future__ import annotations

"""Prepare release-critical Version 2 runtime payloads before package assembly.

This module is deliberately narrower than the package assembler.  It does not
build the Windows executable, download anything, create a release manifest/ZIP,
or publish an artifact.  It takes already-produced local inputs, verifies the
pinned Stockfish release archive and canonical sound-pack contract, and stages
one immutable product/notices pair for the existing Version 2 package assembler.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import wave
import zipfile

from .sound_windows import PackagedSoundAssetResolver
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
_STOCKFISH_ARCHIVE_NOTICE = "Stockfish-18-windows-x86-64.zip"
_STOCKFISH_LICENSE_NOTICE = "Stockfish-COPYING.txt"
_STOCKFISH_PROVENANCE = "STOCKFISH_PROVENANCE.json"
_MAX_STOCKFISH_ARCHIVE_FILES = 8192
_MAX_STOCKFISH_ARCHIVE_UNCOMPRESSED = 2 * 1024 * 1024 * 1024
_RAW_SOURCE_SUFFIXES = {".py", ".pyc", ".pyo"}


class Version2ReleasePayloadError(RuntimeError):
    """Raised when release payload preparation cannot fail closed."""


@dataclass(frozen=True)
class PreparedVersion2ReleasePayload:
    root: Path
    product_dir: Path
    notices_dir: Path
    stockfish_executable: Path


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
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise Version2ReleasePayloadError("Stockfish archive contains an unsafe member name")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise Version2ReleasePayloadError("Stockfish archive contains path traversal")
    if path.parts and ":" in path.parts[0]:
        raise Version2ReleasePayloadError("Stockfish archive contains a drive-qualified path")
    mode = info.external_attr >> 16
    if mode and stat.S_ISLNK(mode):
        raise Version2ReleasePayloadError("Stockfish archive contains a symlink")
    return path


def _inspect_stockfish_archive(archive: Path) -> tuple[zipfile.ZipInfo, zipfile.ZipInfo]:
    if not archive.is_file():
        raise Version2ReleasePayloadError("Stockfish release archive is missing")
    if _sha256(archive) != OFFICIAL_STOCKFISH_18_WINDOWS_X64_SHA256:
        raise Version2ReleasePayloadError("Stockfish release archive SHA-256 mismatch")

    try:
        handle = zipfile.ZipFile(archive, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise Version2ReleasePayloadError("Stockfish release archive is invalid") from exc

    with handle:
        files = [info for info in handle.infolist() if not info.is_dir()]
        if not files or len(files) > _MAX_STOCKFISH_ARCHIVE_FILES:
            raise Version2ReleasePayloadError("Stockfish archive file-count limit exceeded")
        total = sum(info.file_size for info in files)
        if total <= 0 or total > _MAX_STOCKFISH_ARCHIVE_UNCOMPRESSED:
            raise Version2ReleasePayloadError("Stockfish archive size limit exceeded")

        names: set[str] = set()
        executables: list[zipfile.ZipInfo] = []
        licenses: list[zipfile.ZipInfo] = []
        has_source = False
        for info in files:
            path = _safe_zip_name(info)
            folded = "/".join(path.parts).casefold()
            if folded in names:
                raise Version2ReleasePayloadError("Stockfish archive has duplicate member names")
            names.add(folded)
            basename = path.name.casefold()
            if basename.startswith("stockfish") and basename.endswith(".exe"):
                executables.append(info)
            if basename in {"copying.txt", "copying", "license.txt", "license"}:
                licenses.append(info)
            if "src" in {part.casefold() for part in path.parts} and path.suffix.casefold() in {
                ".cpp",
                ".h",
                ".hpp",
            }:
                has_source = True

        if len(executables) != 1:
            raise Version2ReleasePayloadError("Stockfish archive must contain exactly one engine executable")
        if not licenses:
            raise Version2ReleasePayloadError("Stockfish archive is missing its license")
        if not has_source:
            raise Version2ReleasePayloadError("Stockfish archive is missing corresponding source")

        executable = executables[0]
        prefix = handle.read(executable, pwd=None)[:2]
        if prefix != b"MZ":
            raise Version2ReleasePayloadError("Stockfish executable is not a Windows PE image")
        return executable, licenses[0]


def _copy_verified_stockfish(
    archive: Path,
    product_dir: Path,
    notices_dir: Path,
) -> Path:
    executable_info, license_info = _inspect_stockfish_archive(archive)
    destination = product_dir / PACKAGED_STOCKFISH_RELATIVE_PATH
    destination.parent.mkdir(parents=True, exist_ok=False)

    with zipfile.ZipFile(archive, "r") as handle:
        executable_bytes = handle.read(executable_info)
        license_bytes = handle.read(license_info)
    if not executable_bytes or executable_bytes[:2] != b"MZ":
        raise Version2ReleasePayloadError("Stockfish executable payload is invalid")
    if not license_bytes.strip():
        raise Version2ReleasePayloadError("Stockfish license payload is empty")

    destination.write_bytes(executable_bytes)
    shutil.copy2(archive, notices_dir / _STOCKFISH_ARCHIVE_NOTICE)
    (notices_dir / _STOCKFISH_LICENSE_NOTICE).write_bytes(license_bytes)
    provenance = {
        "schema_version": 1,
        "product": "Stockfish",
        "version": 18,
        "tag": OFFICIAL_STOCKFISH_18_TAG,
        "upstream_commit": OFFICIAL_STOCKFISH_18_COMMIT,
        "release_asset": OFFICIAL_STOCKFISH_18_WINDOWS_X64_ARCHIVE,
        "release_asset_sha256": OFFICIAL_STOCKFISH_18_WINDOWS_X64_SHA256,
        "packaged_executable_sha256": hashlib.sha256(executable_bytes).hexdigest(),
    }
    (notices_dir / _STOCKFISH_PROVENANCE).write_text(
        json.dumps(provenance, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def _validate_sound_pack(product_dir: Path) -> None:
    try:
        manifest = PackagedSoundAssetResolver(product_dir).load_manifest()
    except Exception as exc:
        raise Version2ReleasePayloadError("sound pack does not satisfy the canonical manifest contract") from exc

    for path in manifest.files.values():
        try:
            with wave.open(str(path), "rb") as reader:
                if reader.getsampwidth() != 2:
                    raise Version2ReleasePayloadError("release sounds must be 16-bit PCM WAV")
                if reader.getnframes() <= 0 or reader.getframerate() <= 0:
                    raise Version2ReleasePayloadError("release sound WAV is empty or invalid")
                reader.readframes(1)
        except Version2ReleasePayloadError:
            raise
        except (OSError, EOFError, wave.Error) as exc:
            raise Version2ReleasePayloadError("release sound WAV is unreadable") from exc


def _reject_raw_source(product_dir: Path) -> None:
    for path in product_dir.rglob("*"):
        if path.is_file() and path.suffix.casefold() in _RAW_SOURCE_SUFFIXES:
            raise Version2ReleasePayloadError("prepared standalone contains raw Python source")


def prepare_version2_release_payload(
    standalone_dir: str | Path,
    stockfish_release_archive: str | Path,
    sound_pack_dir: str | Path,
    output_root: str | Path,
) -> PreparedVersion2ReleasePayload:
    """Atomically stage one complete runtime payload for the V2 package assembler.

    Inputs are local, already-produced artifacts.  The Stockfish archive is pinned
    to the official Stockfish 18 generic Windows x86-64 release digest; callers
    cannot override that identity.  ``sound_pack_dir`` must contain the canonical
    ``manifest.json`` and all nine WAVs at its root.
    """

    standalone = Path(standalone_dir)
    stockfish_archive = Path(stockfish_release_archive)
    sounds = Path(sound_pack_dir)
    output = Path(output_root)

    if output.exists():
        raise Version2ReleasePayloadError("output payload root already exists")
    _require_clean_source_tree(standalone, label="standalone")
    _require_clean_source_tree(sounds, label="sound pack")
    if not (standalone / "AccessibleChess.exe").is_file():
        raise Version2ReleasePayloadError("standalone AccessibleChess.exe is missing")
    if not (standalone / "web" / "index.html").is_file():
        raise Version2ReleasePayloadError("standalone web/index.html is missing")
    if (standalone / PACKAGED_STOCKFISH_RELATIVE_PATH).exists():
        raise Version2ReleasePayloadError("standalone already contains a Stockfish payload")
    if (standalone / "assets" / "sounds").exists():
        raise Version2ReleasePayloadError("standalone already contains a sound payload")

    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.payload-", dir=parent))
    try:
        product = staging / _PREPARED_PRODUCT_DIR
        notices = staging / _PREPARED_NOTICES_DIR
        _copy_tree_without_links(standalone, product)
        notices.mkdir()

        sound_destination = product / "assets" / "sounds"
        sound_destination.parent.mkdir(parents=True, exist_ok=True)
        _copy_tree_without_links(sounds, sound_destination)
        _validate_sound_pack(product)

        stockfish_executable = _copy_verified_stockfish(
            stockfish_archive,
            product,
            notices,
        )
        resolved = resolve_stockfish_path(StockfishRuntimeConfig(application_dir=product))
        if resolved != stockfish_executable.resolve():
            raise Version2ReleasePayloadError("packaged Stockfish resolver disagrees with staged payload")
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
