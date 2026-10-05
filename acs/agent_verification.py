from __future__ import annotations

"""Strict observation/verification contracts for the Universal Chess Agent.

Adapted from first-party donor:
Oleksii-debug/ChatGPT-Autopilot-ExtensionChatGPT-Autopilot-Extension@main
src/core/universal-agent-contracts.js
blob 5fbf0b87a7f6696034d4159b553d27c2a1425a3b

The purpose is to keep "the model/tool observed X" distinct from
"Accessible Chess verified X". Verification does not override canonical chess
truth; board legality/state remains owned by Accessible Chess services.
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+~-]{0,179}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _id(value: str, label: str) -> str:
    if not isinstance(value, str) or value != value.strip() or _ID_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a canonical ID")
    return value


class AgentObservationStatus(StrEnum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    ERROR = "ERROR"
    UNAVAILABLE = "UNAVAILABLE"


class AgentVerificationStatus(StrEnum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class AgentArtifactRef:
    artifact_id: str
    kind: str
    uri: str
    sha256: str = ""
    size_bytes: int = 0
    sensitive: bool = False

    def __post_init__(self) -> None:
        _id(self.artifact_id, "artifact_id")
        _id(self.kind, "kind")
        if not isinstance(self.uri, str) or not self.uri.strip() or len(self.uri) > 4096:
            raise ValueError("uri must be bounded non-empty text")
        if self.sha256 and _SHA256_RE.fullmatch(self.sha256) is None:
            raise ValueError("sha256 must be lowercase SHA-256 hex")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise ValueError("size_bytes must be a non-negative integer")
        if type(self.sensitive) is not bool:
            raise TypeError("sensitive must be boolean")


@dataclass(frozen=True, slots=True)
class AgentObservation:
    observation_id: str
    invocation_id: str
    status: AgentObservationStatus
    summary: str = ""
    data: Mapping[str, object] = field(default_factory=dict)
    artifacts: tuple[AgentArtifactRef, ...] = ()

    def __post_init__(self) -> None:
        _id(self.observation_id, "observation_id")
        _id(self.invocation_id, "invocation_id")
        if not isinstance(self.status, AgentObservationStatus):
            raise TypeError("status must be AgentObservationStatus")
        if not isinstance(self.summary, str) or len(self.summary) > 8000:
            raise ValueError("summary must be bounded text")
        if not isinstance(self.data, Mapping):
            raise TypeError("data must be a mapping")
        if len(self.artifacts) > 128 or any(
            type(item) is not AgentArtifactRef for item in self.artifacts
        ):
            raise ValueError("artifacts must contain at most 128 AgentArtifactRef values")


@dataclass(frozen=True, slots=True)
class AgentVerification:
    verification_id: str
    invocation_id: str
    observation_id: str | None
    status: AgentVerificationStatus
    reason_code: str
    summary: str = ""
    evidence_artifact_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _id(self.verification_id, "verification_id")
        _id(self.invocation_id, "invocation_id")
        if self.observation_id is not None:
            _id(self.observation_id, "observation_id")
        if not isinstance(self.status, AgentVerificationStatus):
            raise TypeError("status must be AgentVerificationStatus")
        if self.status is not AgentVerificationStatus.NOT_APPLICABLE and self.observation_id is None:
            raise ValueError("verification requires observation_id")
        _id(self.reason_code, "reason_code")
        if not isinstance(self.summary, str) or len(self.summary) > 8000:
            raise ValueError("summary must be bounded text")
        if len(self.evidence_artifact_ids) > 128:
            raise ValueError("too many evidence artifacts")
        normalized = tuple(
            _id(value, f"evidence_artifact_ids[{index}]")
            for index, value in enumerate(self.evidence_artifact_ids)
        )
        if len(set(normalized)) != len(normalized):
            raise ValueError("evidence_artifact_ids contains duplicates")
        object.__setattr__(self, "evidence_artifact_ids", normalized)


__all__ = [
    "AgentArtifactRef",
    "AgentObservation",
    "AgentObservationStatus",
    "AgentVerification",
    "AgentVerificationStatus",
]
