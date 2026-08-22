"""WebView-facing adapter for the full-product accessible shell.

The adapter is deliberately presentation-only. It turns the canonical DEV1 shell
and action router into deterministic commands/snapshots suitable for a Windows
WebView2 host. Chess/domain work remains delegated through FullProductActionRouter.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .full_product_actions import FullProductActionRouter
from .full_product_ui_shell import (
    AccessibleShellState,
    UILanguage,
    concise_user_error,
    should_global_keymap_handle,
)


_EDITABLE_TAGS = frozenset({"input", "textarea", "select"})


@dataclass(frozen=True, slots=True)
class WebViewCommand:
    kind: str
    payload: Mapping[str, object]


class FullProductWebViewAdapter:
    """Single UI seam between WebView events and the central action router.

    The host may serialize ``snapshot`` and ``WebViewCommand.payload`` to JSON.
    No browser event is allowed to mutate chess/domain state directly here.
    """

    def __init__(
        self,
        shell: AccessibleShellState,
        router: FullProductActionRouter,
    ) -> None:
        if not isinstance(shell, AccessibleShellState):
            raise TypeError("shell must be AccessibleShellState")
        if not isinstance(router, FullProductActionRouter):
            raise TypeError("router must be FullProductActionRouter")
        self._shell = shell
        self._router = router

    @property
    def shell(self) -> AccessibleShellState:
        return self._shell

    def snapshot(self) -> dict[str, object]:
        semantic = self._shell.semantic_snapshot()
        navigation = self._shell.navigation_items()
        # Validate every exposed navigation action against the one central registry.
        for item in navigation:
            self._router.registry.definition(str(item["action_id"]))
        return {
            "document": {
                "lang": self._shell.language.value,
                "title": semantic["heading"],
                "landmark": semantic["landmark"],
                "heading_level": 1,
            },
            "navigation": navigation,
            "screen": semantic,
        }

    def set_language(self, language: str) -> WebViewCommand:
        try:
            parsed = UILanguage(language.strip().lower())
        except (AttributeError, ValueError):
            raise ValueError("unsupported UI language") from None
        self._shell.set_language(parsed)
        return WebViewCommand("render", self.snapshot())

    def record_focus(self, element_id: str) -> WebViewCommand:
        self._shell.record_focus(element_id)
        return WebViewCommand("focus-recorded", {"element_id": element_id.strip()})

    def _safe_error(self, exc: Exception) -> WebViewCommand:
        # Registry misses are developer/integration details, never user-facing IDs.
        source: object = "" if isinstance(exc, KeyError) else exc
        return WebViewCommand(
            "error",
            {"message": concise_user_error(source, language=self._shell.language)},
        )

    def activate_action(
        self,
        action_id: str,
        payload: Mapping[str, object] | None = None,
        *,
        current_focus_id: str = "",
    ) -> WebViewCommand:
        try:
            result = self._router.dispatch(
                action_id,
                payload,
                current_focus_id=current_focus_id,
            )
        except Exception as exc:  # UI boundary: sanitize before user projection.
            return self._safe_error(exc)
        if result.handled_by_shell:
            return WebViewCommand(
                "route",
                {
                    "route_id": result.route_id or "",
                    "focus_target": result.focus_target or "",
                    "snapshot": self.snapshot(),
                },
            )
        return WebViewCommand(
            "delegated",
            {"action_id": result.action_id, "value": result.value},
        )

    def open_dialog(
        self,
        dialog_id: str,
        *,
        opener_focus_id: str,
        initial_focus_id: str,
    ) -> WebViewCommand:
        try:
            target = self._shell.open_dialog(
                dialog_id,
                opener_focus_id=opener_focus_id,
                initial_focus_id=initial_focus_id,
            )
        except Exception as exc:
            return self._safe_error(exc)
        return WebViewCommand(
            "dialog-open",
            {"dialog_id": dialog_id.strip(), "focus_target": target},
        )

    def close_dialog(self, dialog_id: str | None = None) -> WebViewCommand:
        try:
            target = self._shell.close_dialog(dialog_id)
        except Exception as exc:
            return self._safe_error(exc)
        return WebViewCommand("dialog-close", {"focus_target": target})

    @staticmethod
    def is_editable_target(
        *,
        tag_name: str,
        content_editable: bool = False,
    ) -> bool:
        tag = str(tag_name or "").strip().lower()
        return bool(content_editable) or tag in _EDITABLE_TAGS

    def keydown_policy(
        self,
        *,
        key: str,
        modifiers: Iterable[str],
        tag_name: str = "",
        content_editable: bool = False,
    ) -> WebViewCommand:
        editable = self.is_editable_target(
            tag_name=tag_name,
            content_editable=content_editable,
        )
        handle = should_global_keymap_handle(
            key=key,
            modifiers=modifiers,
            editable=editable,
        )
        return WebViewCommand(
            "keydown-policy",
            {
                "global_keymap": handle,
                "prevent_default": handle,
                "editable": editable,
            },
        )
