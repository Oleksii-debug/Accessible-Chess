from __future__ import annotations

"""Data-only agent checkpoint and rewind assessment.

Adapted from Oleksii-debug/ChatGPT-Autopilot-ExtensionChatGPT-Autopilot-Extension
@fc62b45985654930dfa0e474b01e5e3a03bbfdf4
src/core/agent-checkpoint.js (blob a0373e755d5d698a635df5fc7f6e26924cb7319c).

A checkpoint can rewind only internal agent state. It never authorizes replay or
rollback of external effects and always requires fresh policy/reconciliation.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Mapping


_CHECKPOINT_VERSION = 1
_MAX_EVIDENCE_IDS = 128
_MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024


class CheckpointError(ValueError):
    pass


class RewindStatus(StrEnum):
    READY_FOR_RECONCILIATION = "READY_FOR_RECONCILIATION"
    BLOCKED = "BLOCKED"
    NOOP = "NOOP"


def _id(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise CheckpointError(f"{name} must be non-empty canonical text")
    if len(value) > 180 or any(not ch.isprintable() for ch in value):
        raise CheckpointError(f"{name} is invalid")
    return value


def _positive(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise CheckpointError(f"{name} must be a positive integer")
    return value


def _non_negative(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise CheckpointError(f"{name} must be a non-negative integer")
    return value


def _utc(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CheckpointError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _sha256(value: object, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise CheckpointError(f"{name} must be lowercase SHA-256")
    return value


def _evidence_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise CheckpointError("evidence_ids must be a list/tuple")
    if len(value) > _MAX_EVIDENCE_IDS:
        raise CheckpointError("evidence_ids exceed bound")
    result = tuple(_id(item, "evidence_id") for item in value)
    if len(set(result)) != len(result):
        raise CheckpointError("evidence_ids contain duplicates")
    return result


@dataclass(frozen=True, slots=True)
class AgentCheckpoint:
    checkpoint_id: str
    agent_id: str
    run_id: str
    plan_revision: int
    internal_state_revision: int
    effect_ledger_revision: int
    policy_revision_id: str
    snapshot_sha256: str
    snapshot_size_bytes: int
    evidence_ids: tuple[str, ...]
    created_at: datetime
    checkpoint_digest: str

    def __post_init__(self) -> None:
        for name in ("checkpoint_id", "agent_id", "run_id", "policy_revision_id"):
            _id(getattr(self, name), name)
        _positive(self.plan_revision, "plan_revision")
        _positive(self.internal_state_revision, "internal_state_revision")
        _non_negative(self.effect_ledger_revision, "effect_ledger_revision")
        _sha256(self.snapshot_sha256, "snapshot_sha256")
        if (
            type(self.snapshot_size_bytes) is not int
            or not 1 <= self.snapshot_size_bytes <= _MAX_SNAPSHOT_BYTES
        ):
            raise CheckpointError("snapshot_size_bytes is outside allowed bound")
        object.__setattr__(self, "evidence_ids", _evidence_ids(self.evidence_ids))
        object.__setattr__(self, "created_at", _utc(self.created_at, "created_at"))
        _sha256(self.checkpoint_digest, "checkpoint_digest")


@dataclass(frozen=True, slots=True)
class AgentCheckpointHead:
    agent_id: str
    run_id: str
    plan_revision: int
    internal_state_revision: int
    effect_ledger_revision: int
    policy_revision_id: str
    unresolved_effect_ids: tuple[str, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        for name in ("agent_id", "run_id", "policy_revision_id"):
            _id(getattr(self, name), name)
        _positive(self.plan_revision, "plan_revision")
        _positive(self.internal_state_revision, "internal_state_revision")
        _non_negative(self.effect_ledger_revision, "effect_ledger_revision")
        object.__setattr__(self, "unresolved_effect_ids", _evidence_ids(self.unresolved_effect_ids))
        object.__setattr__(self, "observed_at", _utc(self.observed_at, "observed_at"))


@dataclass(frozen=True, slots=True)
class RewindAssessment:
    status: RewindStatus
    reason_code: str
    checkpoint_id: str
    restore_authorized: bool
    requires_fresh_policy_evaluation: bool
    requires_fresh_reconciliation: bool
    preserve_effect_ledger_revision: int
    preserve_policy_revision_id: str
    target_plan_revision: int | None = None
    target_internal_state_revision: int | None = None


def _material(
    *,
    checkpoint_id: str,
    agent_id: str,
    run_id: str,
    plan_revision: int,
    internal_state_revision: int,
    effect_ledger_revision: int,
    policy_revision_id: str,
    snapshot_sha256: str,
    snapshot_size_bytes: int,
    evidence_ids: tuple[str, ...],
    created_at: datetime,
) -> dict[str, object]:
    return {
        "version": _CHECKPOINT_VERSION,
        "checkpoint_id": _id(checkpoint_id, "checkpoint_id"),
        "agent_id": _id(agent_id, "agent_id"),
        "run_id": _id(run_id, "run_id"),
        "plan_revision": _positive(plan_revision, "plan_revision"),
        "internal_state_revision": _positive(internal_state_revision, "internal_state_revision"),
        "effect_ledger_revision": _non_negative(effect_ledger_revision, "effect_ledger_revision"),
        "policy_revision_id": _id(policy_revision_id, "policy_revision_id"),
        "snapshot_sha256": _sha256(snapshot_sha256, "snapshot_sha256"),
        "snapshot_size_bytes": snapshot_size_bytes,
        "evidence_ids": list(_evidence_ids(evidence_ids)),
        "created_at": _utc(created_at, "created_at").isoformat().replace("+00:00", "Z"),
    }


def _digest_material(material: Mapping[str, object]) -> str:
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_checkpoint(
    *,
    checkpoint_id: str,
    agent_id: str,
    run_id: str,
    plan_revision: int,
    internal_state_revision: int,
    effect_ledger_revision: int,
    policy_revision_id: str,
    snapshot_utf8: str,
    evidence_ids: tuple[str, ...] = (),
    created_at: datetime,
) -> AgentCheckpoint:
    if type(snapshot_utf8) is not str:
        raise CheckpointError("snapshot_utf8 must be text")
    snapshot = snapshot_utf8.encode("utf-8")
    if not 1 <= len(snapshot) <= _MAX_SNAPSHOT_BYTES:
        raise CheckpointError("snapshot_utf8 is outside allowed byte bound")
    snapshot_sha = hashlib.sha256(snapshot).hexdigest()
    material = _material(
        checkpoint_id=checkpoint_id,
        agent_id=agent_id,
        run_id=run_id,
        plan_revision=plan_revision,
        internal_state_revision=internal_state_revision,
        effect_ledger_revision=effect_ledger_revision,
        policy_revision_id=policy_revision_id,
        snapshot_sha256=snapshot_sha,
        snapshot_size_bytes=len(snapshot),
        evidence_ids=evidence_ids,
        created_at=created_at,
    )
    return AgentCheckpoint(
        checkpoint_id=checkpoint_id,
        agent_id=agent_id,
        run_id=run_id,
        plan_revision=plan_revision,
        internal_state_revision=internal_state_revision,
        effect_ledger_revision=effect_ledger_revision,
        policy_revision_id=policy_revision_id,
        snapshot_sha256=snapshot_sha,
        snapshot_size_bytes=len(snapshot),
        evidence_ids=evidence_ids,
        created_at=created_at,
        checkpoint_digest=_digest_material(material),
    )


def verify_checkpoint(checkpoint: AgentCheckpoint, snapshot_utf8: str) -> None:
    if type(checkpoint) is not AgentCheckpoint:
        raise TypeError("checkpoint must be AgentCheckpoint")
    if type(snapshot_utf8) is not str:
        raise CheckpointError("snapshot_utf8 must be text")
    snapshot = snapshot_utf8.encode("utf-8")
    if len(snapshot) != checkpoint.snapshot_size_bytes:
        raise CheckpointError("snapshot size does not match checkpoint")
    if hashlib.sha256(snapshot).hexdigest() != checkpoint.snapshot_sha256:
        raise CheckpointError("snapshot digest does not match checkpoint")
    material = _material(
        checkpoint_id=checkpoint.checkpoint_id,
        agent_id=checkpoint.agent_id,
        run_id=checkpoint.run_id,
        plan_revision=checkpoint.plan_revision,
        internal_state_revision=checkpoint.internal_state_revision,
        effect_ledger_revision=checkpoint.effect_ledger_revision,
        policy_revision_id=checkpoint.policy_revision_id,
        snapshot_sha256=checkpoint.snapshot_sha256,
        snapshot_size_bytes=checkpoint.snapshot_size_bytes,
        evidence_ids=checkpoint.evidence_ids,
        created_at=checkpoint.created_at,
    )
    if _digest_material(material) != checkpoint.checkpoint_digest:
        raise CheckpointError("checkpoint material digest mismatch")


def assess_rewind(
    *,
    checkpoint: AgentCheckpoint,
    current: AgentCheckpointHead,
    snapshot_utf8: str,
) -> RewindAssessment:
    verify_checkpoint(checkpoint, snapshot_utf8)
    if current.agent_id != checkpoint.agent_id or current.run_id != checkpoint.run_id:
        raise CheckpointError("current agent/run identity does not match checkpoint")
    if current.plan_revision < checkpoint.plan_revision:
        raise CheckpointError("current plan revision regressed behind checkpoint")
    if current.internal_state_revision < checkpoint.internal_state_revision:
        raise CheckpointError("current internal state regressed behind checkpoint")
    if current.effect_ledger_revision < checkpoint.effect_ledger_revision:
        raise CheckpointError("current effect ledger regressed behind checkpoint")
    if current.observed_at < checkpoint.created_at:
        raise CheckpointError("current observation predates checkpoint")

    common = dict(
        checkpoint_id=checkpoint.checkpoint_id,
        restore_authorized=False,
        requires_fresh_policy_evaluation=True,
        requires_fresh_reconciliation=True,
        preserve_effect_ledger_revision=current.effect_ledger_revision,
        preserve_policy_revision_id=current.policy_revision_id,
    )
    if current.unresolved_effect_ids:
        return RewindAssessment(
            status=RewindStatus.BLOCKED,
            reason_code="UNRESOLVED_EXTERNAL_EFFECTS",
            **common,
        )
    if current.effect_ledger_revision != checkpoint.effect_ledger_revision:
        return RewindAssessment(
            status=RewindStatus.BLOCKED,
            reason_code="EXTERNAL_EFFECTS_AFTER_CHECKPOINT",
            **common,
        )
    if (
        current.plan_revision == checkpoint.plan_revision
        and current.internal_state_revision == checkpoint.internal_state_revision
    ):
        return RewindAssessment(
            status=RewindStatus.NOOP,
            reason_code="ALREADY_AT_CHECKPOINT",
            **common,
        )
    return RewindAssessment(
        status=RewindStatus.READY_FOR_RECONCILIATION,
        reason_code="INTERNAL_STATE_ONLY_REWIND",
        target_plan_revision=checkpoint.plan_revision,
        target_internal_state_revision=checkpoint.internal_state_revision,
        **common,
    )
