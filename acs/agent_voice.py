from __future__ import annotations

"""Replaceable speech adapters for bounded Agent voice conversation.

Audio is transient input/output owned by the caller.  This module persists no
recording, credential, transcript or provider secret and owns no chess state.
"""

from dataclasses import dataclass
from typing import Protocol

from .agent_resource_budget import AgentResourceUsage
from .agent_reliability import ReliableAgentSession


_MAX_AUDIO_BYTES = 16 * 1024 * 1024
_MAX_TRANSCRIPT_CHARS = 16_000
_MAX_SPOKEN_TEXT_CHARS = 32_000


class SpeechInputAdapter(Protocol):
    async def transcribe(self, audio: bytes, *, language: str | None) -> str: ...


class SpeechOutputAdapter(Protocol):
    async def synthesize(self, text: str, *, language: str | None) -> bytes: ...


@dataclass(frozen=True, slots=True)
class VoicePermissionState:
    input_allowed: bool
    model_allowed: bool
    output_allowed: bool

    def __post_init__(self) -> None:
        for name in ("input_allowed", "model_allowed", "output_allowed"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be boolean")


class VoicePermissionProvider(Protocol):
    def __call__(self) -> VoicePermissionState: ...


@dataclass(frozen=True, slots=True)
class VoiceConversationResult:
    transcript: str
    text: str
    audio: bytes | None
    output_suppressed: bool


class VoiceConversationError(RuntimeError):
    pass


def _language(value: str | None) -> str | None:
    if value is None:
        return None
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > 35
        or any(not (ch.isalnum() or ch in "-_") for ch in value)
    ):
        raise ValueError("language must be a bounded language tag or None")
    return value


class AgentVoiceConversation:
    """One speech -> Universal Agent -> speech turn with live permission checks."""

    def __init__(
        self,
        *,
        session: ReliableAgentSession,
        speech_input: SpeechInputAdapter,
        speech_output: SpeechOutputAdapter,
        permission_provider: VoicePermissionProvider,
    ) -> None:
        if type(session) is not ReliableAgentSession:
            raise TypeError("session must be ReliableAgentSession")
        if not callable(getattr(speech_input, "transcribe", None)):
            raise TypeError("speech_input must implement transcribe")
        if not callable(getattr(speech_output, "synthesize", None)):
            raise TypeError("speech_output must implement synthesize")
        if not callable(permission_provider):
            raise TypeError("permission_provider must be callable")
        self.session = session
        self.speech_input = speech_input
        self.speech_output = speech_output
        self.permission_provider = permission_provider

    def _permissions(self) -> VoicePermissionState:
        value = self.permission_provider()
        if type(value) is not VoicePermissionState:
            raise VoiceConversationError(
                "voice permission provider returned an invalid state"
            )
        return value

    async def converse(
        self,
        *,
        run_id: str,
        audio: bytes,
        language: str | None = None,
        current_usage: AgentResourceUsage,
        requested_usage: AgentResourceUsage,
    ) -> VoiceConversationResult:
        if type(audio) is not bytes or not 1 <= len(audio) <= _MAX_AUDIO_BYTES:
            raise ValueError("audio must be bounded non-empty bytes")
        language = _language(language)

        permissions = self._permissions()
        if not permissions.input_allowed:
            raise VoiceConversationError("voice input permission denied")

        transcript = await self.speech_input.transcribe(
            bytes(audio),
            language=language,
        )
        if (
            type(transcript) is not str
            or not transcript.strip()
            or len(transcript) > _MAX_TRANSCRIPT_CHARS
            or "\x00" in transcript
        ):
            raise VoiceConversationError("speech transcript is outside supported bounds")
        transcript = transcript.strip()

        permissions = self._permissions()
        if not permissions.model_allowed:
            raise VoiceConversationError("voice model permission denied")

        result = await self.session.run(
            run_id=run_id,
            user_text=transcript,
            current_usage=current_usage,
            requested_usage=requested_usage,
        )
        if len(result.text) > _MAX_SPOKEN_TEXT_CHARS:
            raise VoiceConversationError("agent voice response is outside supported bounds")

        permissions = self._permissions()
        if not permissions.output_allowed:
            return VoiceConversationResult(
                transcript=transcript,
                text=result.text,
                audio=None,
                output_suppressed=True,
            )

        spoken = await self.speech_output.synthesize(
            result.text,
            language=language,
        )
        if type(spoken) is not bytes or not 1 <= len(spoken) <= _MAX_AUDIO_BYTES:
            raise VoiceConversationError("speech output is outside supported bounds")
        return VoiceConversationResult(
            transcript=transcript,
            text=result.text,
            audio=bytes(spoken),
            output_suppressed=False,
        )

    async def cancel(self, run_id: str) -> bool:
        return await self.session.cancel(run_id)


__all__ = [
    "AgentVoiceConversation",
    "SpeechInputAdapter",
    "SpeechOutputAdapter",
    "VoiceConversationError",
    "VoiceConversationResult",
    "VoicePermissionProvider",
    "VoicePermissionState",
]
