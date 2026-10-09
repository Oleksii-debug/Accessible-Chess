"""Provider-neutral, secret-safe AI gateway for the Accessible Chess agent.

The gateway deliberately keeps provider credentials outside source/config files.
Profiles are editable at runtime, while API keys are resolved only from the
named environment variable when a request is sent. Responses are normalized so
the chess application never depends on one vendor's JSON shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import time
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class AIProviderError(RuntimeError):
    """Safe user-facing gateway failure; never contains a credential."""

    def __init__(self, message: str, *, code: str = "provider-error", retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    base_url: str
    model: str
    api_key_env: str
    protocol: str = "openai-chat"
    enabled: bool = True
    timeout_seconds: float = 30.0

    def public_dict(self) -> dict[str, Any]:
        """Return editor-safe metadata; the secret value is never returned."""
        return {
            "name": self.name,
            "base_url": self.base_url,
            "model": self.model,
            "api_key_env": self.api_key_env,
            "protocol": self.protocol,
            "enabled": self.enabled,
            "timeout_seconds": self.timeout_seconds,
            "configured": bool(os.getenv(self.api_key_env)),
        }


@dataclass(frozen=True)
class ProviderRequest:
    messages: tuple[Mapping[str, str], ...]
    temperature: float = 0.2
    max_tokens: int = 512
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def payload(self, model: str) -> dict[str, Any]:
        return {
            "model": model,
            "messages": [dict(message) for message in self.messages],
            "temperature": max(0.0, min(2.0, float(self.temperature))),
            "max_tokens": max(1, min(8192, int(self.max_tokens))),
        }


@dataclass(frozen=True)
class ProviderResponse:
    provider: str
    model: str
    text: str
    raw: Mapping[str, Any]
    usage: Mapping[str, Any] = field(default_factory=dict)


def default_profiles() -> dict[str, ProviderProfile]:
    """Built-in editable profiles; no credential values are embedded."""
    return {
        "mistral": ProviderProfile(
            name="mistral",
            base_url=os.getenv("ACS_MISTRAL_BASE_URL", "https://api.mistral.ai/v1"),
            model=os.getenv("ACS_MISTRAL_MODEL", "ministral-3b-latest"),
            api_key_env="ACS_MISTRAL_API_KEY",
        ),
        "openai-compatible": ProviderProfile(
            name="openai-compatible",
            base_url=os.getenv("ACS_OPENAI_COMPATIBLE_BASE_URL", ""),
            model=os.getenv("ACS_OPENAI_COMPATIBLE_MODEL", ""),
            api_key_env="ACS_OPENAI_COMPATIBLE_API_KEY",
            enabled=bool(os.getenv("ACS_OPENAI_COMPATIBLE_BASE_URL")),
        ),
    }


class AIProviderGateway:
    def __init__(
        self,
        profiles: Mapping[str, ProviderProfile] | None = None,
        *,
        opener: Callable[..., Any] = urlopen,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._profiles = dict(profiles or default_profiles())
        self._opener = opener
        self._sleep = sleep

    def profiles_for_editor(self) -> list[dict[str, Any]]:
        return [profile.public_dict() for profile in self._profiles.values()]

    def upsert_profile(self, profile: ProviderProfile) -> None:
        parsed = urlparse(profile.base_url)
        if not profile.name.strip() or parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Provider endpoint must be an HTTPS URL")
        if not profile.api_key_env or not profile.api_key_env.replace("_", "").isalnum() or not profile.api_key_env[0].isalpha():
            raise ValueError("Profile name and environment key are required")
        self._profiles[profile.name] = profile

    def complete(self, profile_name: str, request: ProviderRequest) -> ProviderResponse:
        profile = self._profiles.get(profile_name)
        if not profile or not profile.enabled:
            raise AIProviderError("AI provider is not enabled", code="provider-disabled")
        if profile.protocol != "openai-chat":
            raise AIProviderError("Unsupported AI provider protocol", code="protocol-unsupported")
        api_key = os.getenv(profile.api_key_env)
        if not api_key:
            raise AIProviderError("AI provider credentials are not configured", code="credentials-missing")
        endpoint = profile.base_url.rstrip("/") + "/chat/completions"
        body = json.dumps(request.payload(profile.model), ensure_ascii=False).encode("utf-8")
        req = Request(endpoint, data=body, method="POST", headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Accessible-Chess/ai-gateway",
        })
        last_error: AIProviderError | None = None
        for attempt in range(3):
            try:
                with self._opener(req, timeout=profile.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                return self._normalize(profile, payload)
            except HTTPError as error:
                retryable = error.code == 429 or 500 <= error.code < 600
                last_error = AIProviderError(
                    "AI provider request failed",
                    code="http-%s" % error.code,
                    retryable=retryable,
                )
            except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
                last_error = AIProviderError("AI provider network response was invalid", code="network-error", retryable=True)
            if last_error and last_error.retryable and attempt < 2:
                self._sleep(0.2 * (2**attempt))
                continue
            break
        raise last_error or AIProviderError("AI provider request failed")

    @staticmethod
    def _normalize(profile: ProviderProfile, payload: Mapping[str, Any]) -> ProviderResponse:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AIProviderError("AI provider returned no completion", code="empty-response")
        message = choices[0].get("message", {}) if isinstance(choices[0], Mapping) else {}
        text = message.get("content", "") if isinstance(message, Mapping) else ""
        if not isinstance(text, str):
            text = str(text)
        return ProviderResponse(
            provider=profile.name,
            model=profile.model,
            text=text,
            raw=payload,
            usage=payload.get("usage", {}) if isinstance(payload.get("usage", {}), Mapping) else {},
        )


__all__ = [
    "AIProviderError",
    "AIProviderGateway",
    "ProviderProfile",
    "ProviderRequest",
    "ProviderResponse",
    "default_profiles",
]
