from __future__ import annotations

"""Fail-closed materialization of the pinned LiveKit browser SDK for packaging.

The build workflow downloads the npm tarball. This module owns identity and archive
validation, then publishes only the reviewed UMD bundle and redistribution notices.
It intentionally performs no network access and never reads deployment credentials.
"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import tempfile

LIVEKIT_CLIENT_VERSION = "2.22.3"
LIVEKIT_CLIENT_NPM_TARBALL_URL = (
    "https://registry.npmjs.org/livekit-client/-/"
    f"livekit-client-{LIVEKIT_CLIENT_VERSION}.tgz"
)
LIVEKIT_CLIENT_NPM_INTEGRITY = (
    "sha512-jw9zBKXY5Gtr5MZ7vEON3QhMNccuDvYHck1PFSyG1aaateQPqgKZFBMgZkFZaXHIf9RV4MDW5xpTK2b/+qbwOg=="
)
LIVEKIT_CLIENT_UPSTREAM_TAG = f"v{LIVEKIT_CLIENT_VERSION}"
LIVEKIT_CLIENT_LICENSE_ID = "Apache-2.0"

_PACKAGE_JSON = "package/package.json"
_BUNDLE = "package/dist/livekit-client.umd.js"
_LICENSE = "package/LICENSE"
_NOTICE = "package/NOTICE"
_MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
_MAX_MEMBERS = 20_000
_MAX_TOTAL_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
_MAX_MEMBER_BYTES = 16 * 1024 * 1024
_MIN_BUNDLE_BYTES = 100_000
_MAX_BUNDLE_BYTES = 8 * 1024 * 1024
_MIN_LICENSE_BYTES = 5_000
_MAX_LICENSE_BYTES = 128 * 1024
_MAX_NOTICE_BYTES = 256 * 1024
_MAX_PROVENANCE_BYTES = 64 * 1024
_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
    "com¹",
    "com²",
    "com³",
    "lpt¹",
    "lpt²",
    "lpt³",
}

# client-sdk-js@v2.22.3 upstream NOTICE. npm may omit NOTICE because its package
# whitelist is narrower than the source tree, so preserve the reviewed notice
# explicitly next to the redistributed UMD bundle.
_UPSTREAM_NOTICE = """Copyright 2021 LiveKit, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""


class LiveKitClientSdkStageError(RuntimeError):
    """Raised when the downloaded SDK cannot be safely identified and staged."""


def _is_reparse(info: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & flag)


def _same_file_snapshot(left: os.stat_result, right: os.stat_result) -> bool:
    """Compare pathname/open-handle identity plus content-relevant metadata."""

    try:
        same_identity = os.path.samestat(left, right)
    except (AttributeError, OSError):
        same_identity = (
            getattr(left, "st_dev", None),
            getattr(left, "st_ino", None),
        ) == (
            getattr(right, "st_dev", None),
            getattr(right, "st_ino", None),
        )
    return bool(
        same_identity
        and int(left.st_size) == int(right.st_size)
        and getattr(left, "st_mtime_ns", None) == getattr(right, "st_mtime_ns", None)
    )


