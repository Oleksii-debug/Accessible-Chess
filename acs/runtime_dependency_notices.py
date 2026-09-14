from __future__ import annotations

"""Deterministic third-party notice bundle for the Windows build/runtime stack.

Installed wheel notice bytes remain the preferred authority. Some upstream wheels
omit the license file even though the exact source release contains it. For that
bounded case callers may provide an exact source archive, cryptographic digest,
and exact regular-file member. The collector verifies and reads those bytes itself;
it never invents or downloads license text.
"""

from dataclasses import dataclass
import hashlib
from importlib import metadata
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tarfile
import tempfile
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlparse


_NOTICE_SCHEMA_VERSION = 2
_LICENSE_BASENAMES = ("license", "licence", "copying", "notice", "copyright")
_SAFE_DISTRIBUTION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+!-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_EXTERNAL_NOTICE_BYTES = 2 * 1024 * 1024


class RuntimeDependencyNoticeError(RuntimeError):
    """Raised when dependency notice evidence cannot be built fail-closed."""


@dataclass(frozen=True, slots=True)
class RuntimeDependencyNoticeBundle:
    root: Path
    manifest_path: Path
    notice_files: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class ExternalArchiveNoticeSource:
    """Exact upstream source artifact used only when an installed wheel omits notice bytes."""

    archive_path: str | Path
    source_url: str
    source_sha256: str
    member_path: str


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
    if any(stem == base or stem.startswith(base + "-") for base in _LICENSE_BASENAMES):
        return True
    # Some upstream source archives use SPDX-style prefixes such as
    # ``MIT-LICENSE``. Accept only whole separator-delimited notice tokens; do
    # not use a substring test that would misclassify names such as LICENSEE.
    tokens = tuple(token for token in re.split(r"[-_]+", stem) if token)
    return any(token in _LICENSE_BASENAMES for token in tokens)


def _inventory_notice_candidate(value: object) -> PurePosixPath | None:
    token = str(value or "").strip().replace("\\", "/")
    if not token:
        return None
    observed = PurePosixPath(token)
    if not _looks_like_notice(observed):
        return None
    return _safe_relative_notice(token)


def _candidate_notice_paths(dist: Any) -> tuple[PurePosixPath, ...]:
    candidates: dict[str, PurePosixPath] = {}
    try:
        files = tuple(getattr(dist, "files", None) or ())
    except Exception:
        files = ()
    for value in files:
        path = _inventory_notice_candidate(value)
        if path is not None:
            candidates.setdefault(path.as_posix().casefold(), path)

    for value in _metadata_values(dist, "License-File"):
        path = _safe_relative_notice(value)
        candidates.setdefault(path.as_posix().casefold(), path)

    return tuple(candidates[key] for key in sorted(candidates))


def _try_locate_notice(dist: Any, relative: PurePosixPath) -> Path | None:
    locator = getattr(dist, "locate_file", None)
    if not callable(locator):
        raise RuntimeDependencyNoticeError("distribution cannot locate license files")
    try:
        located = Path(locator(str(relative)))
        resolved = located.resolve(strict=True)
    except FileNotFoundError:
        return None
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeDependencyNoticeError("distribution license file cannot be inspected") from exc
    try:
        if not resolved.is_file() or resolved.is_symlink() or resolved.stat().st_size <= 0:
            return None
    except OSError as exc:
        raise RuntimeDependencyNoticeError("distribution license file cannot be inspected") from exc
    return resolved


