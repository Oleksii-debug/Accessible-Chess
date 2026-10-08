from __future__ import annotations

"""Minimal accessibility-first locked shell for the R00-R14 protection boundary."""

from pathlib import Path
from typing import Any

from .protection_boundary import ProtectionDecision, ProtectionRuntimeClient
from .webapp_keymap import _asset_root


class ProtectionLockedAPI:
    def __init__(self, client: ProtectionRuntimeClient, decision: ProtectionDecision) -> None:
        self.client = client
        self.decision = decision
        self.authorized = False
        self._window: Any | None = None

    def bind_window(self, window: Any) -> None:
        self._window = window

    def status(self) -> dict[str, object]:
        return {
            "state": self.decision.state,
            "reason": self.decision.reason,
            "safe_operations": sorted(self.decision.safe_operations),
            "build_id": self.decision.build_id,
        }

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