def _snapshot_archive(
    archive_path: Path,
    *,
    expected_integrity: str,
):
    """Return an immutable, verified archive snapshot without following links."""

    try:
        metadata = archive_path.lstat()
    except FileNotFoundError as exc:
        raise LiveKitClientSdkStageError(
            "LiveKit npm archive is missing or empty"
        ) from exc
    except OSError as exc:
        raise LiveKitClientSdkStageError("LiveKit npm archive is unreadable") from exc

    if (
        stat.S_ISLNK(metadata.st_mode)
        or _is_reparse(metadata)
        or not stat.S_ISREG(metadata.st_mode)
    ):
        raise LiveKitClientSdkStageError(
            "LiveKit npm archive must be a regular file, not a link or reparse point"
        )
    if metadata.st_size <= 0:
        raise LiveKitClientSdkStageError("LiveKit npm archive is missing or empty")
    if metadata.st_size > _MAX_ARCHIVE_BYTES:
        raise LiveKitClientSdkStageError(
            "LiveKit npm archive exceeds the compressed-size limit"
        )

    try:
        source = archive_path.open("rb")
    except OSError as exc:
        raise LiveKitClientSdkStageError("LiveKit npm archive is unreadable") from exc

    snapshot = tempfile.TemporaryFile()
    try:
        with source:
            opened = os.fstat(source.fileno())
            if not stat.S_ISREG(opened.st_mode) or _is_reparse(opened):
                raise LiveKitClientSdkStageError(
                    "LiveKit npm archive must remain a regular non-reparse file"
                )
            if not _same_file_snapshot(metadata, opened):
                raise LiveKitClientSdkStageError(
                    "LiveKit npm archive changed while it was being opened"
                )

            digest = hashlib.sha512()
            copied = 0
            while True:
                block = source.read(1024 * 1024)
                if not block:
                    break
                copied += len(block)
                if copied > _MAX_ARCHIVE_BYTES:
                    raise LiveKitClientSdkStageError(
                        "LiveKit npm archive exceeds the compressed-size limit"
                    )
                digest.update(block)
                snapshot.write(block)

            after_read = os.fstat(source.fileno())
            try:
                after_path = archive_path.lstat()
            except OSError as exc:
                raise LiveKitClientSdkStageError(
                    "LiveKit npm archive changed while it was being read"
                ) from exc
            if (
                stat.S_ISLNK(after_path.st_mode)
                or _is_reparse(after_path)
                or not stat.S_ISREG(after_path.st_mode)
                or not _same_file_snapshot(opened, after_read)
                or not _same_file_snapshot(after_read, after_path)
                or copied != int(after_read.st_size)
            ):
                raise LiveKitClientSdkStageError(
                    "LiveKit npm archive changed while it was being read"
                )
        actual_integrity = (
            "sha512-" + base64.b64encode(digest.digest()).decode("ascii")
        )
        if actual_integrity != expected_integrity:
            raise LiveKitClientSdkStageError(
                "LiveKit npm archive SHA-512 integrity mismatch"
            )
        snapshot.seek(0)
        return snapshot
    except Exception:
        snapshot.close()
        raise


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_json_object(data: bytes, *, label: str) -> dict[str, object]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LiveKitClientSdkStageError(f"{label} is not UTF-8") from exc

    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise LiveKitClientSdkStageError(f"{label} contains duplicate JSON keys")
            result[key] = value
        return result

    try:
        parsed = json.loads(text, object_pairs_hook=object_pairs)
    except LiveKitClientSdkStageError:
        raise
    except (TypeError, ValueError) as exc:
        raise LiveKitClientSdkStageError(f"{label} is invalid JSON") from exc
    if type(parsed) is not dict:
        raise LiveKitClientSdkStageError(f"{label} root must be an object")
    return parsed


def _safe_member_name(name: str) -> str:
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise LiveKitClientSdkStageError("LiveKit npm archive contains an unsafe member name")
    raw_parts = name.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts[:-1]):
        raise LiveKitClientSdkStageError("LiveKit npm archive contains an unsafe member name")
    if raw_parts[-1] in {".", ".."}:
        raise LiveKitClientSdkStageError("LiveKit npm archive contains an unsafe member name")
    path_parts = raw_parts[:-1] if raw_parts[-1] == "" else raw_parts
    for part in path_parts:
        if (
            ":" in part
            or part.rstrip(" .") != part
            or any(ord(character) < 32 or ord(character) == 127 for character in part)
            or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES
        ):
            raise LiveKitClientSdkStageError(
                "LiveKit npm archive contains a Windows-unsafe member name"
            )
    path = PurePosixPath(name)
    canonical = path.as_posix()
    if path.is_absolute() or canonical not in {name, name.rstrip("/")}:
        raise LiveKitClientSdkStageError("LiveKit npm archive contains an unsafe member name")
    if not path.parts or path.parts[0] != "package":
        raise LiveKitClientSdkStageError("LiveKit npm archive escaped its package root")
    return canonical


def _read_regular_member(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    *,
    label: str,
) -> bytes:
    if not member.isfile():
        raise LiveKitClientSdkStageError(f"{label} is not a regular file")
    if member.size < 0 or member.size > _MAX_MEMBER_BYTES:
        raise LiveKitClientSdkStageError(f"{label} has an unsafe size")
    stream = archive.extractfile(member)
    if stream is None:
        raise LiveKitClientSdkStageError(f"{label} is unreadable")
    data = stream.read(_MAX_MEMBER_BYTES + 1)
    if len(data) != member.size or len(data) > _MAX_MEMBER_BYTES:
        raise LiveKitClientSdkStageError(f"{label} size does not match archive metadata")
    return data


