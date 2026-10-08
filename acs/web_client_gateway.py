from __future__ import annotations

"""Authenticated browser boundary for the Accessible Chess Web client.

This module is deliberately domain-neutral. It never parses chess notation,
applies moves, owns Library/Book/Classroom state, or decides game legality.
A deployment binds one canonical application/server service through snapshot
and command callables. Browser identity/workspace data is trusted only when
supplied by authenticated server middleware.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping
import math
import re


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_AREA_RE = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
_COMMAND_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_ALLOWED_AREAS = frozenset(
    {
        "shell", "board", "review", "pgn", "gametree", "library", "books",
        "training", "media", "teacher", "classes", "education", "classroom",
        "online", "spectator", "settings", "help",
    }
)
_MAX_PAYLOAD_KEYS = 64
_MAX_CONTAINER_ITEMS = 512
_MAX_DEPTH = 10
_MAX_TEXT = 16_384


class WebClientContractError(ValueError):
    """A bounded browser/server contract violation."""


@dataclass(frozen=True, slots=True)
class WebPrincipal:
    user_id: str
    workspace_id: str
    session_id: str
    roles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_id", _bounded_id(self.user_id, "user_id"))
        object.__setattr__(
            self, "workspace_id", _bounded_id(self.workspace_id, "workspace_id")
        )
        object.__setattr__(self, "session_id", _bounded_id(self.session_id, "session_id"))
        if type(self.roles) is not tuple or len(self.roles) > 32:
            raise WebClientContractError("roles must be a bounded tuple")
        clean: list[str] = []
        for role in self.roles:
            if type(role) is not str or not _ID_RE.fullmatch(role):
                raise WebClientContractError("invalid role")
            clean.append(role)
        if len(set(clean)) != len(clean):
            raise WebClientContractError("duplicate role")
        object.__setattr__(self, "roles", tuple(clean))

    def public_context(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "user_id": self.user_id,
                "workspace_id": self.workspace_id,
                "roles": self.roles,
            }
        )


def _bounded_id(value: object, field: str) -> str:
    if type(value) is not str or not _ID_RE.fullmatch(value):
        raise WebClientContractError(f"invalid {field}")
    return value


def _validate_json_value(value: object, *, depth: int = 0) -> object:
    if depth > _MAX_DEPTH:
        raise WebClientContractError("payload is too deeply nested")
    if value is None or type(value) in {bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise WebClientContractError("non-finite number")
        return value
    if type(value) is str:
        if len(value) > _MAX_TEXT or "\x00" in value:
            raise WebClientContractError("invalid text value")
        return value
    if type(value) is list:
        if len(value) > _MAX_CONTAINER_ITEMS:
            raise WebClientContractError("too many list items")
        return [_validate_json_value(item, depth=depth + 1) for item in value]
    if type(value) is tuple:
        if len(value) > _MAX_CONTAINER_ITEMS:
            raise WebClientContractError("too many tuple items")
        return [_validate_json_value(item, depth=depth + 1) for item in value]
    if type(value) is dict:
        if len(value) > _MAX_PAYLOAD_KEYS:
            raise WebClientContractError("too many object fields")
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str or not key or len(key) > 96 or "\x00" in key:
                raise WebClientContractError("invalid object field")
            result[key] = _validate_json_value(item, depth=depth + 1)
        return result
    raise WebClientContractError("unsupported JSON value")


class CanonicalWebGateway:
    """One browser gateway over canonical application/server services.

    The injected callables may marshal work onto the native application owner
    thread, call cloud services, or route to provider-neutral Media/Classroom/
    Online services. This gateway validates only the untrusted browser envelope
    and authenticated context.
    """

    def __init__(
        self,
        *,
        snapshot: Callable[[WebPrincipal], Mapping[str, object]],
        command: Callable[
            [WebPrincipal, str, str, Mapping[str, object]], Mapping[str, object]
        ],
    ) -> None:
        if not callable(snapshot) or not callable(command):
            raise TypeError("snapshot and command must be callable")
        self._snapshot = snapshot
        self._command = command

    @staticmethod
    def _area(value: object) -> str:
        if type(value) is not str or not _AREA_RE.fullmatch(value):
            raise WebClientContractError("invalid area")
        if value not in _ALLOWED_AREAS:
            raise WebClientContractError("unsupported area")
        return value

    @staticmethod
    def _command_id(value: object) -> str:
        if type(value) is not str or not _COMMAND_RE.fullmatch(value):
            raise WebClientContractError("invalid command")
        return value

    def snapshot(self, principal: WebPrincipal) -> dict[str, object]:
        if type(principal) is not WebPrincipal:
            raise TypeError("authenticated WebPrincipal is required")
        value = self._snapshot(principal)
        if not isinstance(value, Mapping):
            raise WebClientContractError("canonical snapshot must be a mapping")
        safe = _validate_json_value(dict(value))
        if type(safe) is not dict:
            raise WebClientContractError("canonical snapshot is invalid")
        return {
            "ok": True,
            "context": dict(principal.public_context()),
            "snapshot": safe,
        }

    def command(
        self,
        principal: WebPrincipal,
        *,
        area: object,
        command: object,
        payload: object = None,
    ) -> dict[str, object]:
        if type(principal) is not WebPrincipal:
            raise TypeError("authenticated WebPrincipal is required")
        clean_area = self._area(area)
        clean_command = self._command_id(command)
        if payload is None:
            clean_payload: dict[str, object] = {}
        elif type(payload) is dict:
            validated = _validate_json_value(payload)
            if type(validated) is not dict:
                raise WebClientContractError("invalid command payload")
            clean_payload = validated
        else:
            raise WebClientContractError("command payload must be an object")

        value = self._command(principal, clean_area, clean_command, clean_payload)
        if not isinstance(value, Mapping):
            raise WebClientContractError("canonical command result must be a mapping")
        safe = _validate_json_value(dict(value))
        if type(safe) is not dict:
            raise WebClientContractError("canonical command result is invalid")
        return {
            "ok": True,
            "context": dict(principal.public_context()),
            "result": safe,
        }
