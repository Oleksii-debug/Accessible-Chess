from __future__ import annotations

"""Durable storage for preprocessed media-position timelines.

Recovery pattern adapted from first-party donor:
Oleksii-debug/scripture-archive
qa-current-package-accessibility-0913-sol
runtime_engine/scripture_archive_runtime/persistence.py
blob 31e9ce5db8f34272667d0079abc315910e78268e

The schema is Accessible Chess-owned and stores only media timeline identities,
not arbitrary Scripture Archive state.
"""

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from .media_core import MediaPositionTimeline, ReconciliationStatus, TimelineEntry


class MediaTimelineStoreError(RuntimeError):
    pass


class MediaTimelineStore:
    SCHEMA = "accessible_chess.media_timeline"
    VERSION = 1
    MAX_BYTES = 16 * 1024 * 1024

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise MediaTimelineStoreError("timeline root must be a directory")

    @staticmethod
    def _key(session_id: str) -> str:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must not be empty")
        return hashlib.sha256(session_id.encode("utf-8")).hexdigest()

    def _paths(self, session_id: str) -> tuple[Path, Path]:
        key = self._key(session_id)
        return (
            self.root / f"{key}.timeline.json",
            self.root / f"{key}.timeline.json.bak",
        )

    @staticmethod
    def _entry_payload(entry: TimelineEntry) -> dict[str, object]:
        return {
            "start_ms": entry.start_ms,
            "end_ms": entry.end_ms,
            "segment_id": entry.segment_id,
            "gametree_node_id": entry.gametree_node_id,
            "position_id": entry.position_id,
            "qualification": entry.qualification.value,
        }

    def _document(
        self,
        session_id: str,
        timeline: MediaPositionTimeline,
    ) -> dict[str, object]:
        return {
            "schema": self.SCHEMA,
            "version": self.VERSION,
            "session_id": session_id,
            "entries": [self._entry_payload(entry) for entry in timeline.entries],
        }

    @classmethod
    def _encode(cls, document: dict[str, object]) -> bytes:
        try:
            payload = (
                json.dumps(
                    document,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError) as exc:
            raise MediaTimelineStoreError("timeline is not canonical JSON") from exc
        if len(payload) > cls.MAX_BYTES:
            raise MediaTimelineStoreError("timeline exceeds size limit")
        return payload

    def save(self, session_id: str, timeline: MediaPositionTimeline) -> Path:
        if not isinstance(timeline, MediaPositionTimeline):
            raise TypeError("timeline must be MediaPositionTimeline")
        target, backup = self._paths(session_id)
        payload = self._encode(self._document(session_id, timeline))

        if target.exists():
            try:
                self._decode(target.read_bytes(), expected_session_id=session_id)
            except (OSError, MediaTimelineStoreError):
                pass
            else:
                shutil.copy2(target, backup)

        fd, tmp_name = tempfile.mkstemp(
            prefix=".timeline-",
            suffix=".tmp",
            dir=self.root,
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
            self._fsync_directory()
        finally:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
        return target

    def load(self, session_id: str) -> MediaPositionTimeline | None:
        target, backup = self._paths(session_id)
        if not target.exists():
            return None
        try:
            return self._decode(target.read_bytes(), expected_session_id=session_id)
        except (OSError, MediaTimelineStoreError):
            self._quarantine(target)
            if not backup.exists():
                return None
            try:
                recovered = self._decode(
                    backup.read_bytes(),
                    expected_session_id=session_id,
                )
            except (OSError, MediaTimelineStoreError):
                return None
            self.save(session_id, recovered)
            return recovered

    def delete(self, session_id: str) -> None:
        target, backup = self._paths(session_id)
        target.unlink(missing_ok=True)
        backup.unlink(missing_ok=True)

    def _decode(
        self,
        payload: bytes,
        *,
        expected_session_id: str,
    ) -> MediaPositionTimeline:
        if len(payload) > self.MAX_BYTES:
            raise MediaTimelineStoreError("timeline exceeds size limit")
        try:
            raw = json.loads(
                payload.decode("utf-8"),
                object_pairs_hook=self._reject_duplicate_keys,
                parse_constant=self._reject_nonfinite,
            )
        except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise MediaTimelineStoreError("timeline is invalid JSON") from exc
        if type(raw) is not dict:
            raise MediaTimelineStoreError("timeline root must be an object")
        if set(raw) != {"schema", "version", "session_id", "entries"}:
            raise MediaTimelineStoreError("timeline has unexpected fields")
        if raw["schema"] != self.SCHEMA or raw["version"] != self.VERSION:
            raise MediaTimelineStoreError("unsupported timeline schema")
        if raw["session_id"] != expected_session_id:
            raise MediaTimelineStoreError("timeline session identity mismatch")
        entries_raw = raw["entries"]
        if type(entries_raw) is not list:
            raise MediaTimelineStoreError("timeline entries must be a list")

        entries: list[TimelineEntry] = []
        for item in entries_raw:
            if type(item) is not dict or set(item) != {
                "start_ms",
                "end_ms",
                "segment_id",
                "gametree_node_id",
                "position_id",
                "qualification",
            }:
                raise MediaTimelineStoreError("timeline entry is invalid")
            try:
                qualification = ReconciliationStatus(item["qualification"])
                entry = TimelineEntry(
                    start_ms=item["start_ms"],
                    end_ms=item["end_ms"],
                    segment_id=item["segment_id"],
                    gametree_node_id=item["gametree_node_id"],
                    position_id=item["position_id"],
                    qualification=qualification,
                )
            except (TypeError, ValueError) as exc:
                raise MediaTimelineStoreError("timeline entry is invalid") from exc
            entries.append(entry)
        try:
            return MediaPositionTimeline(tuple(entries))
        except (TypeError, ValueError) as exc:
            raise MediaTimelineStoreError("timeline topology is invalid") from exc

    @staticmethod
    def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    @staticmethod
    def _reject_nonfinite(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    def _quarantine(self, target: Path) -> None:
        if not target.exists():
            return
        digest = hashlib.sha256(target.read_bytes()).hexdigest()[:16]
        quarantine = self.root / f"{target.stem}.corrupt.{digest}.json"
        try:
            os.replace(target, quarantine)
        except OSError:
            pass

    def _fsync_directory(self) -> None:
        flags = getattr(os, "O_DIRECTORY", 0)
        try:
            fd = os.open(str(self.root), os.O_RDONLY | flags)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)


__all__ = ["MediaTimelineStore", "MediaTimelineStoreError"]
