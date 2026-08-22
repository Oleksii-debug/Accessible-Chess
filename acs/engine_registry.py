from __future__ import annotations

"""Presentation-neutral registration point for chess engine providers.

The application selects engines through stable provider IDs. Infrastructure
registers factories at the composition root; core services never import a
Stockfish subprocess adapter or another concrete engine implementation.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterable

from .engine_ports import ChessEnginePort


class EngineCapability(str, Enum):
    ANALYSIS = "analysis"
    MOVE = "move"


@dataclass(frozen=True)
class EngineProviderDescriptor:
    provider_id: str
    title: str
    capabilities: frozenset[EngineCapability]

    def __post_init__(self) -> None:
        provider_id = self.provider_id.strip()
        title = self.title.strip()
        if not provider_id:
            raise ValueError("provider_id must not be empty")
        if provider_id != self.provider_id:
            raise ValueError("provider_id must not contain surrounding whitespace")
        if provider_id.casefold() != provider_id:
            raise ValueError("provider_id must be lowercase and stable")
        if not title:
            raise ValueError("provider title must not be empty")
        if not self.capabilities:
            raise ValueError("provider must declare at least one capability")


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
        if descriptor.provider_id in self._descriptors:
            raise ValueError(f"engine provider already registered: {descriptor.provider_id}")
        if not callable(factory):
            raise TypeError("engine provider factory must be callable")
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
        descriptor = self.descriptor(provider_id)
        if require is not None and require not in descriptor.capabilities:
            raise ValueError(
                f"engine provider {descriptor.provider_id} does not support {require.value}"
            )
        engine = self._factories[descriptor.provider_id]()
        if not isinstance(engine, ChessEnginePort):
            raise TypeError(
                f"engine provider {descriptor.provider_id} factory returned an incompatible adapter"
            )
        return engine

    @staticmethod
    def _normalize_provider_id(provider_id: str) -> str:
        value = provider_id.strip().casefold()
        if not value:
            raise ValueError("provider_id must not be empty")
        return value
