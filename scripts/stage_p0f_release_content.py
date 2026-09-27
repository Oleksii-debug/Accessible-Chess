from __future__ import annotations

"""Atomically stage the qualified P0-F W2 bundle into a Windows package tree.

This is a package-composition seam only.  Bundle semantics and provenance stay
owned by ``acs.version2_packaged_starter_application._load_manifest``; the
stager deliberately reuses that exact runtime authority before and after copy.
"""

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import stat
import tempfile

from acs.version2_packaged_starter_application import (
    _MANIFEST_MAX_BYTES,
    _identity_pinned_bytes,
    _is_reparse,
    _load_manifest,
)


_CANONICAL_FILES = (
    "starter_uk.pgn",
    "stress_uk.pgn",
    "sample_library.acsdb",
    "manifest.json",
)
_TARGET_RELATIVE = Path("release-content") / "w2-starter"


class StageError(RuntimeError):
    pass


def _require_direct_directory(path: Path, *, label: str) -> Path:
    # ``Path.resolve()`` can change the textual spelling of an otherwise direct
    # Windows path (notably by expanding an 8.3 component such as RUNNER~1).
    # Textual inequality is therefore not evidence of indirection. Walk every
    # existing lexical component instead and fail closed on an actual symlink
    # or Windows reparse point. Resolve once only to prove the checked lexical
    # path remains resolvable, then preserve that lexical identity for callers.
    absolute = Path(os.path.abspath(path))
    current = absolute
    while True:
        try:
            info = current.lstat()
        except OSError as exc:
            if current == absolute:
                raise StageError(f"{label} is unavailable") from exc
            raise StageError(f"{label} path ancestry is unavailable") from exc
        if stat.S_ISLNK(info.st_mode) or _is_reparse(info):
            raise StageError(f"{label} must not resolve through an indirect path")
        parent = current.parent
        if parent == current:
            break
        current = parent

    try:
        info = absolute.lstat()
    except OSError as exc:
        raise StageError(f"{label} is unavailable") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise StageError(f"{label} must be a direct regular directory")
    try:
        absolute.resolve(strict=True)
    except OSError as exc:
        raise StageError(f"{label} cannot be resolved") from exc
    return absolute


def _manifest_bytes(root: Path) -> bytes:
    try:
        return _identity_pinned_bytes(
            root / "manifest.json",
            label="P0-F staging manifest",
            maximum_bytes=_MANIFEST_MAX_BYTES,
        )
    except RuntimeError as exc:
        raise StageError(str(exc)) from exc


def _fsync_copy(source: Path, destination: Path) -> None:
    try:
        with source.open("rb") as src, destination.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
    except OSError as exc:
        raise StageError("P0-F bundle file could not be staged") from exc


def stage_bundle(source_bundle: str | Path, product_root: str | Path) -> Path:
    """Publish one validated W2 bundle beside ``AccessibleChess.exe``.

    The target must not already exist.  This makes repeated/stale package
    composition fail closed rather than silently replacing release evidence.
    A release-content directory created by this call is also rolled back when
    publication fails, so a failed transaction does not mutate the package tree.
    """

    source = _require_direct_directory(Path(source_bundle), label="P0-F source bundle")
    product = _require_direct_directory(Path(product_root), label="Product root")

    executable = product / "AccessibleChess.exe"
    try:
        exe_info = executable.lstat()
    except OSError as exc:
        raise StageError("AccessibleChess.exe is missing from Product root") from exc
    if stat.S_ISLNK(exe_info.st_mode) or _is_reparse(exe_info) or not stat.S_ISREG(exe_info.st_mode):
        raise StageError("AccessibleChess.exe must be a direct regular file before staging")

    # Bind the validation to one exact source manifest across the potentially
    # expensive payload verification performed by the incumbent runtime owner.
    manifest_before = _manifest_bytes(source)
    try:
        _load_manifest(source)
    except RuntimeError as exc:
        raise StageError(f"P0-F source bundle validation failed: {exc}") from exc
    manifest_after = _manifest_bytes(source)
    if manifest_after != manifest_before:
        raise StageError("P0-F source manifest changed during validation")

    release_root = product / _TARGET_RELATIVE.parent
    created_release_root = False
    if os.path.lexists(release_root):
        release = _require_direct_directory(release_root, label="Product release-content root")
    else:
        try:
            release_root.mkdir(mode=0o755)
            created_release_root = True
        except OSError as exc:
            raise StageError("Product release-content root could not be created") from exc
        try:
            release = _require_direct_directory(release_root, label="Product release-content root")
        except StageError:
            try:
                release_root.rmdir()
            except OSError:
                pass
            raise

    target = release / _TARGET_RELATIVE.name
    if os.path.lexists(target):
        raise StageError("P0-F W2 package target already exists")

    temporary: Path | None = None
    published = False
    try:
        try:
            raw_temp = tempfile.mkdtemp(prefix=".w2-starter-stage-", dir=str(release))
        except OSError as exc:
            raise StageError("P0-F temporary staging directory could not be created") from exc
        temporary = Path(raw_temp)

        for name in _CANONICAL_FILES:
            _fsync_copy(source / name, temporary / name)

        staged_manifest = _manifest_bytes(temporary)
        if staged_manifest != manifest_before:
            raise StageError("staged P0-F manifest does not match validated source")
        try:
            _load_manifest(temporary)
        except RuntimeError as exc:
            raise StageError(f"staged P0-F bundle validation failed: {exc}") from exc

        try:
            os.replace(temporary, target)
        except OSError as exc:
            raise StageError("P0-F W2 package target could not be published atomically") from exc
        published = True
    finally:
        if not published:
            if temporary is not None and temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)
            if created_release_root:
                try:
                    release_root.rmdir()
                except OSError:
                    # Never remove a non-empty/externally changed release root.
                    pass

    # A final post-publication validation catches filesystem interference at the
    # publication boundary before package checksums are generated.
    try:
        _load_manifest(target)
    except RuntimeError as exc:
        raise StageError(f"published P0-F bundle validation failed: {exc}") from exc
    if hashlib.sha256(_manifest_bytes(target)).digest() != hashlib.sha256(manifest_before).digest():
        raise StageError("published P0-F manifest identity changed")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage qualified P0-F W2 release content")
    parser.add_argument("source_bundle", type=Path)
    parser.add_argument("product_root", type=Path)
    args = parser.parse_args()
    try:
        target = stage_bundle(args.source_bundle, args.product_root)
    except StageError as exc:
        print(f"P0-F PACKAGE STAGING FAIL: {exc}")
        return 1
    print(f"P0-F PACKAGE STAGING PASS: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