def _validated_payload(
    archive_path: Path,
    *,
    expected_integrity: str,
) -> tuple[bytes, bytes, bytes]:
    snapshot = _snapshot_archive(
        archive_path,
        expected_integrity=expected_integrity,
    )
    try:
        handle = tarfile.open(fileobj=snapshot, mode="r:gz")
    except (tarfile.TarError, OSError) as exc:
        snapshot.close()
        raise LiveKitClientSdkStageError("LiveKit npm archive is invalid") from exc

    with snapshot, handle as archive:
        by_name: dict[str, tarfile.TarInfo] = {}
        casefolded: set[str] = set()
        total = 0
        member_count = 0
        for member in archive:
            member_count += 1
            if member_count > _MAX_MEMBERS:
                raise LiveKitClientSdkStageError(
                    "LiveKit npm archive member-count limit exceeded"
                )
            safe_name = _safe_member_name(member.name)
            if not (member.isfile() or member.isdir()):
                raise LiveKitClientSdkStageError(
                    "LiveKit npm archive contains a link or special file"
                )
            folded = safe_name.casefold()
            if folded in casefolded:
                raise LiveKitClientSdkStageError(
                    "LiveKit npm archive contains duplicate member names"
                )
            casefolded.add(folded)
            if member.isfile():
                if member.size < 0 or member.size > _MAX_MEMBER_BYTES:
                    raise LiveKitClientSdkStageError(
                        "LiveKit npm archive member exceeds the size limit"
                    )
                total += member.size
                if total > _MAX_TOTAL_UNCOMPRESSED_BYTES:
                    raise LiveKitClientSdkStageError(
                        "LiveKit npm archive exceeds the uncompressed-size limit"
                    )
                by_name[safe_name] = member

        if member_count == 0:
            raise LiveKitClientSdkStageError(
                "LiveKit npm archive member-count limit exceeded"
            )

        for required in (_PACKAGE_JSON, _BUNDLE, _LICENSE):
            if required not in by_name:
                raise LiveKitClientSdkStageError(
                    f"LiveKit npm archive is missing {required}"
                )

        package_bytes = _read_regular_member(
            archive,
            by_name[_PACKAGE_JSON],
            label="LiveKit package metadata",
        )
        metadata = _strict_json_object(package_bytes, label="LiveKit package metadata")
        expected_metadata = {
            "name": "livekit-client",
            "version": LIVEKIT_CLIENT_VERSION,
            "license": LIVEKIT_CLIENT_LICENSE_ID,
            "main": "./dist/livekit-client.umd.js",
            "unpkg": "./dist/livekit-client.umd.js",
        }
        for key, expected in expected_metadata.items():
            if metadata.get(key) != expected:
                raise LiveKitClientSdkStageError(
                    f"LiveKit package metadata field {key} is not canonical"
                )

        bundle = _read_regular_member(
            archive,
            by_name[_BUNDLE],
            label="LiveKit UMD bundle",
        )
        if not (_MIN_BUNDLE_BYTES <= len(bundle) <= _MAX_BUNDLE_BYTES):
            raise LiveKitClientSdkStageError("LiveKit UMD bundle has an unexpected size")
        if b"LivekitClient" not in bundle or b"Room" not in bundle:
            raise LiveKitClientSdkStageError(
                "LiveKit UMD bundle does not expose the expected browser API markers"
            )

        license_bytes = _read_regular_member(
            archive,
            by_name[_LICENSE],
            label="LiveKit license",
        )
        if (
            len(license_bytes) < _MIN_LICENSE_BYTES
            or b"Apache License" not in license_bytes
            or b"Version 2.0" not in license_bytes
        ):
            raise LiveKitClientSdkStageError("LiveKit license payload is invalid")

        notice_bytes = _UPSTREAM_NOTICE.encode("utf-8")
        if _NOTICE in by_name:
            archive_notice = _read_regular_member(
                archive,
                by_name[_NOTICE],
                label="LiveKit NOTICE",
            )
            if b"LiveKit" not in archive_notice or b"Apache License" not in archive_notice:
                raise LiveKitClientSdkStageError("LiveKit NOTICE payload is invalid")
            notice_bytes = archive_notice

    return bundle, license_bytes, notice_bytes


