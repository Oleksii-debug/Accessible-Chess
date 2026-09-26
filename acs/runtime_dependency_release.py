from __future__ import annotations

"""Publish verified Python runtime notices and SPDX into the canonical release notices tree.

This is intentionally an adapter, not a second dependency collector.  Its input is
the already-qualified runtime notice bundle; it verifies those exact bytes again,
rejects untracked/symlinked content, generates SPDX from that same manifest, and
atomically publishes one bounded ``Python-Runtime`` subtree beneath the existing
Version 2 ``third-party-notices`` directory.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Any

from .runtime_dependency_sbom import build_runtime_dependency_spdx23


_MANIFEST = "PYTHON_RUNTIME_DEPENDENCIES.json"
_SBOM = "PYTHON_RUNTIME_DEPENDENCIES.spdx.json"
_RELEASE_SUBDIR = "Python-Runtime"
_SCHEMA_VERSION = 2


class RuntimeDependencyReleaseError(RuntimeError):
    """Raised when verified runtime evidence cannot be shipped fail-closed."""


@dataclass(frozen=True)
class PublishedRuntimeDependencyEvidence:
    root: Path
    manifest_path: Path
    sbom_path: Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_flat_file(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise RuntimeDependencyReleaseError(f"{label} is invalid")
    token = PurePosixPath(value)
    if token.is_absolute() or len(token.parts) != 1 or token.parts[0] in {".", ".."}:
        raise RuntimeDependencyReleaseError(f"{label} must be a flat safe file name")
    if token.as_posix() != value:
        raise RuntimeDependencyReleaseError(f"{label} is invalid")
    return value


def _verified_file(root: Path, name: str, digest: object, *, label: str) -> Path:
    if not isinstance(digest, str) or len(digest) != 64 or digest != digest.lower():
        raise RuntimeDependencyReleaseError(f"{label} SHA-256 is invalid")
    if any(character not in "0123456789abcdef" for character in digest):
        raise RuntimeDependencyReleaseError(f"{label} SHA-256 is invalid")
    path = root / name
    if path.is_symlink() or not path.is_file():
        raise RuntimeDependencyReleaseError(f"{label} file is missing or unsafe")
    if _sha256(path) != digest:
        raise RuntimeDependencyReleaseError(f"{label} SHA-256 mismatch")
    return path


def _load_inventory(root: Path) -> tuple[Path, dict[str, Any], tuple[Path, ...]]:
    if root.is_symlink() or not root.is_dir():
        raise RuntimeDependencyReleaseError("runtime notice bundle is missing or unsafe")
    manifest_path = root / _MANIFEST
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise RuntimeDependencyReleaseError("runtime notice manifest is missing or unsafe")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeDependencyReleaseError("runtime notice manifest is invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != _SCHEMA_VERSION:
        raise RuntimeDependencyReleaseError("runtime notice manifest schema is unsupported")
    python = manifest.get("python")
    rows = manifest.get("distributions")
    if not isinstance(python, dict) or not isinstance(rows, list) or not rows:
        raise RuntimeDependencyReleaseError("runtime notice manifest shape is invalid")

    expected_names = {_MANIFEST}
    verified: list[Path] = []
    python_name = _safe_flat_file(python.get("packaged_file"), label="Python notice")
    if python_name in expected_names:
        raise RuntimeDependencyReleaseError("runtime notice manifest contains duplicate files")
    expected_names.add(python_name)
    verified.append(
        _verified_file(root, python_name, python.get("sha256"), label="Python notice")
    )

    distributions: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeDependencyReleaseError("runtime notice distribution row is invalid")
        distribution = row.get("distribution")
        if not isinstance(distribution, str) or not distribution.strip():
            raise RuntimeDependencyReleaseError("runtime notice distribution name is invalid")
        folded = distribution.strip().casefold()
        if folded in distributions:
            raise RuntimeDependencyReleaseError("runtime notice distributions contain duplicates")
        distributions.add(folded)
        notices = row.get("notice_files")
        if not isinstance(notices, list) or not notices:
            raise RuntimeDependencyReleaseError(
                f"runtime notice distribution has no evidence: {distribution}"
            )
        for notice in notices:
            if not isinstance(notice, dict):
                raise RuntimeDependencyReleaseError("runtime notice evidence row is invalid")
            name = _safe_flat_file(notice.get("packaged_file"), label="dependency notice")
            if name in expected_names:
                raise RuntimeDependencyReleaseError("runtime notice manifest contains duplicate files")
            expected_names.add(name)
            verified.append(
                _verified_file(root, name, notice.get("sha256"), label="dependency notice")
            )

    actual_names: set[str] = set()
    for path in root.iterdir():
        if path.is_symlink() or not path.is_file():
            raise RuntimeDependencyReleaseError("runtime notice bundle contains non-file content")
        actual_names.add(path.name)
    if actual_names != expected_names:
        raise RuntimeDependencyReleaseError("runtime notice bundle contains untracked or missing files")
    return manifest_path, manifest, tuple(verified)


def publish_runtime_dependency_release_evidence(
    notice_bundle_root: str | Path,
    release_notices_dir: str | Path,
    *,
    document_name: str,
    created_utc: str,
) -> PublishedRuntimeDependencyEvidence:
    """Atomically add verified Python runtime evidence to release third-party notices."""

    source_root = Path(notice_bundle_root)
    destination_parent = Path(release_notices_dir)
    if destination_parent.is_symlink() or not destination_parent.is_dir():
        raise RuntimeDependencyReleaseError("release notices directory is missing or unsafe")
    destination = destination_parent / _RELEASE_SUBDIR
    if destination.exists() or destination.is_symlink():
        raise RuntimeDependencyReleaseError("runtime release evidence destination already exists")

    manifest_path, _manifest, verified = _load_inventory(source_root)
    staging = Path(tempfile.mkdtemp(prefix=".python-runtime-evidence-", dir=destination_parent))
    try:
        shutil.copyfile(manifest_path, staging / _MANIFEST, follow_symlinks=False)
        for source in verified:
            shutil.copyfile(source, staging / source.name, follow_symlinks=False)
        sbom = build_runtime_dependency_spdx23(
            staging / _MANIFEST,
            staging / _SBOM,
            document_name=document_name,
            created_utc=created_utc,
        )
        if destination.exists() or destination.is_symlink():
            raise RuntimeDependencyReleaseError("runtime release evidence destination appeared during publication")
        staging.rename(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return PublishedRuntimeDependencyEvidence(
        root=destination,
        manifest_path=destination / _MANIFEST,
        sbom_path=destination / sbom.name,
    )


__all__ = [
    "PublishedRuntimeDependencyEvidence",
    "RuntimeDependencyReleaseError",
    "publish_runtime_dependency_release_evidence",
]