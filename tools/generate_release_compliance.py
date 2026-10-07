#!/usr/bin/env python3
"""Generate and verify deterministic release-compliance evidence.

The tool inventories release/runtime inputs only. It does not infer license
ownership or dependency pedigree from file names.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable, Sequence

TOOL_ID = "accessible-chess-release-evidence/1"
SCHEMA_ID = "accessible-chess.release-provenance.v1"
DEFAULT_INCLUDES = (
    "acs",
    "web",
    "packaging",
    "run_accessible_chess.py",
    "run_accessible_chess_v2.py",
    "VERSION.txt",
    "HOTKEYS_EN.txt",
    "HOTKEYS_UA.txt",
)
HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
_MEDIA_TYPES = {
    ".config": "application/xml",
    ".css": "text/css",
    ".html": "text/html",
    ".js": "text/javascript",
    ".json": "application/json",
    ".md": "text/markdown",
    ".py": "text/x-python",
    ".txt": "text/plain",
    ".xml": "application/xml",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
}


class EvidenceError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True)
class FileRecord:
    path: str
    size: int
    sha256: str
    media_type: str

    def canonical_line(self) -> str:
        return f"{self.path}\0{self.size}\0{self.sha256}\0{self.media_type}\n"


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _normalize_created(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise EvidenceError("created timestamp must not be empty")
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = dt.datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise EvidenceError(f"invalid RFC3339 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise EvidenceError("created timestamp must include a timezone")
    utc = parsed.astimezone(dt.timezone.utc).replace(microsecond=0)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_commit(value: str) -> str:
    commit = value.strip().lower()
    if not HEX40_RE.fullmatch(commit):
        raise EvidenceError("source commit must be exactly 40 lowercase hex characters")
    return commit


def _is_linklike(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _safe_candidate(root: Path, relative: str) -> Path:
    rel_path = Path(relative)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        raise EvidenceError(f"unsafe include path: {relative!r}")
    candidate = root / rel_path
    cursor = root
    for part in rel_path.parts:
        cursor = cursor / part
        if _is_linklike(cursor):
            raise EvidenceError(
                f"symlinks/junctions are not allowed in release evidence: {cursor}"
            )
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise EvidenceError(f"required release input is missing: {candidate}") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise EvidenceError(f"path escapes repository root: {relative!r}") from exc
    return candidate


def _git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise EvidenceError(f"git source-identity check failed: {detail.strip()}") from exc
    return completed.stdout.strip()


def _assert_git_source_identity(
    root: Path,
    *,
    source_commit: str,
    includes: Sequence[str],
) -> None:
    head = _git(root, "rev-parse", "--verify", "HEAD").lower()
    if head != source_commit:
        raise EvidenceError(
            f"source commit mismatch: declared={source_commit} actual={head}"
        )
    status = _git(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        *includes,
    )
    if status:
        raise EvidenceError(
            "scoped release inputs contain uncommitted changes; "
            "provenance requires committed bytes"
        )


def _iter_regular_files(root: Path, candidate: Path) -> Iterable[Path]:
    if _is_linklike(candidate):
        raise EvidenceError(f"symlinks/junctions are not allowed in release evidence: {candidate}")
    if not candidate.exists():
        raise EvidenceError(f"required release input is missing: {candidate}")
    if candidate.is_file():
        yield candidate
        return
    if not candidate.is_dir():
        raise EvidenceError(f"unsupported release input type: {candidate}")
    for path in sorted(candidate.rglob("*"), key=lambda item: item.as_posix()):
        if _is_linklike(path):
            raise EvidenceError(f"symlinks/junctions are not allowed in release evidence: {path}")
        try:
            path.resolve(strict=True).relative_to(root)
        except (OSError, ValueError) as exc:
            raise EvidenceError(f"release input escapes repository root: {path}") from exc
        if path.is_dir():
            continue
        if not path.is_file():
            raise EvidenceError(f"unsupported release input type: {path}")
        yield path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def collect_runtime_files(root: Path, includes: Sequence[str]) -> list[FileRecord]:
    root = root.resolve(strict=True)
    seen: set[str] = set()
    records: list[FileRecord] = []
    for include in includes:
        candidate = _safe_candidate(root, include)
        for path in _iter_regular_files(root, candidate):
            relative = path.relative_to(root).as_posix()
            if relative in seen:
                continue
            seen.add(relative)
            media_type = _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
            records.append(
                FileRecord(
                    path=relative,
                    size=path.stat().st_size,
                    sha256=_sha256_file(path),
                    media_type=media_type,
                )
            )
    records.sort(key=lambda item: item.path)
    if not records:
        raise EvidenceError("release inventory is empty")
    return records


def inventory_digest(records: Sequence[FileRecord]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(record.canonical_line().encode("utf-8"))
    return digest.hexdigest()


def read_version(root: Path) -> str:
    version_file = root / "VERSION.txt"
    if not version_file.is_file():
        raise EvidenceError("VERSION.txt is required")
    version = version_file.read_text(encoding="utf-8").strip()
    if not version or len(version) > 128 or any(ord(ch) < 32 for ch in version):
        raise EvidenceError("VERSION.txt contains an invalid version value")
    return version


def _spdx_id_for_path(path: str) -> str:
    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()[:24]
    return f"SPDXRef-File-{digest}"


def build_spdx(
    records: Sequence[FileRecord],
    *,
    version: str,
    source_commit: str,
    created: str,
) -> dict:
    package_id = "SPDXRef-Package-AccessibleChess"
    files = []
    relationships = [
        {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": package_id,
        }
    ]
    for record in records:
        spdx_id = _spdx_id_for_path(record.path)
        files.append(
            {
                "SPDXID": spdx_id,
                "fileName": f"./{record.path}",
                "checksums": [{"algorithm": "SHA256", "checksumValue": record.sha256}],
                "licenseConcluded": "NOASSERTION",
                "licenseInfoInFiles": ["NOASSERTION"],
                "copyrightText": "NOASSERTION",
            }
        )
        relationships.append(
            {
                "spdxElementId": package_id,
                "relationshipType": "CONTAINS",
                "relatedSpdxElement": spdx_id,
            }
        )
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"Accessible Chess {version} runtime inventory",
        "documentNamespace": (
            "https://github.com/Oleksii-debug/Accessible-Chess/spdx/"
            f"{source_commit}/{inventory_digest(records)}"
        ),
        "creationInfo": {
            "created": created,
            "creators": [f"Tool: {TOOL_ID}"],
        },
        "documentComment": (
            "Deterministic file-level inventory of release/runtime inputs. "
            "NOASSERTION is deliberate: this evidence does not infer third-party "
            "license or ownership claims."
        ),
        "packages": [
            {
                "SPDXID": package_id,
                "name": "Accessible Chess",
                "versionInfo": version,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
                "copyrightText": "NOASSERTION",
                "externalRefs": [
                    {
                        "referenceCategory": "OTHER",
                        "referenceType": "source-commit",
                        "referenceLocator": source_commit,
                    }
                ],
            }
        ],
        "files": files,
        "relationships": relationships,
    }


def build_provenance(
    records: Sequence[FileRecord],
    *,
    version: str,
    source_commit: str,
    created: str,
    includes: Sequence[str],
) -> dict:
    return {
        "schema": SCHEMA_ID,
        "generator": TOOL_ID,
        "product": {"name": "Accessible Chess", "version": version},
        "source": {
            "commit": source_commit,
            "git_head_verified": True,
            "scoped_inputs_clean": True,
        },
        "created": created,
        "scope": {
            "kind": "runtime-release-inputs",
            "includes": list(includes),
            "file_count": len(records),
        },
        "inventory_sha256": inventory_digest(records),
        "files": [dataclasses.asdict(record) for record in records],
        "claims": {
            "human_tested": False,
            "nvda_verified": False,
            "final_windows_zip": False,
            "license_inference_performed": False,
        },
    }


def generate(
    *,
    root: Path,
    output_dir: Path,
    source_commit: str,
    created: str,
    includes: Sequence[str],
) -> tuple[Path, ...]:
    root = root.resolve(strict=True)
    source_commit = _validate_commit(source_commit)
    created = _normalize_created(created)
    for include in includes:
        _safe_candidate(root, include)
    _assert_git_source_identity(
        root,
        source_commit=source_commit,
        includes=includes,
    )
    version = read_version(root)
    records = collect_runtime_files(root, includes)
    spdx = build_spdx(
        records,
        version=version,
        source_commit=source_commit,
        created=created,
    )
    provenance = build_provenance(
        records,
        version=version,
        source_commit=source_commit,
        created=created,
        includes=includes,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    spdx_path = output_dir / "accessible-chess.spdx.json"
    provenance_path = output_dir / "accessible-chess.provenance.json"
    spdx_path.write_bytes(_json_bytes(spdx))
    provenance_path.write_bytes(_json_bytes(provenance))
    manifest_path = output_dir / "accessible-chess.evidence.sha256"
    manifest_lines = []
    for path in (spdx_path, provenance_path):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest_lines.append(f"{digest}  {path.name}\n")
    manifest_path.write_text("".join(manifest_lines), encoding="utf-8", newline="\n")
    return spdx_path, provenance_path, manifest_path


class tempfile_directory:
    def __init__(self) -> None:
        self._path: str | None = None

    def __enter__(self) -> str:
        import tempfile
        self._path = tempfile.mkdtemp(prefix="accessible-chess-release-evidence-")
        return self._path

    def __exit__(self, exc_type, exc, tb) -> None:
        import shutil
        if self._path is not None:
            shutil.rmtree(self._path, ignore_errors=True)


def verify(
    *,
    root: Path,
    evidence_dir: Path,
    source_commit: str,
    created: str,
    includes: Sequence[str],
) -> None:
    with tempfile_directory() as temp:
        expected_dir = Path(temp)
        expected_paths = generate(
            root=root,
            output_dir=expected_dir,
            source_commit=source_commit,
            created=created,
            includes=includes,
        )
        for expected_path in expected_paths:
            actual_path = evidence_dir / expected_path.name
            if not actual_path.is_file():
                raise EvidenceError(f"missing evidence file: {actual_path}")
            expected = expected_path.read_bytes()
            actual = actual_path.read_bytes()
            if actual != expected:
                raise EvidenceError(
                    f"release evidence mismatch: {actual_path.name}; "
                    "regenerate from the exact source commit"
                )


def _includes_from_args(values: Sequence[str] | None) -> tuple[str, ...]:
    if not values:
        return DEFAULT_INCLUDES
    normalized = tuple(item.strip() for item in values if item.strip())
    if not normalized:
        raise EvidenceError("at least one non-empty include path is required")
    return normalized


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("generate", "verify"):
        command = subparsers.add_parser(name)
        command.add_argument("--root", type=Path, default=Path("."))
        command.add_argument("--source-commit", required=True)
        command.add_argument("--created", required=True)
        command.add_argument(
            "--include",
            action="append",
            dest="includes",
            help="Runtime/release path to inventory; repeatable",
        )
        target = "--output-dir" if name == "generate" else "--evidence-dir"
        command.add_argument(target, type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        includes = _includes_from_args(args.includes)
        if args.command == "generate":
            paths = generate(
                root=args.root,
                output_dir=args.output_dir,
                source_commit=args.source_commit,
                created=args.created,
                includes=includes,
            )
            for path in paths:
                print(path)
        else:
            verify(
                root=args.root,
                evidence_dir=args.evidence_dir,
                source_commit=args.source_commit,
                created=args.created,
                includes=includes,
            )
            print("RELEASE_COMPLIANCE_EVIDENCE=PASS")
    except (EvidenceError, OSError) as exc:
        print(f"release evidence error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
