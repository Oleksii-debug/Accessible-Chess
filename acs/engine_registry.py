from __future__ import annotations

"""Presentation-neutral registration point for chess engine providers.

The application selects engines through stable provider IDs. Infrastructure
registers factories at the composition root; core services never import a
Stockfish subprocess adapter or another concrete engine implementation.
"""

from dataclasses import dataclass
from enum import Enum
import re
from typing import Callable, Iterable

from .engine_ports import (
    ChessEnginePort,
    EngineContractError,
    EngineContractErrorCode,
)


_PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


class EngineCapability(str, Enum):
    ANALYSIS = "analysis"
    MOVE = "move"


@dataclass(frozen=True)
class EngineProviderDescriptor:
    provider_id: str
    title: str
    capabilities: frozenset[EngineCapability]

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str):
            raise EngineContractError(
                "provider_id must be text",
                code=EngineContractErrorCode.INVALID_CONFIG,
            )
        if not isinstance(self.title, str):
            raise EngineContractError(
                "provider title must be text",
                code=EngineContractErrorCode.INVALID_CONFIG,
            )
        provider_id = self.provider_id.strip()
        title = self.title.strip()
        if not provider_id:
            raise EngineContractError(
                "provider_id must not be empty",
                code=EngineContractErrorCode.INVALID_CONFIG,
            )
        if provider_id != self.provider_id:
            raise EngineContractError(
                "provider_id must not contain surrounding whitespace",
                code=EngineContractErrorCode.INVALID_CONFIG,
            )
        if _PROVIDER_ID_RE.fullmatch(provider_id) is None:
            raise EngineContractError(
                "provider_id must be a lowercase ASCII slug",
                code=EngineContractErrorCode.INVALID_CONFIG,
            )
        if not title or "\n" in title or "\r" in title:
            raise EngineContractError(
                "provider title must be non-empty single-line text",
                code=EngineContractErrorCode.INVALID_CONFIG,
            )
        if (
            not isinstance(self.capabilities, frozenset)
            or not self.capabilities
            or any(
                not isinstance(capability, EngineCapability)
                for capability in self.capabilities
            )
        ):
            raise EngineContractError(
                "provider capabilities must be a non-empty EngineCapability frozenset",
                code=EngineContractErrorCode.INVALID_CONFIG,
            )
        object.__setattr__(self, "title", title)


EngineFactory = Callable[[], ChessEnginePort]


class EngineProviderRegistry:
    """Small composition-root registry for replaceable engine adapters.

    Registration is intentionally explicit. Factories are kept lazy so merely
    listing available providers cannot spawn a process or allocate engine
    resources.
    """

    def __init__(self) -> None:
        self._descriptors: dict[str, EngineProviderDescriptor] = {}
        self._factories: dict[str, EngineFactory] = {}

    def register(self, descriptor: EngineProviderDescriptor, factory: EngineFactory) -> None:
        if not isinstance(descriptor, EngineProviderDescriptor):
            raise TypeError("descriptor must be EngineProviderDescriptor")
        if descriptor.provider_id in self._descriptors:
            raise ValueError(f"engine provider already registered: {descriptor.provider_id}")
        if not callable(factory):
            raise EngineContractError(
                "engine provider factory must be callable",
                code=EngineContractErrorCode.INVALID_PROVIDER,
            )
        self._descriptors[descriptor.provider_id] = descriptor
        self._factories[descriptor.provider_id] = factory

    def unregister(self, provider_id: str) -> None:
        provider_id = self._normalize_provider_id(provider_id)
        if provider_id not in self._descriptors:
            raise KeyError(f"unknown engine provider: {provider_id}")
        del self._descriptors[provider_id]
        del self._factories[provider_id]

    def descriptor(self, provider_id: str) -> EngineProviderDescriptor:
        provider_id = self._normalize_provider_id(provider_id)
        try:
            return self._descriptors[provider_id]
        except KeyError as exc:
            raise KeyError(f"unknown engine provider: {provider_id}") from exc

    def descriptors(
        self,
        *,
        capability: EngineCapability | None = None,
    ) -> tuple[EngineProviderDescriptor, ...]:
        self._validate_capability(capability, field_name="capability")
        values: Iterable[EngineProviderDescriptor] = self._descriptors.values()
        if capability is not None:
            values = (item for item in values if capability in item.capabilities)
        return tuple(values)

    def provider_ids(self, *, capability: EngineCapability | None = None) -> tuple[str, ...]:
        return tuple(item.provider_id for item in self.descriptors(capability=capability))

    def create(
        self,
        provider_id: str,
        *,
        require: EngineCapability | None = None,
    ) -> ChessEnginePort:
        self._validate_capability(require, field_name="require")
        descriptor = self.descriptor(provider_id)
        if require is not None and require not in descriptor.capabilities:
            raise ValueError(
                f"engine provider {descriptor.provider_id} does not support {require.value}"
            )
        engine = self._factories[descriptor.provider_id]()
        if (
            isinstance(engine, type)
            or not isinstance(engine, ChessEnginePort)
            or not callable(getattr(engine, "analyze", None))
            or not callable(getattr(engine, "best_move", None))
            or not callable(getattr(engine, "close", None))
        ):
            raise EngineContractError(
                f"engine provider {descriptor.provider_id} factory returned an incompatible adapter",
                code=EngineContractErrorCode.INVALID_PROVIDER,
            )
        return engine

    @staticmethod
    def _normalize_provider_id(provider_id: str) -> str:
        if not isinstance(provider_id, str):
            raise EngineContractError(
                "provider_id must be text",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        value = provider_id.strip().casefold()
        if not value or _PROVIDER_ID_RE.fullmatch(value) is None:
            raise EngineContractError(
                "provider_id must be a non-empty lowercase ASCII slug",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
        return value

    @staticmethod
    def _validate_capability(
        capability: EngineCapability | None,
        *,
        field_name: str,
    ) -> None:
        if capability is not None and not isinstance(
            capability,
            EngineCapability,
        ):
            raise EngineContractError(
                f"{field_name} must be EngineCapability or None",
                code=EngineContractErrorCode.INVALID_REQUEST,
            )
