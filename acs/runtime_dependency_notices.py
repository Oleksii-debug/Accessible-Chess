from __future__ import annotations

"""Deterministic third-party notice bundle for the Windows build/runtime stack.

The release payload already publishes Stockfish and sound provenance.  This module
covers the Python/native dependency side without guessing license text: every
listed distribution must expose at least one real installed license/notice file,
and the exact bytes copied into the release evidence are SHA-256 inventoried.

This is a build-time boundary only.  It does not decide which dependencies are
redistributed; callers provide the exact distribution inventory established by
the qualified build.  Missing metadata, missing license files, unsafe names, or
version drift fail closed before publication.
"""

from dataclasses import dataclass
import hashlib
from importlib import metadata
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile
from typing import Any, Callable, Iterable


_NOTICE_SCHEMA_VERSION = 1
_LICENSE_BASENAMES = ("license", "copying", "notice", "copyright")
_SAFE_DISTRIBUTION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+!-]{0,127}$")


class RuntimeDependencyNoticeError(RuntimeError):
    """Raised when dependency notice evidence cannot be built fail-closed."""


@dataclass(frozen=True, slots=True)
class RuntimeDependencyNoticeBundle:
    root: Path
    manifest_path: Path
    notice_files: tuple[Path, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean_distribution_name(value: object) -> str:
    if type(value) is not str:
        raise RuntimeDependencyNoticeError("distribution name must be text")
    token = value.strip()
    if not _SAFE_DISTRIBUTION.fullmatch(token):
        raise RuntimeDependencyNoticeError("distribution name is unsafe")
    return token


def _clean_version(value: object) -> str:
    if type(value) is not str:
        raise RuntimeDependencyNoticeError("distribution version must be text")
    token = value.strip()
    if not _SAFE_VERSION.fullmatch(token):
        raise RuntimeDependencyNoticeError("distribution version is unsafe")
    return token


def _metadata_value(dist: Any, key: str) -> str:
    raw = getattr(dist, "metadata", None)
    if raw is None:
        return ""
    try:
        value = raw.get(key, "")
    except Exception:
        return ""
    return str(value or "").strip()


def _metadata_values(dist: Any, key: str) -> tuple[str, ...]:
    raw = getattr(dist, "metadata", None)
    if raw is None:
        return ()
    getter = getattr(raw, "get_all", None)
    if not callable(getter):
        return ()
    try:
        values = getter(key) or ()
    except Exception:
        return ()
    return tuple(str(value).strip() for value in values if str(value).strip())


def _safe_relative_notice(value: object) -> PurePosixPath:
    token = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(token)
    if (
        not token
        or path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != token
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise RuntimeDependencyNoticeError("distribution license path is unsafe")
    return path


def _looks_like_notice(path: PurePosixPath) -> bool:
    name = path.name.casefold()
    stem = name.split(".", 1)[0]
    return any(stem == base or stem.startswith(base + "-") for base in _LICENSE_BASENAMES)


def _candidate_notice_paths(dist: Any) -> tuple[PurePosixPath, ...]:
    candidates: list[PurePosixPath] = []
    for value in _metadata_values(dist, "License-File"):
        path = _safe_relative_notice(value)
        if path not in candidates:
            candidates.append(path)

    # Older wheels may omit License-File metadata while still shipping a license
    # under dist-info.  Fall back only to real installed files with conventional
    # notice names; never synthesize license text from metadata classifiers.
    try:
        files = tuple(getattr(dist, "files", None) or ())
    except Exception:
        files = ()
    for value in files:
        path = _safe_relative_notice(str(value))
        if _looks_like_notice(path) and path not in candidates:
            candidates.append(path)
    return tuple(candidates)


def _locate_notice(dist: Any, relative: PurePosixPath) -> Path:
    locator = getattr(dist, "locate_file", None)
    if not callable(locator):
        raise RuntimeDependencyNoticeError("distribution cannot locate license files")
    try:
        located = Path(locator(str(relative)))
        resolved = located.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeDependencyNoticeError("distribution license file is unavailable") from exc
    if not resolved.is_file() or resolved.is_symlink() or resolved.stat().st_size <= 0:
        raise RuntimeDependencyNoticeError("distribution license file is not a regular non-empty file")
    return resolved


def _python_license_path(explicit: str | Path | None) -> Path:
    candidates = (
        (Path(explicit),) if explicit is not None else (
            Path(sys.base_prefix) / "LICENSE.txt",
            Path(sys.base_prefix) / "LICENSE",
            Path(sys.prefix) / "LICENSE.txt",
            Path(sys.prefix) / "LICENSE",
        )
    )
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            continue
        if resolved.is_file() and not resolved.is_symlink() and resolved.stat().st_size > 0:
            return resolved
    raise RuntimeDependencyNoticeError("Python license file is unavailable")


def _project_urls(dist: Any) -> tuple[str, ...]:
    values = []
    for entry in _metadata_values(dist, "Project-URL"):
        if "," in entry:
            _label, raw = entry.split(",", 1)
            url = raw.strip()
        else:
            url = entry.strip()
        if url.startswith("https://") and url not in values:
            values.append(url)
    home = _metadata_value(dist, "Home-page")
    if home.startswith("https://") and home not in values:
        values.append(home)
    return tuple(values)


def build_runtime_dependency_notice_bundle(
    distributions: Iterable[str],
    output_root: str | Path,
    *,
    expected_versions: dict[str, str] | None = None,
    distribution_loader: Callable[[str], Any] = metadata.distribution,
    python_license_path: str | Path | None = None,
    python_version: str | None = None,
) -> RuntimeDependencyNoticeBundle:
    """Publish deterministic exact-byte license evidence for a qualified stack.

    ``expected_versions`` is optional for reusable source tests, but release
    callers should provide it.  Keys are matched case-insensitively after the
    distribution names themselves pass the bounded filename-safe contract.
    """

    root = Path(output_root)
    if root.exists():
        raise RuntimeDependencyNoticeError("dependency notice output already exists")

    names: list[str] = []
    seen: set[str] = set()
    for value in distributions:
        name = _clean_distribution_name(value)
        folded = name.casefold()
        if folded in seen:
            raise RuntimeDependencyNoticeError("dependency notice inventory contains duplicates")
        seen.add(folded)
        names.append(name)
    if not names:
        raise RuntimeDependencyNoticeError("dependency notice inventory must not be empty")

    expected: dict[str, str] = {}
    for key, value in (expected_versions or {}).items():
        name = _clean_distribution_name(key)
        version = _clean_version(value)
        folded = name.casefold()
        if folded in expected:
            raise RuntimeDependencyNoticeError("expected dependency versions contain duplicates")
        expected[folded] = version
    if expected and set(expected) != seen:
        raise RuntimeDependencyNoticeError("expected dependency versions must match the notice inventory")

    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{root.name}.dependency-notices-", dir=root.parent))
    published_files: list[Path] = []
    manifest_rows: list[dict[str, object]] = []
    try:
        python_license = _python_license_path(python_license_path)
        python_notice = staging / "Python-LICENSE.txt"
        shutil.copyfile(python_license, python_notice, follow_symlinks=False)
        published_files.append(python_notice)
        resolved_python_version = python_version or ".".join(str(value) for value in sys.version_info[:3])
        resolved_python_version = _clean_version(resolved_python_version)

        for name in sorted(names, key=str.casefold):
            try:
                dist = distribution_loader(name)
            except Exception as exc:
                raise RuntimeDependencyNoticeError(
                    f"installed distribution is unavailable: {name}"
                ) from exc
            version = _clean_version(getattr(dist, "version", ""))
            wanted = expected.get(name.casefold())
            if wanted is not None and version != wanted:
                raise RuntimeDependencyNoticeError(
                    f"installed distribution version mismatch: {name}"
                )

            candidates = _candidate_notice_paths(dist)
            if not candidates:
                raise RuntimeDependencyNoticeError(
                    f"installed distribution has no real license/notice file: {name}"
                )
            rows: list[dict[str, str]] = []
            prefix = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._")
            for index, relative in enumerate(candidates, start=1):
                source = _locate_notice(dist, relative)
                suffix = source.suffix if len(source.suffix) <= 16 else ".txt"
                target_name = f"{prefix}-{version}-NOTICE-{index:02d}{suffix or '.txt'}"
                target = staging / target_name
                shutil.copyfile(source, target, follow_symlinks=False)
                published_files.append(target)
                rows.append(
                    {
                        "source_path": relative.as_posix(),
                        "packaged_file": target.name,
                        "sha256": _sha256(target),
                    }
                )

            manifest_rows.append(
                {
                    "distribution": name,
                    "version": version,
                    "license_expression": _metadata_value(dist, "License-Expression"),
                    "license_metadata": _metadata_value(dist, "License"),
                    "project_urls": list(_project_urls(dist)),
                    "notice_files": rows,
                }
            )

        manifest = {
            "schema_version": _NOTICE_SCHEMA_VERSION,
            "scope": "qualified Python build/runtime dependency notice evidence",
            "python": {
                "version": resolved_python_version,
                "packaged_file": python_notice.name,
                "sha256": _sha256(python_notice),
            },
            "distributions": manifest_rows,
        }
        manifest_path = staging / "PYTHON_RUNTIME_DEPENDENCIES.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        published_files.append(manifest_path)
        staging.replace(root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    final_files = tuple(root / path.name for path in published_files)
    return RuntimeDependencyNoticeBundle(
        root=root,
        manifest_path=root / "PYTHON_RUNTIME_DEPENDENCIES.json",
        notice_files=final_files,
    )


__all__ = [
    "RuntimeDependencyNoticeBundle",
    "RuntimeDependencyNoticeError",
    "build_runtime_dependency_notice_bundle",
]
