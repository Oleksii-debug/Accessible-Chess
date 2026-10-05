from __future__ import annotations

"""Per-identity async serialization primitive.

Adapted from the first-party Nika-agent runtime pattern:
Oleksii-debug/Nika-agent dev/runtime-consolidated-candidate
src/runtime.ts blob 5f990821549f20d174a153ba3e2435544eb65099

Nika-agent serializes one browser agent's operations. Accessible Chess uses the
same pattern for one agent thread/media session so concurrent control operations
cannot race each other while unrelated identities remain concurrent.
"""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class KeyedAsyncLock:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._users: dict[str, int] = {}
        self._registry_lock = asyncio.Lock()

    async def run(self, key: str, operation: Callable[[], Awaitable[T]]) -> T:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("key must not be empty")

        async with self._registry_lock:
            lock = self._locks[key]
            self._users[key] = self._users.get(key, 0) + 1

        try:
            async with lock:
                return await operation()
        finally:
            async with self._registry_lock:
                remaining = self._users.get(key, 1) - 1
                if remaining <= 0 and not lock.locked():
                    self._users.pop(key, None)
                    self._locks.pop(key, None)
                else:
                    self._users[key] = remaining

    async def active_keys(self) -> tuple[str, ...]:
        async with self._registry_lock:
            return tuple(sorted(self._users))


__all__ = ["KeyedAsyncLock"]
