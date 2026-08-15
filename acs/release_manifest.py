from __future__ import annotations

"""Deterministic validation and checksums for packaged Accessible Chess builds.

This module is release infrastructure, not application logic. It validates a
finished distribution directory before publication and produces a stable
manifest that can later be signed by release tooling. It intentionally performs
no code signing and stores no secrets.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable


MANIFEST_SCHEMA_VERSION = 1
DEFAULT_PRODUCT_NAME = "Accessible Chess"
DEFAULT_EXECUTABLE = "AccessibleChess.exe"
_SOURCE_SUFFIXES = frozenset({".py", ".pyc", ".pyo"})


@dataclass(frozen=True, slots=True)
class ReleaseFile:
    path: str
    size: int
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return {"path": self.path, "size": self.size, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    schema_version: int
    product: str
    version: str
    files: tuple[ReleaseFile, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "product": self.product,
            "version": self.version,
            "files": [item.as_dict() for item in self.files],
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _sha256(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _relative_packaged_files(root: Path) -> Iterable[Path]:
    resolved_root = root.resolve()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if path.is_symlink():
            target = path.resolve()
            try:
                target.relative_to(resolved_root)
            except ValueError as exc:
                raise ValueError(f"release contains symlink escaping package root: {path}") from exc
        if path.is_file():
            yield path


def build_release_manifest(
    root: str | Path,
    *,
    version: str,
    product: str = DEFAULT_PRODUCT_NAME,
) -> ReleaseManifest:
    package_root = Path(root)
    if not package_root.is_dir():
        raise ValueError(f"release root is not a directory: {package_root}")
    normalized_version = str(version).strip()
    if not normalized_version:
        raise ValueError("release version must not be empty")

    files: list[ReleaseFile] = []
    for path in _relative_packaged_files(package_root):
        relative = path.relative_to(package_root).as_posix()
        files.append(ReleaseFile(relative, path.stat().st_size, _sha256(path)))
    if not files:
        raise ValueError("release package is empty")
    return ReleaseManifest(MANIFEST_SCHEMA_VERSION, product, normalized_version, tuple(files))


def validate_distribution(
    root: str | Path,
    *,
    executable: str = DEFAULT_EXECUTABLE,
    require_stockfish: bool = True,
    prohibit_python_source: bool = True,
) -> tuple[str, ...]:
    """Return release-blocking defects found in a finished distribution.

    The gate is intentionally conservative. A development checkout is not a
    distribution and is expected to fail the raw-source rule.
    """

    package_root = Path(root)
    if not package_root.is_dir():
        return (f"release root is not a directory: {package_root}",)

    defects: list[str] = []
    executable_matches = [
        path for path in package_root.rglob("*")
        if path.is_file() and path.name.casefold() == executable.casefold()
    ]
    if len(executable_matches) != 1:
        defects.append(
            f"expected exactly one {executable}; found {len(executable_matches)}"
        )

    if require_stockfish:
        stockfish_matches = [
            path for path in package_root.rglob("*")
            if path.is_file()
            and path.suffix.casefold() == ".exe"
            and "stockfish" in path.name.casefold()
        ]
        if not stockfish_matches:
            defects.append("Stockfish executable is missing from packaged runtime")

    if prohibit_python_source:
        leaked_sources = sorted(
            path.relative_to(package_root).as_posix()
            for path in package_root.rglob("*")
            if path.is_file() and path.suffix.casefold() in _SOURCE_SUFFIXES
        )
        if leaked_sources:
            defects.append(
                "raw Python source/bytecode present in production package: "
                + ", ".join(leaked_sources[:10])
            )

    try:
        tuple(_relative_packaged_files(package_root))
    except ValueError as exc:
        defects.append(str(exc))

    return tuple(defects)


def read_project_version(path: str | Path = "VERSION.txt") -> str:
    version_path = Path(path)
    if not version_path.is_file():
        raise ValueError(f"version file is missing: {version_path}")
    version = version_path.read_text(encoding="utf-8").strip()
    if not version:
        raise ValueError(f"version file is empty: {version_path}")
    return version
