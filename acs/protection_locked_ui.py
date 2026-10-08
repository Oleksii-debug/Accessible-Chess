from __future__ import annotations

"""Minimal accessibility-first locked shell for the R00-R14 protection boundary."""

from pathlib import Path
from typing import Any

from .protection_boundary import ONLINE_RUNTIME_API_VERSION, ProtectionDecision, ProtectionRuntimeClient
from .protection_online_boundary import ProtectionOnlineClient
from .webapp_keymap import _asset_root


class ProtectionLockedAPI:
    def __init__(
        self,
        client: ProtectionRuntimeClient,
        decision: ProtectionDecision,
        *,
        online_client: ProtectionOnlineClient | None = None,
    ) -> None:
        self.client = client
        self.decision = decision
        self.authorized = False
        self._window: Any | None = None
        if online_client is not None:
            self._online = online_client
        elif isinstance(client, ProtectionRuntimeClient):
            self._online = ProtectionOnlineClient(client)
        else:
            # Preserve Wave-1 test/adaptor compatibility. Online operations are
            # unavailable for duck-typed legacy clients unless explicitly injected.
            self._online = None
        self._online_flow_id: str | None = None
        self._online_mode: str | None = None

    def bind_window(self, window: Any) -> None:
        self._window = window

    def status(self) -> dict[str, object]:
        try:
            online_available = (
                self._online is not None
                and self.client.runtime_api_version() >= ONLINE_RUNTIME_API_VERSION
            )
        except Exception:
            online_available = False
        return {
            "state": self.decision.state,
            "reason": self.decision.reason,
            "safe_operations": sorted(self.decision.safe_operations),
            "build_id": self.decision.build_id,
            "online_available": online_available,
        }

    def _begin_online(self, mode: str) -> dict[str, object]:
        if self._online is None:
            return {"ok": False, "error": "online access is unavailable"}
        try:
            flow = self._online.begin(mode=mode)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        self._online_flow_id = flow.flow_id
        self._online_mode = flow.mode
        return {
            "ok": True,
            "mode": flow.mode,
            "expires_in_seconds": flow.expires_in_seconds,
        }

    def begin_online_login(self) -> dict[str, object]:
        return self._begin_online("login")

    def begin_online_registration(self) -> dict[str, object]:
        return self._begin_online("register")

    def poll_online_access(self) -> dict[str, object]:
        if self._online_flow_id is None:
            return {"ok": False, "error": "online access flow has not been started"}
        if self._online is None:
            return {"ok": False, "error": "online access is unavailable"}
        try:
            poll = self._online.poll(flow_id=self._online_flow_id)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        result: dict[str, object] = {
            "ok": True,
            "state": poll.state,
            "reason": poll.reason,
            "mode": self._online_mode,
            "authorized": False,
        }
        if not poll.completed:
            return result

        try:
            decision = self.client.evaluate()
        except Exception as exc:
            return {"ok": False, "authorized": False, "error": str(exc)}
        self.decision = decision
        if not decision.authorized:
            result["reason"] = decision.reason
            return result

        self.authorized = True
        result["authorized"] = True
        destroy = getattr(self._window, "destroy", None)
        if callable(destroy):
            destroy()
        return result

    def create_activation_request(self) -> dict[str, object]:
        try:
            request = self.client.create_activation_request()
            return {"ok": True, "request": request}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def import_entitlement(self, raw_json: str) -> dict[str, object]:
        try:
            self.client.import_entitlement_json(raw_json)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def retry(self) -> dict[str, object]:
        try:
            decision = self.client.evaluate()
        except Exception as exc:
            return {"ok": False, "authorized": False, "error": str(exc)}
        self.decision = decision
        if decision.authorized:
            self.authorized = True
            destroy = getattr(self._window, "destroy", None)
            if callable(destroy):
                destroy()
            return {"ok": True, "authorized": True}
        return {
            "ok": True,
            "authorized": False,
            "reason": decision.reason,
        }

    def close(self) -> dict[str, object]:
        destroy = getattr(self._window, "destroy", None)
        if callable(destroy):
            destroy()
        return {"ok": True}


def run_locked_security_window(
    client: ProtectionRuntimeClient,
    decision: ProtectionDecision,
    *,
    webview_module: Any | None = None,
) -> bool:
    api = ProtectionLockedAPI(client, decision)
    html = _asset_root() / "web" / "protection_locked.html"
    if not html.is_file():
        raise RuntimeError("Accessible protection locked-shell resource is missing")
    if webview_module is None:
        import webview as webview_module  # type: ignore[no-redef]
    window = webview_module.create_window(
        "Accessible Chess — Activation",
        url=str(html),
        js_api=api,
        width=820,
        height=700,
        min_size=(640, 520),
        text_select=True,
    )
    api.bind_window(window)
    webview_module.start(gui="edgechromium", private_mode=True)
    return api.authorized


__all__ = ["ProtectionLockedAPI", "run_locked_security_window"]
