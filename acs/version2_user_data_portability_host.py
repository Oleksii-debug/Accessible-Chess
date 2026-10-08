from __future__ import annotations

"""Production Windows/startup host for Section 37 user-data portability.

The browser/action layer never receives filesystem paths. Native owned dialogs only
schedule work. Backup/export and restore/import execute on the next process start,
before Settings or SQLite writers are opened. Restore/import publication is kept
behind a rollback transaction until the canonical Version2UpgradeCoordinator has
validated the newly published root.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import stat
from collections.abc import Callable
import zipfile

from .user_data_portability import BundleKind
from .version2_upgrade import UserDataLayout

ARCHIVE_SCHEMA_VERSION = 1
PENDING_SCHEMA_VERSION = 1
MAX_FILES = 100_000
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
CHUNK = 1024 * 1024

_PRIVATE_TOKENS = (
    "credential", "secret", "token", "oauth", "oidc", "keyring",
    "private-key", "signing-key", "protection", "entitlement",
    "session", "cookie",
)
_WIN_BAD = set('<>:"/\\|?*')
_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class UserDataArchiveError(RuntimeError):
    """Stable fail-closed production archive error."""


class _DuplicateKey(ValueError):
    pass


def _unique_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise _DuplicateKey(key)
        out[key] = value
    return out


def _reparse(info: os.stat_result) -> bool:
    return bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _regular(path: Path, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise UserDataArchiveError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or _reparse(info) or not stat.S_ISREG(info.st_mode):
        raise UserDataArchiveError(f"{label} must be a regular file")
    return info


def _directory(path: Path, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise UserDataArchiveError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or _reparse(info) or not stat.S_ISDIR(info.st_mode):
        raise UserDataArchiveError(f"{label} must be a real directory")
    return info


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _validated_relative(relative: str) -> str:
    if type(relative) is not str or not relative or chr(0) in relative or "\\" in relative:
        raise UserDataArchiveError("archive path is unsafe")
    token = PurePosixPath(relative)
    if token.is_absolute() or token.as_posix() != relative or any(part in {"", ".", ".."} for part in token.parts):
        raise UserDataArchiveError("archive path is unsafe")
    for part in token.parts:
        if part[-1:] in {" ", "."} or any(ord(ch) < 32 or ch in _WIN_BAD for ch in part):
            raise UserDataArchiveError("archive path is not Windows-portable")
        if part.split(".", 1)[0].upper() in _WIN_RESERVED:
            raise UserDataArchiveError("archive path uses a reserved Windows name")
    return relative


def _portable(relative: str) -> bool:
    folded = relative.casefold()
    parts = PurePosixPath(relative).parts
    if any(token in folded for token in _PRIVATE_TOKENS):
        return False
    if parts and parts[0].casefold() in {"sound-cache", "cache", "tmp", "temp"}:
        return False
    return True


def _canonical_relative(root: Path, path: Path) -> str:
    try:
        rel = PurePosixPath(*path.relative_to(root).parts).as_posix()
    except ValueError as exc:
        raise UserDataArchiveError("user-data path escapes canonical root") from exc
    token = PurePosixPath(rel)
    if not rel or token.is_absolute() or any(part in {"", ".", ".."} for part in token.parts):
        raise UserDataArchiveError("user-data path is not canonical")
    return _validated_relative(rel)


def _iter_files(root: Path, *, portable: bool) -> tuple[tuple[str, Path, int], ...]:
    if not root.exists() and not root.is_symlink():
        return ()
    _directory(root, "user-data root")
    found = []
    for base, dirs, files in os.walk(root, topdown=True, followlinks=False):
        base_path = Path(base)
        _directory(base_path, "user-data directory")
        safe_dirs = []
        for name in sorted(dirs):
            child = base_path / name
            _directory(child, "user-data directory")
            safe_dirs.append(name)
        dirs[:] = safe_dirs
        for name in sorted(files):
            path = base_path / name
            info = _regular(path, "user-data file")
            relative = _canonical_relative(root, path)
            if portable and not _portable(relative):
                continue
            found.append((relative, path, int(info.st_size)))
            if len(found) > MAX_FILES:
                raise UserDataArchiveError("user-data file count exceeds limit")
    found.sort(key=lambda item: item[0])
    return tuple(found)


def _sha256_path(path: Path, *, limit: int = MAX_ARCHIVE_BYTES) -> tuple[str, int]:
    _regular(path, "archive file")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise UserDataArchiveError("archive exceeds byte limit")
            digest.update(chunk)
    return digest.hexdigest(), size


def _meta_root(layout: UserDataLayout) -> Path:
    return layout.root.parent / f".{layout.root.name}.portability"


def _pending_path(layout: UserDataLayout) -> Path:
    return _meta_root(layout) / "pending.json"


def _journal_path(layout: UserDataLayout) -> Path:
    return _meta_root(layout) / "restore-journal.json"


def _staged_archive_path(layout: UserDataLayout, digest: str) -> Path:
    return _meta_root(layout) / f"archive-{digest}.acdata"


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    temp = path.parent / f".{path.name}.tmp-{secrets.token_hex(8)}"
    try:
        with temp.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists() or temp.is_symlink():
            try:
                temp.unlink()
            except OSError:
                pass


def _read_json(path: Path, label: str) -> dict[str, object]:
    info = _regular(path, label)
    if info.st_size > MAX_MANIFEST_BYTES:
        raise UserDataArchiveError(f"{label} exceeds byte limit")
    try:
        value = json.loads(path.read_text("utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey) as exc:
        raise UserDataArchiveError(f"{label} is invalid") from exc
    if type(value) is not dict:
        raise UserDataArchiveError(f"{label} must be an object")
    return value


def _remove(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink():
        raise UserDataArchiveError("transaction path became a symlink")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def create_user_data_archive(root: Path, destination: Path, *, kind: BundleKind) -> dict[str, object]:
    if not isinstance(kind, BundleKind):
        raise TypeError("kind must be BundleKind")
    root = Path(root)
    destination = Path(destination)
    if _inside(destination, root):
        raise UserDataArchiveError("archive destination must be outside user-data root")
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = _iter_files(root, portable=(kind is BundleKind.PORTABLE))
    temp = destination.parent / f".{destination.name}.tmp-{secrets.token_hex(8)}"
    entries = []
    total = 0
    try:
        with zipfile.ZipFile(temp, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
            for relative, source, expected_size in files:
                before = _regular(source, "user-data file")
                digest = hashlib.sha256()
                copied = 0
                info = zipfile.ZipInfo(f"data/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                with source.open("rb") as reader, archive.open(info, "w") as writer:
                    while True:
                        chunk = reader.read(CHUNK)
                        if not chunk:
                            break
                        copied += len(chunk)
                        total += len(chunk)
                        if copied > expected_size or total > MAX_ARCHIVE_BYTES:
                            raise UserDataArchiveError("user data changed during archive capture")
                        digest.update(chunk)
                        writer.write(chunk)
                after = _regular(source, "user-data file")
                identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                if copied != expected_size or identity_before != identity_after:
                    raise UserDataArchiveError("user data changed during archive capture")
                entries.append({"path": relative, "size": copied, "sha256": digest.hexdigest()})
            manifest = {"schema": ARCHIVE_SCHEMA_VERSION, "kind": kind.value, "entries": entries}
            raw = (json.dumps(manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            if len(raw) > MAX_MANIFEST_BYTES:
                raise UserDataArchiveError("archive manifest exceeds byte limit")
            info = zipfile.ZipInfo("manifest.json", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, raw)
        digest, archive_bytes = _sha256_path(temp)
        if destination.exists() or destination.is_symlink():
            _regular(destination, "archive destination")
        os.replace(temp, destination)
        return {"kind": kind.value, "files": len(entries), "bytes": total, "archive_bytes": archive_bytes, "sha256": digest, "path": str(destination)}
    except BaseException:
        if temp.exists() or temp.is_symlink():
            try:
                temp.unlink()
            except OSError:
                pass
        raise


def validate_user_data_archive(path: Path, *, expected_kind: BundleKind | None = None) -> dict[str, object]:
    path = Path(path)
    info = _regular(path, "user-data archive")
    if info.st_size > MAX_ARCHIVE_BYTES:
        raise UserDataArchiveError("archive exceeds byte limit")
    try:
        archive = zipfile.ZipFile(path, "r", allowZip64=True)
    except (OSError, zipfile.BadZipFile) as exc:
        raise UserDataArchiveError("user-data archive is invalid") from exc
    with archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if len(names) != len(set(names)) or "manifest.json" not in names:
            raise UserDataArchiveError("archive entry set is invalid")
        manifest_info = archive.getinfo("manifest.json")
        if manifest_info.file_size > MAX_MANIFEST_BYTES:
            raise UserDataArchiveError("archive manifest exceeds byte limit")
        try:
            manifest = json.loads(archive.read(manifest_info).decode("utf-8"), object_pairs_hook=_unique_object)
        except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey) as exc:
            raise UserDataArchiveError("archive manifest is invalid") from exc
        if type(manifest) is not dict or set(manifest) != {"schema", "kind", "entries"}:
            raise UserDataArchiveError("archive manifest shape is invalid")
        if manifest["schema"] != ARCHIVE_SCHEMA_VERSION or manifest["kind"] not in {kind.value for kind in BundleKind}:
            raise UserDataArchiveError("archive schema or kind is unsupported")
        kind = BundleKind(manifest["kind"])
        if expected_kind is not None and kind is not expected_kind:
            raise UserDataArchiveError("archive kind mismatch")
        entries = manifest["entries"]
        if type(entries) is not list or len(entries) > MAX_FILES:
            raise UserDataArchiveError("archive entries are invalid")
        expected_names = {"manifest.json"}
        previous = ""
        total = 0
        for item in entries:
            if type(item) is not dict or set(item) != {"path", "size", "sha256"}:
                raise UserDataArchiveError("archive entry metadata is invalid")
            relative, size, digest = item["path"], item["size"], item["sha256"]
            if type(relative) is not str or type(size) is not int or type(digest) is not str:
                raise UserDataArchiveError("archive entry metadata types are invalid")
            _validated_relative(relative)
            if relative <= previous or size < 0 or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise UserDataArchiveError("archive entry ordering or identity is invalid")
            if kind is BundleKind.PORTABLE and not _portable(relative):
                raise UserDataArchiveError("portable archive contains private/local state")
            previous = relative
            total += size
            if total > MAX_ARCHIVE_BYTES:
                raise UserDataArchiveError("archive expanded size exceeds limit")
            member_name = f"data/{relative}"
            expected_names.add(member_name)
            try:
                member = archive.getinfo(member_name)
            except KeyError as exc:
                raise UserDataArchiveError("archive data entry is missing") from exc
            if member.is_dir() or member.file_size != size:
                raise UserDataArchiveError("archive data entry size is invalid")
            measured = hashlib.sha256()
            copied = 0
            with archive.open(member, "r") as reader:
                while True:
                    chunk = reader.read(CHUNK)
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > size:
                        raise UserDataArchiveError("archive data entry exceeds declared size")
                    measured.update(chunk)
            if copied != size or measured.hexdigest() != digest:
                raise UserDataArchiveError("archive data entry checksum mismatch")
        if set(names) != expected_names:
            raise UserDataArchiveError("archive contains undeclared entries")
        return manifest


def _extract(path: Path, target: Path, manifest: dict[str, object]) -> None:
    if target.exists() or target.is_symlink():
        raise UserDataArchiveError("restore staging path already exists")
    target.mkdir(parents=True)
    with zipfile.ZipFile(path, "r", allowZip64=True) as archive:
        for item in manifest["entries"]:
            relative = str(item["path"])
            output = target.joinpath(*PurePosixPath(relative).parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            copied = 0
            with archive.open(f"data/{relative}", "r") as reader, output.open("xb") as writer:
                while True:
                    chunk = reader.read(CHUNK)
                    if not chunk:
                        break
                    copied += len(chunk)
                    digest.update(chunk)
                    writer.write(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            if copied != item["size"] or digest.hexdigest() != item["sha256"]:
                raise UserDataArchiveError("materialized archive entry failed verification")


def _matches(root: Path, manifest: dict[str, object], *, portable_only: bool) -> bool:
    expected = {str(item["path"]): (int(item["size"]), str(item["sha256"])) for item in manifest["entries"]}
    actual = _iter_files(root, portable=portable_only)
    if {rel for rel, _, _ in actual} != set(expected):
        return False
    for relative, path, size in actual:
        exp_size, exp_digest = expected[relative]
        digest, measured = _sha256_path(path)
        if size != exp_size or measured != exp_size or digest != exp_digest:
            return False
    return True


def _stage_portable_import(current: Path, staging: Path, archive_path: Path, manifest: dict[str, object]) -> None:
    if current.exists() or current.is_symlink():
        _directory(current, "user-data root")
        # Validate the complete current tree before copytree so a nested symlink
        # or Windows reparse point can never be followed into staging.
        _iter_files(current, portable=False)
        shutil.copytree(current, staging, symlinks=True)
        for relative, path, _ in reversed(_iter_files(staging, portable=True)):
            path.unlink()
        for base, dirs, _files in os.walk(staging, topdown=False):
            for name in dirs:
                candidate = Path(base) / name
                try:
                    candidate.rmdir()
                except OSError:
                    pass
    else:
        staging.mkdir(parents=True)
    with zipfile.ZipFile(archive_path, "r", allowZip64=True) as archive:
        for item in manifest["entries"]:
            relative = str(item["path"])
            output = staging.joinpath(*PurePosixPath(relative).parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            copied = 0
            with archive.open(f"data/{relative}", "r") as reader, output.open("xb") as writer:
                while True:
                    chunk = reader.read(CHUNK)
                    if not chunk:
                        break
                    copied += len(chunk)
                    digest.update(chunk)
                    writer.write(chunk)
            if copied != item["size"] or digest.hexdigest() != item["sha256"]:
                raise UserDataArchiveError("portable import materialization failed verification")


def schedule_user_data_backup(layout: UserDataLayout, destination: Path, *, kind: BundleKind) -> dict[str, object]:
    pending = _pending_path(layout)
    if pending.exists() or pending.is_symlink():
        raise UserDataArchiveError("another user-data operation is already pending")
    destination = Path(destination)
    if _inside(destination, layout.root) or _inside(destination, _meta_root(layout)):
        raise UserDataArchiveError("archive destination must be outside managed user-data paths")
    operation = "backup" if kind is BundleKind.BACKUP else "export"
    _atomic_json(pending, {"schema": PENDING_SCHEMA_VERSION, "operation": operation, "kind": kind.value, "destination": str(destination)})
    return {"operation": operation, "kind": kind.value, "restart_required": True}


def schedule_user_data_restore(layout: UserDataLayout, source: Path, *, kind: BundleKind) -> dict[str, object]:
    pending = _pending_path(layout)
    if pending.exists() or pending.is_symlink():
        raise UserDataArchiveError("another user-data operation is already pending")
    source = Path(source)
    validate_user_data_archive(source, expected_kind=kind)
    digest, size = _sha256_path(source)
    staged = _staged_archive_path(layout, digest)
    staged.parent.mkdir(parents=True, exist_ok=True)
    if staged.exists() or staged.is_symlink():
        existing_digest, existing_size = _sha256_path(staged)
        if existing_digest != digest or existing_size != size:
            raise UserDataArchiveError("staged archive identity collision")
    else:
        temp = staged.parent / f".{staged.name}.tmp-{secrets.token_hex(8)}"
        try:
            with source.open("rb") as reader, temp.open("xb") as writer:
                shutil.copyfileobj(reader, writer, length=CHUNK)
                writer.flush()
                os.fsync(writer.fileno())
            copied_digest, copied_size = _sha256_path(temp)
            if copied_digest != digest or copied_size != size:
                raise UserDataArchiveError("staged archive copy verification failed")
            os.replace(temp, staged)
        finally:
            if temp.exists() or temp.is_symlink():
                try:
                    temp.unlink()
                except OSError:
                    pass
    operation = "restore" if kind is BundleKind.BACKUP else "import"
    _atomic_json(pending, {"schema": PENDING_SCHEMA_VERSION, "operation": operation, "kind": kind.value, "archive": str(staged), "sha256": digest, "size": size})
    return {"operation": operation, "kind": kind.value, "restart_required": True}


@dataclass(slots=True)
class PendingUserDataTransaction:
    layout: UserDataLayout
    rollback_path: Path | None
    journal_path: Path
    pending_path: Path
    staged_archive: Path
    committed: bool = False

    def commit(self) -> None:
        if self.committed:
            return
        journal = _read_json(self.journal_path, "restore journal")
        journal["phase"] = "validated"
        _atomic_json(self.journal_path, journal)
        if self.pending_path.exists() or self.pending_path.is_symlink():
            _regular(self.pending_path, "pending operation")
            self.pending_path.unlink()
        if self.rollback_path is not None and (self.rollback_path.exists() or self.rollback_path.is_symlink()):
            _remove(self.rollback_path)
        if self.staged_archive.exists() or self.staged_archive.is_symlink():
            _regular(self.staged_archive, "staged archive")
            self.staged_archive.unlink()
        if self.journal_path.exists() or self.journal_path.is_symlink():
            _regular(self.journal_path, "restore journal")
            self.journal_path.unlink()
        self.committed = True

    def rollback(self) -> None:
        if self.committed:
            return
        root = self.layout.root
        if root.exists() or root.is_symlink():
            _directory(root, "published user-data root")
            failed = root.parent / f".{root.name}.failed-{secrets.token_hex(8)}"
            os.replace(root, failed)
            _remove(failed)
        if self.rollback_path is not None and (self.rollback_path.exists() or self.rollback_path.is_symlink()):
            _directory(self.rollback_path, "rollback user-data root")
            os.replace(self.rollback_path, root)
        for path in (self.pending_path, self.journal_path, self.staged_archive):
            if path.exists() or path.is_symlink():
                _remove(path)
        self.committed = True


def _recover_interrupted(layout: UserDataLayout) -> None:
    journal_path = _journal_path(layout)
    if not journal_path.exists() and not journal_path.is_symlink():
        return
    journal = _read_json(journal_path, "restore journal")
    required = {"schema", "phase", "rollback", "staging", "archive", "pending", "had_root"}
    if set(journal) != required or journal["schema"] != PENDING_SCHEMA_VERSION or journal["phase"] not in {"prepared", "old-renamed", "published", "validated"}:
        raise UserDataArchiveError("restore journal is invalid")
    phase = str(journal["phase"])
    root = layout.root
    rollback_raw = journal["rollback"]
    rollback = Path(str(rollback_raw)) if rollback_raw else None
    staging = Path(str(journal["staging"]))
    archive = Path(str(journal["archive"]))
    pending = Path(str(journal["pending"]))
    if phase == "validated":
        _directory(root, "validated user-data root")
        for path in (rollback, staging, archive, pending, journal_path):
            if path is not None and (path.exists() or path.is_symlink()):
                _remove(path)
        return
    if phase == "prepared":
        for path in (staging, archive, pending, journal_path):
            if path.exists() or path.is_symlink():
                _remove(path)
        raise UserDataArchiveError("previous restore stopped before publication; prior state was preserved")
    if root.exists() or root.is_symlink():
        _remove(root)
    if rollback is not None and (rollback.exists() or rollback.is_symlink()):
        os.replace(rollback, root)
    for path in (staging, archive, pending, journal_path):
        if path.exists() or path.is_symlink():
            _remove(path)
    raise UserDataArchiveError("previous restore was interrupted; prior state was restored")


def begin_pending_user_data_operation(layout: UserDataLayout) -> PendingUserDataTransaction | None:
    if not isinstance(layout, UserDataLayout):
        raise TypeError("layout must be UserDataLayout")
    layout.root.parent.mkdir(parents=True, exist_ok=True)
    _recover_interrupted(layout)
    pending_path = _pending_path(layout)
    if not pending_path.exists() and not pending_path.is_symlink():
        return None
    pending = _read_json(pending_path, "pending user-data operation")
    if pending.get("schema") != PENDING_SCHEMA_VERSION:
        raise UserDataArchiveError("pending operation schema is invalid")
    operation = pending.get("operation")
    try:
        kind = BundleKind(pending.get("kind"))
    except (TypeError, ValueError) as exc:
        raise UserDataArchiveError("pending operation kind is invalid") from exc
    if operation in {"backup", "export"}:
        expected = BundleKind.BACKUP if operation == "backup" else BundleKind.PORTABLE
        if kind is not expected or set(pending) != {"schema", "operation", "kind", "destination"}:
            raise UserDataArchiveError("pending backup/export operation is invalid")
        create_user_data_archive(layout.root, Path(str(pending["destination"])), kind=kind)
        pending_path.unlink()
        return None
    if operation not in {"restore", "import"}:
        raise UserDataArchiveError("pending operation is unknown")
    expected = BundleKind.BACKUP if operation == "restore" else BundleKind.PORTABLE
    if kind is not expected or set(pending) != {"schema", "operation", "kind", "archive", "sha256", "size"}:
        raise UserDataArchiveError("pending restore/import operation is invalid")
    archive_path = Path(str(pending["archive"]))
    digest, size = _sha256_path(archive_path)
    if digest != pending["sha256"] or size != pending["size"]:
        raise UserDataArchiveError("pending archive changed after authorization")
    manifest = validate_user_data_archive(archive_path, expected_kind=kind)
    staging = layout.root.parent / f".{layout.root.name}.restore-stage-{secrets.token_hex(8)}"
    rollback = layout.root.parent / f".{layout.root.name}.restore-rollback-{secrets.token_hex(8)}"
    if kind is BundleKind.PORTABLE:
        _stage_portable_import(layout.root, staging, archive_path, manifest)
        portable_only = True
    else:
        _extract(archive_path, staging, manifest)
        portable_only = False
    if not _matches(staging, manifest, portable_only=portable_only):
        _remove(staging)
        raise UserDataArchiveError("restore staging verification failed")
    had_root = layout.root.exists() or layout.root.is_symlink()
    if had_root:
        _directory(layout.root, "user-data root")
    journal_path = _journal_path(layout)
    journal = {"schema": PENDING_SCHEMA_VERSION, "phase": "prepared", "rollback": str(rollback) if had_root else "", "staging": str(staging), "archive": str(archive_path), "pending": str(pending_path), "had_root": had_root}
    _atomic_json(journal_path, journal)
    rollback_ref = rollback if had_root else None
    if had_root:
        os.replace(layout.root, rollback)
    journal["phase"] = "old-renamed"
    _atomic_json(journal_path, journal)
    os.replace(staging, layout.root)
    journal["phase"] = "published"
    _atomic_json(journal_path, journal)
    if not _matches(layout.root, manifest, portable_only=portable_only):
        tx = PendingUserDataTransaction(layout, rollback_ref, journal_path, pending_path, archive_path)
        tx.rollback()
        raise UserDataArchiveError("published restore failed readback and was rolled back")
    return PendingUserDataTransaction(layout, rollback_ref, journal_path, pending_path, archive_path)


class Version2UserDataPortabilityHost:
    """Owner-bound host. Native dialogs choose paths; work runs on next startup."""

    def __init__(self, layout: UserDataLayout, *, save_dialog: Callable[[BundleKind], Path | None], open_dialog: Callable[[BundleKind], Path | None]) -> None:
        if not isinstance(layout, UserDataLayout) or not callable(save_dialog) or not callable(open_dialog):
            raise TypeError("invalid user-data portability host construction")
        self.layout = layout
        self._save_dialog = save_dialog
        self._open_dialog = open_dialog

    def __call__(self, action: str, payload: dict[str, object]) -> dict[str, object]:
        if type(payload) is not dict or payload:
            raise UserDataArchiveError("user-data actions accept no browser payload")
        if action in {"data.backup", "data.export"}:
            kind = BundleKind.BACKUP if action == "data.backup" else BundleKind.PORTABLE
            path = self._save_dialog(kind)
            if path is None:
                return {"ok": False, "cancelled": True, "action": action}
            result = schedule_user_data_backup(self.layout, Path(path), kind=kind)
        elif action in {"data.restore", "data.import"}:
            kind = BundleKind.BACKUP if action == "data.restore" else BundleKind.PORTABLE
            path = self._open_dialog(kind)
            if path is None:
                return {"ok": False, "cancelled": True, "action": action}
            result = schedule_user_data_restore(self.layout, Path(path), kind=kind)
        else:
            raise UserDataArchiveError("unknown user-data action")
        return {"ok": True, "action": action, **result}


__all__ = [
    "UserDataArchiveError", "PendingUserDataTransaction",
    "Version2UserDataPortabilityHost", "create_user_data_archive",
    "validate_user_data_archive", "schedule_user_data_backup",
    "schedule_user_data_restore", "begin_pending_user_data_operation",
]
