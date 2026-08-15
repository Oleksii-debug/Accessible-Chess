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
from typing import Iterable, Mapping


MANIFEST_SCHEMA_VERSION = 1
DEFAULT_PRODUCT_NAME = "Accessible Chess"
DEFAULT_EXECUTABLE = "AccessibleChess.exe"
_SOURCE_SUFFIXES = frozenset({".py", ".pyc", ".pyo"})
_DEFAULT_UNTRACKED_METADATA = frozenset({"RELEASE-MANIFEST.json", "RELEASE-BUILD.txt"})


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

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ReleaseManifest":
        schema = value.get("schema_version")
        if schema != MANIFEST_SCHEMA_VERSION:
            raise ValueError(f"unsupported release manifest schema: {schema!r}")

        product = value.get("product")
        version = value.get("version")
        raw_files = value.get("files")
        if not isinstance(product, str) or not product.strip():
            raise ValueError("release manifest product must be a non-empty string")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("release manifest version must be a non-empty string")
        if not isinstance(raw_files, list) or not raw_files:
            raise ValueError("release manifest files must be a non-empty list")

        files: list[ReleaseFile] = []
        seen: set[str] = set()
        for index, raw in enumerate(raw_files):
            if not isinstance(raw, Mapping):
                raise ValueError(f"release manifest file #{index} must be an object")
            path = raw.get("path")
            size = raw.get("size")
            sha256 = raw.get("sha256")
            if not isinstance(path, str) or not path or "\\" in path:
                raise ValueError(f"invalid release manifest path at index {index}: {path!r}")
            normalized = Path(path)
            if normalized.is_absolute() or ".." in normalized.parts or normalized.as_posix() != path:
                raise ValueError(f"unsafe release manifest path at index {index}: {path!r}")
            folded = path.casefold()
            if folded in seen:
                raise ValueError(f"duplicate release manifest path: {path}")
            seen.add(folded)
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise ValueError(f"invalid release manifest size for {path}: {size!r}")
            if (
                not isinstance(sha256, str)
                or len(sha256) != 64
                or any(ch not in "0123456789abcdef" for ch in sha256)
            ):
                raise ValueError(f"invalid SHA-256 for {path}")
            files.append(ReleaseFile(path, size, sha256))

        expected_order = sorted(files, key=lambda item: item.path.casefold())
        if files != expected_order:
            raise ValueError("release manifest files are not in canonical sorted order")
        return cls(schema, product.strip(), version.strip(), tuple(files))

    @classmethod
    def from_json(cls, text: str) -> "ReleaseManifest":
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid release manifest JSON: {exc}") from exc
        if not isinstance(value, Mapping):
            raise ValueError("release manifest root must be an object")
        return cls.from_dict(value)


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


def verify_release_manifest(
    root: str | Path,
    manifest: ReleaseManifest,
    *,
    expected_product: str = DEFAULT_PRODUCT_NAME,
    expected_version: str | None = None,
    allowed_untracked: Iterable[str] = _DEFAULT_UNTRACKED_METADATA,
) -> tuple[str, ...]:
    """Verify a finished package against a previously generated manifest.

    This is deliberately strict: listed files must exist with the exact size and
    SHA-256, and unexpected payload files are rejected. Release metadata created
    after the manifest is generated is explicitly allowlisted because a manifest
    cannot checksum itself. A future signature should cover the manifest bytes.
    """

    package_root = Path(root)
    if not package_root.is_dir():
        return (f"release root is not a directory: {package_root}",)

    defects: list[str] = []
    if manifest.product != expected_product:
        defects.append(
            f"release product mismatch: manifest={manifest.product!r}, expected={expected_product!r}"
        )
    if expected_version is not None and manifest.version != str(expected_version).strip():
        defects.append(
            f"release version mismatch: manifest={manifest.version!r}, expected={str(expected_version).strip()!r}"
        )

    listed = {item.path.casefold(): item for item in manifest.files}
    for item in manifest.files:
        path = package_root / Path(item.path)
        try:
            resolved = path.resolve()
            resolved.relative_to(package_root.resolve())
        except ValueError:
            defects.append(f"manifest path escapes package root: {item.path}")
            continue
        if not path.is_file():
            defects.append(f"manifest file missing: {item.path}")
            continue
        current_size = path.stat().st_size
        if current_size != item.size:
            defects.append(
                f"manifest size mismatch for {item.path}: expected {item.size}, found {current_size}"
            )
            continue
        current_hash = _sha256(path)
        if current_hash != item.sha256:
            defects.append(f"manifest SHA-256 mismatch for {item.path}")

    allowed = {Path(value).as_posix().casefold() for value in allowed_untracked}
    try:
        actual_paths = {
            path.relative_to(package_root).as_posix().casefold(): path
            for path in _relative_packaged_files(package_root)
        }
    except ValueError as exc:
        defects.append(str(exc))
        return tuple(defects)

    unexpected = sorted(
        relative for relative in actual_paths if relative not in listed and relative not in allowed
    )
    for relative in unexpected:
        defects.append(f"unexpected unmanifested release file: {relative}")

    return tuple(defects)


def load_release_manifest(path: str | Path) -> ReleaseManifest:
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise ValueError(f"release manifest is missing: {manifest_path}")
    return ReleaseManifest.from_json(manifest_path.read_text(encoding="utf-8-sig"))


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
