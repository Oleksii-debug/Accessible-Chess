from __future__ import annotations

"""Periodic R26 online-entitlement monitor for an already-open premium window."""

import threading
from typing import Callable

from .protection_entitlement_lifecycle import (
    EntitlementLifecycleSnapshot,
    ProtectionEntitlementLifecycle,
)
from .protection_boundary import ProtectionRuntimeClient

_MIN_CHECK_SECONDS = 30
_MAX_CHECK_SECONDS = 900


class ProtectionLifecycleMonitor:
    """Poll private authority without ever exposing its credentials to the product UI."""

    def __init__(
        self,
        client: ProtectionRuntimeClient,
        *,
        lifecycle: ProtectionEntitlementLifecycle | None = None,
    ) -> None:
        if not isinstance(client, ProtectionRuntimeClient):
            raise TypeError("client must be a ProtectionRuntimeClient")
        self.client = client
        self.lifecycle = lifecycle or ProtectionEntitlementLifecycle(client)
        self.latest: EntitlementLifecycleSnapshot | None = None
        self.blocked: EntitlementLifecycleSnapshot | None = None
        self.failure_reason: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def _delay(snapshot: EntitlementLifecycleSnapshot) -> int:
        requested = snapshot.retry_after_seconds
        if requested <= 0:
            requested = _MIN_CHECK_SECONDS
        return max(_MIN_CHECK_SECONDS, min(requested, _MAX_CHECK_SECONDS))

    def poll_once(self) -> EntitlementLifecycleSnapshot:
        snapshot = self.lifecycle.synchronize()
        self.latest = snapshot
        if not snapshot.premium_allowed:
            self.blocked = snapshot
        return snapshot

    def start(
        self,
        *,
        warning_callback: Callable[[EntitlementLifecycleSnapshot], None],
        block_callback: Callable[[EntitlementLifecycleSnapshot | None], None],
    ) -> None:
        if not callable(warning_callback) or not callable(block_callback):
            raise TypeError("monitor callbacks must be callable")
        if self._thread is not None:
            raise RuntimeError("protection lifecycle monitor is already started")

        def run() -> None:
            try:
                while not self._stop.is_set():
                    try:
                        snapshot = self.poll_once()
                    except Exception:
                        self.failure_reason = "online_lifecycle_unavailable"
                        block_callback(None)
                        return

                    if not snapshot.premium_allowed:
                        block_callback(snapshot)
                        return
                    if snapshot.state in {"renewal_due", "network_grace"}:
                        warning_callback(snapshot)
                    if self._stop.wait(self._delay(snapshot)):
                        return
            finally:
                self._stop.set()

        self._thread = threading.Thread(
            target=run,
            name="accessible-chess-protection-monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    @property
    def blocked_or_failed(self) -> bool:
        return self.blocked is not None or self.failure_reason is not None


__all__ = ["ProtectionLifecycleMonitor"]