def _python_license_path(explicit: str | Path | None) -> Path:
    candidates = (
        (Path(explicit),)
        if explicit is not None
        else (
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
        try:
            if resolved.is_file() and not resolved.is_symlink() and resolved.stat().st_size > 0:
                return resolved
        except OSError:
            continue
    raise RuntimeDependencyNoticeError("Python license file is unavailable")


def _project_urls(dist: Any) -> tuple[str, ...]:
    values: list[str] = []
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


def _validated_external_sources(
    sources: Mapping[str, ExternalArchiveNoticeSource] | None,
    inventory: set[str],
) -> dict[str, ExternalArchiveNoticeSource]:
    result: dict[str, ExternalArchiveNoticeSource] = {}
    for raw_name, source in (sources or {}).items():
        name = _clean_distribution_name(raw_name).casefold()
        if name not in inventory:
            raise RuntimeDependencyNoticeError("external notice source is outside dependency inventory")
        if name in result:
            raise RuntimeDependencyNoticeError("external notice source inventory contains duplicates")
        if not isinstance(source, ExternalArchiveNoticeSource):
            raise RuntimeDependencyNoticeError("external notice source contract is invalid")
        digest = str(source.source_sha256 or "").strip().casefold()
        if not _SHA256.fullmatch(digest):
            raise RuntimeDependencyNoticeError("external notice source sha256 is invalid")
        parsed = urlparse(str(source.source_url or "").strip())
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise RuntimeDependencyNoticeError("external notice source URL is invalid")
        member = _safe_relative_notice(source.member_path)
        if not _looks_like_notice(member):
            raise RuntimeDependencyNoticeError("external notice archive member is not a license/notice")
        result[name] = ExternalArchiveNoticeSource(
            archive_path=source.archive_path,
            source_url=parsed.geturl(),
            source_sha256=digest,
            member_path=member.as_posix(),
        )
    return result


def _read_external_notice(source: ExternalArchiveNoticeSource) -> bytes:
    try:
        archive = Path(source.archive_path).resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeDependencyNoticeError("external notice source archive is unavailable") from exc
    try:
        if not archive.is_file() or archive.is_symlink() or archive.stat().st_size <= 0:
            raise RuntimeDependencyNoticeError("external notice source archive is invalid")
    except OSError as exc:
        raise RuntimeDependencyNoticeError("external notice source archive is invalid") from exc
    if _sha256(archive) != source.source_sha256:
        raise RuntimeDependencyNoticeError("external notice source archive sha256 mismatch")

    try:
        with tarfile.open(archive, mode="r:gz") as package:
            member = package.getmember(source.member_path)
            if not member.isfile() or member.issym() or member.islnk():
                raise RuntimeDependencyNoticeError("external notice archive member is not a regular file")
            if member.size <= 0 or member.size > _MAX_EXTERNAL_NOTICE_BYTES:
                raise RuntimeDependencyNoticeError("external notice archive member size is invalid")
            handle = package.extractfile(member)
            if handle is None:
                raise RuntimeDependencyNoticeError("external notice archive member cannot be read")
            data = handle.read(_MAX_EXTERNAL_NOTICE_BYTES + 1)
    except RuntimeDependencyNoticeError:
        raise
    except (tarfile.TarError, KeyError, OSError) as exc:
        raise RuntimeDependencyNoticeError("external notice source archive cannot be inspected") from exc
    if not data or len(data) > _MAX_EXTERNAL_NOTICE_BYTES:
        raise RuntimeDependencyNoticeError("external notice archive member bytes are invalid")
    return data


def build_runtime_dependency_notice_bundle(
    distributions: Iterable[str],
    output_root: str | Path,
    *,
    expected_versions: dict[str, str] | None = None,
    distribution_loader: Callable[[str], Any] = metadata.distribution,
    python_license_path: str | Path | None = None,
    python_version: str | None = None,
    external_notice_sources: Mapping[str, ExternalArchiveNoticeSource] | None = None,
) -> RuntimeDependencyNoticeBundle:
    """Publish deterministic exact-byte license evidence for a qualified stack."""

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
    external = _validated_external_sources(external_notice_sources, seen)

    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{root.name}.dependency-notices-", dir=root.parent))
    published_names: list[str] = []
    manifest_rows: list[dict[str, object]] = []
    try:
        python_license = _python_license_path(python_license_path)
        python_notice = staging / "Python-LICENSE.txt"
        shutil.copyfile(python_license, python_notice, follow_symlinks=False)
        published_names.append(python_notice.name)
        resolved_python_version = python_version or ".".join(str(value) for value in sys.version_info[:3])
        resolved_python_version = _clean_version(resolved_python_version)

        for name in sorted(names, key=str.casefold):
            try:
                dist = distribution_loader(name)
            except Exception as exc:
                raise RuntimeDependencyNoticeError(f"installed distribution is unavailable: {name}") from exc
            version = _clean_version(getattr(dist, "version", ""))
            wanted = expected.get(name.casefold())
            if wanted is not None and version != wanted:
                raise RuntimeDependencyNoticeError(f"installed distribution version mismatch: {name}")

            rows: list[dict[str, str]] = []
            seen_sources: set[Path] = set()
            prefix = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._")
            for relative in _candidate_notice_paths(dist):
                source = _try_locate_notice(dist, relative)
                if source is None or source in seen_sources:
                    continue
                seen_sources.add(source)
                index = len(rows) + 1
                suffix = source.suffix if 0 < len(source.suffix) <= 16 else ".txt"
                target_name = f"{prefix}-{version}-NOTICE-{index:02d}{suffix}"
                target = staging / target_name
                shutil.copyfile(source, target, follow_symlinks=False)
                published_names.append(target.name)
                rows.append({
                    "source_kind": "installed_distribution",
                    "source_path": relative.as_posix(),
                    "packaged_file": target.name,
                    "sha256": _sha256(target),
                })

            if not rows and name.casefold() in external:
                source = external[name.casefold()]
                data = _read_external_notice(source)
                target_name = f"{prefix}-{version}-NOTICE-01.txt"
                target = staging / target_name
                target.write_bytes(data)
                published_names.append(target.name)
                rows.append({
                    "source_kind": "verified_source_archive",
                    "source_path": source.member_path,
                    "source_url": source.source_url,
                    "source_artifact_sha256": source.source_sha256,
                    "packaged_file": target.name,
                    "sha256": _sha256(target),
                })

            if not rows:
                raise RuntimeDependencyNoticeError(
                    f"installed distribution has no real license/notice file: {name}"
                )

            manifest_rows.append({
                "distribution": name,
                "version": version,
                "license_expression": _metadata_value(dist, "License-Expression"),
                "license_metadata": _metadata_value(dist, "License"),
                "project_urls": list(_project_urls(dist)),
                "notice_files": rows,
            })

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
        published_names.append(manifest_path.name)

        if root.exists():
            raise RuntimeDependencyNoticeError("dependency notice output appeared during publication")
        staging.rename(root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return RuntimeDependencyNoticeBundle(
        root=root,
        manifest_path=root / "PYTHON_RUNTIME_DEPENDENCIES.json",
        notice_files=tuple(root / name for name in published_names),
    )


__all__ = [
    "ExternalArchiveNoticeSource",
    "RuntimeDependencyNoticeBundle",
    "RuntimeDependencyNoticeError",
    "build_runtime_dependency_notice_bundle",
]