def _provenance_bytes(
    bundle: bytes,
    license_bytes: bytes,
    notice_bytes: bytes,
    *,
    expected_integrity: str,
) -> bytes:
    provenance = {
        "schema_version": 1,
        "component": "livekit-client",
        "version": LIVEKIT_CLIENT_VERSION,
        "license_id": LIVEKIT_CLIENT_LICENSE_ID,
        "source": LIVEKIT_CLIENT_NPM_TARBALL_URL,
        "upstream_tag": LIVEKIT_CLIENT_UPSTREAM_TAG,
        "npm_integrity": expected_integrity,
        "bundle_sha256": _sha256_bytes(bundle),
        "license_sha256": _sha256_bytes(license_bytes),
        "notice_sha256": _sha256_bytes(notice_bytes),
    }
    return (
        json.dumps(provenance, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _read_staged_file_snapshot(
    path: Path,
    *,
    label: str,
    max_bytes: int,
) -> bytes:
    try:
        before = path.lstat()
    except OSError as exc:
        raise LiveKitClientSdkStageError(f"{label} is missing or unreadable") from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or _is_reparse(before)
        or not stat.S_ISREG(before.st_mode)
    ):
        raise LiveKitClientSdkStageError(
            f"{label} must be a regular non-reparse file"
        )
    if before.st_size <= 0 or before.st_size > max_bytes:
        raise LiveKitClientSdkStageError(f"{label} has an unsafe size")

    try:
        source = path.open("rb")
    except OSError as exc:
        raise LiveKitClientSdkStageError(f"{label} is missing or unreadable") from exc
    with source:
        opened = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(opened.st_mode)
            or _is_reparse(opened)
            or not _same_file_snapshot(before, opened)
        ):
            raise LiveKitClientSdkStageError(f"{label} changed while being opened")
        data = source.read(max_bytes + 1)
        after_read = os.fstat(source.fileno())
        try:
            after_path = path.lstat()
        except OSError as exc:
            raise LiveKitClientSdkStageError(f"{label} changed while being read") from exc
        if (
            len(data) > max_bytes
            or len(data) != int(after_read.st_size)
            or stat.S_ISLNK(after_path.st_mode)
            or _is_reparse(after_path)
            or not stat.S_ISREG(after_path.st_mode)
            or not _same_file_snapshot(opened, after_read)
            or not _same_file_snapshot(after_read, after_path)
        ):
            raise LiveKitClientSdkStageError(f"{label} changed while being read")
    return data


def _reject_linked_output_ancestors(output: Path) -> None:
    for ancestor in (output.parent, *output.parent.parents):
        if not os.path.lexists(ancestor):
            continue
        try:
            info = ancestor.lstat()
        except OSError as exc:
            raise LiveKitClientSdkStageError(
                "LiveKit SDK output path ancestor cannot be inspected"
            ) from exc
        if stat.S_ISLNK(info.st_mode) or _is_reparse(info):
            raise LiveKitClientSdkStageError(
                "LiveKit SDK output path must not traverse a symlink or reparse point"
            )
        if not stat.S_ISDIR(info.st_mode):
            raise LiveKitClientSdkStageError(
                "LiveKit SDK output path ancestor must be a directory"
            )


