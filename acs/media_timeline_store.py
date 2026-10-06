from __future__ import annotations

"""Append-only durable persistence for MediaPositionTimeline.

The store deliberately avoids a mutable "latest.json". Each revision is a
content-bound immutable snapshot published through the cross-repository
pinned-root/no-replace media-file primitive. Restart recovery selects and
verifies the highest valid revision for the requested session.
"""

import hashlib
import json
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .media_files import promote_partial_file
from .media_foundation import MediaContractError, MediaPositionTimeline
from .pinned_directory import pinned_real_directory


_SCHEMA_VERSION = 1
_MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024


def _session(value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise MediaContractError("session_id must be non-empty canonical text")
    if len(value) > 512 or any(ord(ch) < 32 for ch in value):
        raise MediaContractError("session_id is invalid")
    return value


def _revision(value: object) -> int:
    if type(value) is not int or value < 1:
        raise MediaContractError("timeline revision must be a positive integer")
    return value


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _material(
    *,
    session_id: str,
    revision: int,
    timeline: MediaPositionTimeline,
) -> dict[str, object]:
    return {
        "version": _SCHEMA_VERSION,
        "session_id": _session(session_id),
        "revision": _revision(revision),
        "timeline": timeline.to_payload(),
    }


def _material_digest(material: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json(material)).hexdigest()


@dataclass(frozen=True, slots=True)
class TimelineSnapshot:
    path: Path
    session_id: str
    revision: int
    digest_sha256: str
    timeline: MediaPositionTimeline


class MediaTimelineStore:
    def __init__(self, root: Path, *, max_snapshot_bytes: int = _MAX_SNAPSHOT_BYTES) -> None:
        if type(root) is not type(Path()):
            raise TypeError("root must be Path")
        if type(max_snapshot_bytes) is not int or max_snapshot_bytes <= 0:
            raise ValueError("max_snapshot_bytes must be positive")
        root.mkdir(parents=True, exist_ok=True)
        observed = root.lstat()
        if stat.S_ISLNK(observed.st_mode) or not stat.S_ISDIR(observed.st_mode):
            raise MediaContractError("timeline store root must be a real directory")
        self.root = root
        self.max_snapshot_bytes = max_snapshot_bytes

    @staticmethod
    def _session_key(session_id: str) -> str:
        return hashlib.sha256(_session(session_id).encode("utf-8")).hexdigest()[:24]

    def save(
        self,
        *,
        session_id: str,
        revision: int,
        timeline: MediaPositionTimeline,
    ) -> TimelineSnapshot:
        if type(timeline) is not MediaPositionTimeline:
            raise TypeError("timeline must be MediaPositionTimeline")
        session = _session(session_id)
        rev = _revision(revision)
        current = self.latest(session)
        if current is not None and rev <= current.revision:
            raise MediaContractError("timeline revision must advance monotonically")

        material = _material(session_id=session, revision=rev, timeline=timeline)
        digest = _material_digest(material)
        envelope = dict(material)
        envelope["digest_sha256"] = digest
        body = _canonical_json(envelope)
        if not 1 <= len(body) <= self.max_snapshot_bytes:
            raise MediaContractError("timeline snapshot exceeds configured byte bound")

        key = self._session_key(session)
        final_name = f"timeline-{key}-{rev:012d}-{digest}.json"
        final = self.root / final_name
        partial = self.root / f".{final_name}.{uuid.uuid4().hex}.partial"

        fd = os.open(
            partial,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        try:
            with os.fdopen(fd, "wb", closefd=False) as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(fd)

        file_sha = hashlib.sha256(body).hexdigest()
        try:
            promote_partial_file(
                partial,
                final,
                allowed_root=self.root,
                expected_sha256=file_sha,
                max_bytes=self.max_snapshot_bytes,
            )
        except Exception:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return TimelineSnapshot(final, session, rev, digest, timeline)

    def latest(self, session_id: str) -> TimelineSnapshot | None:
        session = _session(session_id)
        key = self._session_key(session)
        prefix = f"timeline-{key}-"
        candidates: list[tuple[int, Path]] = []

        with pinned_real_directory(self.root) as pinned:
            pinned.verify_binding()
            for entry in pinned.path.iterdir():
                name = entry.name
                if not name.startswith(prefix) or not name.endswith(".json"):
                    continue
                parts = name[:-5].split("-")
                if len(parts) != 4:
                    continue
                try:
                    rev = int(parts[2])
                except ValueError:
                    continue
                if rev < 1:
                    continue
                candidates.append((rev, entry))
            pinned.verify_binding()

            for _revision_number, path in sorted(candidates, reverse=True):
                snapshot = self._load_path(path, expected_session=session)
                if snapshot is not None:
                    # Surface visible root path rather than /proc/self/fd alias.
                    return TimelineSnapshot(
                        self.root / path.name,
                        snapshot.session_id,
                        snapshot.revision,
                        snapshot.digest_sha256,
                        snapshot.timeline,
                    )
        return None

    def _load_path(self, path: Path, *, expected_session: str) -> TimelineSnapshot | None:
        try:
            raw = self._read_regular_bytes(path)
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, MediaContractError):
            return None
        if type(value) is not dict or set(value) != {
            "version",
            "session_id",
            "revision",
            "timeline",
            "digest_sha256",
        }:
            return None
        digest = value.get("digest_sha256")
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(ch not in "0123456789abcdef" for ch in digest)
        ):
            return None
        material = {
            "version": value["version"],
            "session_id": value["session_id"],
            "revision": value["revision"],
            "timeline": value["timeline"],
        }
        if _material_digest(material) != digest:
            return None
        try:
            session = _session(value["session_id"])
            rev = _revision(value["revision"])
            timeline = MediaPositionTimeline.from_payload(value["timeline"])
        except (TypeError, ValueError, MediaContractError):
            return None
        if session != expected_session:
            return None
        return TimelineSnapshot(path, session, rev, digest, timeline)

    def _read_regular_bytes(self, path: Path) -> bytes:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise MediaContractError("timeline snapshot must be a regular file")
            if before.st_size < 1 or before.st_size > self.max_snapshot_bytes:
                raise MediaContractError("timeline snapshot byte size is invalid")
            chunks: list[bytes] = []
            remaining = before.st_size
            while remaining:
                chunk = os.read(fd, min(64 * 1024, remaining))
                if not chunk:
                    raise MediaContractError("timeline snapshot ended unexpectedly")
                chunks.append(chunk)
                remaining -= len(chunk)
            after = os.fstat(fd)
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise MediaContractError("timeline snapshot changed while reading")
            return b"".join(chunks)
        finally:
            os.close(fd)
