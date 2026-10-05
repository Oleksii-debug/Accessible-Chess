from __future__ import annotations

"""Checksum-verified durable checkpoints for Agent/Media jobs.

Adapted from first-party donors:
- Oleksii-debug/Nika-Core src/nika_core/kernel/checkpoint.py
- Oleksii-debug/12-6-ai. checkpoint canonical JSON/hash durability patterns

This is intentionally filesystem-only and dependency-free. It does not replace
ACSDB; it gives long-running preprocessing/agent jobs a small recoverable cursor.
"""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


def canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class DurableCheckpoint:
    job_id: str
    stage: str
    payload: Mapping[str, object]
    checksum_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.job_id, str) or not self.job_id.strip():
            raise ValueError("job_id must not be empty")
        if not isinstance(self.stage, str) or not self.stage.strip():
            raise ValueError("stage must not be empty")
        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a mapping")
        if (
            not isinstance(self.checksum_sha256, str)
            or len(self.checksum_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in self.checksum_sha256)
        ):
            raise ValueError("checksum_sha256 must be lowercase SHA-256 hex")


class CheckpointCorruptError(RuntimeError):
    pass


class FileCheckpointStore:
    """Atomic one-checkpoint-per-job store.

    Publication uses fsync + os.replace. Load recomputes canonical payload hash
    and fails closed on unknown schema/fields or checksum mismatch.
    """

    SCHEMA_VERSION = 1

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise ValueError("checkpoint root must be a directory")

    @staticmethod
    def _safe_job_filename(job_id: str) -> str:
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("job_id must not be empty")
        digest = hashlib.sha256(job_id.encode("utf-8")).hexdigest()
        return f"{digest}.checkpoint.json"

    def path_for(self, job_id: str) -> Path:
        return self.root / self._safe_job_filename(job_id)

    def save(
        self,
        *,
        job_id: str,
        stage: str,
        payload: Mapping[str, object],
    ) -> DurableCheckpoint:
        if not isinstance(stage, str) or not stage.strip():
            raise ValueError("stage must not be empty")
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        body_bytes = canonical_json_bytes(payload)
        checksum = hashlib.sha256(body_bytes).hexdigest()
        document = {
            "schema_version": self.SCHEMA_VERSION,
            "job_id": job_id,
            "stage": stage,
            "payload": dict(payload),
            "checksum_sha256": checksum,
        }
        encoded = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        destination = self.path_for(job_id)
        fd, tmp_name = tempfile.mkstemp(prefix=".checkpoint-", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, destination)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return DurableCheckpoint(job_id, stage, dict(payload), checksum)

    def load(self, job_id: str) -> DurableCheckpoint | None:
        path = self.path_for(job_id)
        if not path.exists():
            return None
        try:
            raw = path.read_bytes()
            decoded = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CheckpointCorruptError("checkpoint is unreadable") from exc
        if not isinstance(decoded, dict):
            raise CheckpointCorruptError("checkpoint root must be an object")
        expected = {"schema_version", "job_id", "stage", "payload", "checksum_sha256"}
        if set(decoded) != expected:
            raise CheckpointCorruptError("checkpoint structure is invalid")
        if decoded["schema_version"] != self.SCHEMA_VERSION:
            raise CheckpointCorruptError("checkpoint schema is unsupported")
        if decoded["job_id"] != job_id:
            raise CheckpointCorruptError("checkpoint belongs to another job")
        payload = decoded["payload"]
        if not isinstance(payload, dict):
            raise CheckpointCorruptError("checkpoint payload is invalid")
        checksum = decoded["checksum_sha256"]
        actual = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        if checksum != actual:
            raise CheckpointCorruptError("checkpoint checksum mismatch")
        try:
            return DurableCheckpoint(job_id, decoded["stage"], payload, checksum)
        except (TypeError, ValueError) as exc:
            raise CheckpointCorruptError("checkpoint fields are invalid") from exc

    def delete(self, job_id: str) -> None:
        self.path_for(job_id).unlink(missing_ok=True)


__all__ = [
    "CheckpointCorruptError",
    "DurableCheckpoint",
    "FileCheckpointStore",
    "canonical_json_bytes",
]