def stage_livekit_client_sdk(
    archive_path: str | Path,
    output_dir: str | Path,
    *,
    expected_integrity: str = LIVEKIT_CLIENT_NPM_INTEGRITY,
) -> Path:
    archive = Path(archive_path)
    output = Path(output_dir)
    if os.path.lexists(output):
        raise LiveKitClientSdkStageError("LiveKit SDK output directory already exists")
    _reject_linked_output_ancestors(output)

    bundle, license_bytes, notice_bytes = _validated_payload(
        archive,
        expected_integrity=expected_integrity,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    _reject_linked_output_ancestors(output)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=output.parent))
    try:
        (staging / "livekit-client.umd.js").write_bytes(bundle)
        (staging / "LICENSE").write_bytes(license_bytes)
        (staging / "NOTICE").write_bytes(notice_bytes)
        (staging / "provenance.json").write_bytes(
            _provenance_bytes(
                bundle,
                license_bytes,
                notice_bytes,
                expected_integrity=expected_integrity,
            )
        )
        if os.path.lexists(output):
            raise LiveKitClientSdkStageError(
                "LiveKit SDK output directory appeared during staging"
            )
        _reject_linked_output_ancestors(output)
        staging.rename(output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return output


def verify_staged_livekit_client_sdk(
    archive_path: str | Path,
    staged_dir: str | Path,
    *,
    expected_integrity: str = LIVEKIT_CLIENT_NPM_INTEGRITY,
) -> Path:
    """Prove an existing staged SDK tree is byte-derived from the pinned npm archive."""

    archive = Path(archive_path)
    staged = Path(staged_dir)
    if not os.path.lexists(staged):
        raise LiveKitClientSdkStageError("staged LiveKit SDK directory is missing")
    _reject_linked_output_ancestors(staged / ".verification-probe")
    try:
        before = staged.lstat()
    except OSError as exc:
        raise LiveKitClientSdkStageError(
            "staged LiveKit SDK directory cannot be inspected"
        ) from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or _is_reparse(before)
        or not stat.S_ISDIR(before.st_mode)
    ):
        raise LiveKitClientSdkStageError(
            "staged LiveKit SDK root must be a real directory"
        )

    bundle, license_bytes, notice_bytes = _validated_payload(
        archive,
        expected_integrity=expected_integrity,
    )
    expected = {
        "livekit-client.umd.js": (
            bundle,
            _MAX_BUNDLE_BYTES,
            "staged LiveKit browser SDK",
        ),
        "LICENSE": (
            license_bytes,
            _MAX_LICENSE_BYTES,
            "staged LiveKit license",
        ),
        "NOTICE": (
            notice_bytes,
            _MAX_NOTICE_BYTES,
            "staged LiveKit NOTICE",
        ),
        "provenance.json": (
            _provenance_bytes(
                bundle,
                license_bytes,
                notice_bytes,
                expected_integrity=expected_integrity,
            ),
            _MAX_PROVENANCE_BYTES,
            "staged LiveKit provenance",
        ),
    }

    try:
        names = {entry.name for entry in staged.iterdir()}
    except OSError as exc:
        raise LiveKitClientSdkStageError(
            "staged LiveKit SDK directory cannot be enumerated"
        ) from exc
    if names != set(expected):
        raise LiveKitClientSdkStageError(
            "staged LiveKit SDK inventory does not match pinned release"
        )

    for name, (canonical_bytes, max_bytes, label) in expected.items():
        actual = _read_staged_file_snapshot(
            staged / name,
            label=label,
            max_bytes=max_bytes,
        )
        if actual != canonical_bytes:
            raise LiveKitClientSdkStageError(
                f"{label} does not match pinned npm archive"
            )

    try:
        after = staged.lstat()
    except OSError as exc:
        raise LiveKitClientSdkStageError(
            "staged LiveKit SDK directory changed during verification"
        ) from exc
    if (
        stat.S_ISLNK(after.st_mode)
        or _is_reparse(after)
        or not stat.S_ISDIR(after.st_mode)
        or not _same_file_snapshot(before, after)
    ):
        raise LiveKitClientSdkStageError(
            "staged LiveKit SDK directory changed during verification"
        )
    return staged


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", nargs="?", help="downloaded livekit-client npm .tgz")
    parser.add_argument(
        "output",
        nargs="?",
        help="new output directory, or existing staged directory with --verify-existing",
    )
    parser.add_argument("--print-tarball-url", action="store_true")
    parser.add_argument("--print-version", action="store_true")
    parser.add_argument("--verify-existing", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.print_tarball_url or args.print_version:
        if (
            args.archive is not None
            or args.output is not None
            or args.verify_existing
        ):
            raise SystemExit("print mode does not accept archive/output arguments")
        print(
            LIVEKIT_CLIENT_NPM_TARBALL_URL
            if args.print_tarball_url
            else LIVEKIT_CLIENT_VERSION
        )
        return 0
    if args.archive is None or args.output is None:
        raise SystemExit("archive and output are required")
    if args.verify_existing:
        verified = verify_staged_livekit_client_sdk(args.archive, args.output)
        bundle_sha256 = hashlib.sha256(
            _read_staged_file_snapshot(
                verified / "livekit-client.umd.js",
                label="verified LiveKit browser SDK",
                max_bytes=_MAX_BUNDLE_BYTES,
            )
        ).hexdigest()
        print(f"LIVEKIT_CLIENT_VERSION={LIVEKIT_CLIENT_VERSION}")
        print(f"LIVEKIT_CLIENT_BUNDLE_SHA256={bundle_sha256}")
        print("LIVEKIT_CLIENT_SDK_VERIFY=PASS")
        return 0
    staged = stage_livekit_client_sdk(args.archive, args.output)
    bundle_sha256 = hashlib.sha256(
        _read_staged_file_snapshot(
            staged / "livekit-client.umd.js",
            label="staged LiveKit browser SDK",
            max_bytes=_MAX_BUNDLE_BYTES,
        )
    ).hexdigest()
    print(f"LIVEKIT_CLIENT_VERSION={LIVEKIT_CLIENT_VERSION}")
    print(f"LIVEKIT_CLIENT_BUNDLE_SHA256={bundle_sha256}")
    print("LIVEKIT_CLIENT_SDK_STAGE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
