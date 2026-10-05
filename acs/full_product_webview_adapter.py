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

    @property
    def registry(self):
        """Expose the router's one central action registry to native UI adapters."""
        return self._router.registry

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

        previous_language = self._shell.language
        try:
            self._shell.set_language(parsed)
            snapshot = self.snapshot()
        except BaseException:
            # The shell is the application-wide locale authority. A failed
            # semantic/navigation snapshot must not commit a language that the
            # WebView never rendered, otherwise subsequent NVDA errors and route
            # labels can disagree with the still-visible document.
            self._shell.set_language(previous_language)
            raise
        return WebViewCommand("render", snapshot)

    def record_focus(self, element_id: str) -> WebViewCommand:
        self._shell.record_focus(element_id)
        # _clean_focus_id rejects surrounding whitespace and active str
        # subclasses, so the exact validated built-in string is already the
        # canonical browser identity. Do not invoke it again after mutation.
        return WebViewCommand("focus-recorded", {"element_id": element_id})

    def _safe_error(self, exc: BaseException) -> WebViewCommand:
        # Registry misses and non-domain exceptions are implementation details,
        # not user-facing messages. In particular, OSError text can expose local
        # paths or storage state. Only a plain ValueError is an intentional
        # concise domain message from the application boundary.
        source: object = exc if type(exc) is ValueError else ""
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
        previous_shell = self._shell._capture_presentation_state()
        try:
            result = self._router.dispatch(
                action_id,
                payload,
                current_focus_id=current_focus_id,
            )
        except BaseException as exc:  # UI boundary: sanitize before user projection.
            # Dispatch may already have recorded focus or a delegate may have
            # changed routes before failing.  Domain effects are not reversible
            # here, but unpublished presentation state must stay aligned with
            # the WebView/NVDA document the user actually has.
            self._shell._restore_presentation_state(previous_shell)
            return self._safe_error(exc)
        if result.handled_by_shell:
            try:
                snapshot = self.snapshot()
            except BaseException as exc:
                self._shell._restore_presentation_state(previous_shell)
                return self._safe_error(exc)
            return WebViewCommand(
                "route",
                {
                    "route_id": result.route_id or "",
                    "focus_target": result.focus_target or "",
                    "snapshot": snapshot,
                },
            )
        return WebViewCommand(
            "delegated",
            # The trusted host owns the domain return value.  It may contain
            # paths, database identities, engine-provider details or objects
            # that are not a stable browser contract.
            {"action_id": result.action_id},
        )

    def open_dialog(
        self,
        dialog_id: str,
        *,
        opener_focus_id: str,
        initial_focus_id: str,
    ) -> WebViewCommand:
        previous_shell = self._shell._capture_presentation_state()
        try:
            target = self._shell.open_dialog(
                dialog_id,
                opener_focus_id=opener_focus_id,
                initial_focus_id=initial_focus_id,
            )
        except BaseException as exc:
            self._shell._restore_presentation_state(previous_shell)
            return self._safe_error(exc)
        return WebViewCommand(
            "dialog-open",
            # The shell accepted only an exact, regex-valid built-in string.
            # Reuse it directly so no post-mutation string hook can run.
            {"dialog_id": dialog_id, "focus_target": target},
        )

    def close_dialog(self, dialog_id: str | None = None) -> WebViewCommand:
        previous_shell = self._shell._capture_presentation_state()
        try:
            target = self._shell.close_dialog(dialog_id)
        except BaseException as exc:
            self._shell._restore_presentation_state(previous_shell)
            return self._safe_error(exc)
        return WebViewCommand("dialog-close", {"focus_target": target})

    @staticmethod
    def is_editable_target(
        *,
        tag_name: str,
        content_editable: bool = False,
    ) -> bool:
        # Browser KeyboardEvent/DOM metadata is passive JSON-like data. Reject
        # active Python values before truthiness, len/strip/lower or iteration
        # can execute provider-defined hooks.
        if type(tag_name) is not str:
            raise TypeError("keyboard target tag must be text")
        if len(tag_name) > 32 or "\x00" in tag_name:
            raise ValueError("keyboard target tag is invalid")
        if type(content_editable) is not bool:
            raise TypeError("content-editable flag must be boolean")
        tag = tag_name.strip().lower()
        return content_editable or tag in _EDITABLE_TAGS

    @staticmethod
    def _keyboard_ingress(
        *,
        key: object,
        modifiers: object,
        tag_name: object,
        content_editable: object,
    ) -> tuple[str, tuple[str, ...], bool]:
        if type(key) is not str:
            raise TypeError("keyboard key must be text")
        if not key or len(key) > 64 or "\x00" in key:
            raise ValueError("keyboard key is invalid")
        if type(modifiers) not in (list, tuple):
            raise TypeError("keyboard modifiers must be a list or tuple")
        if len(modifiers) > 8:
            raise ValueError("too many keyboard modifiers")
        normalized_modifiers: list[str] = []
        for item in modifiers:
            if type(item) is not str:
                raise TypeError("keyboard modifiers must contain text")
            if not item or len(item) > 16 or "\x00" in item:
                raise ValueError("keyboard modifier is invalid")
            token = item.strip().lower()
            if not token:
                raise ValueError("keyboard modifier is invalid")
            normalized_modifiers.append(token)
        editable = FullProductWebViewAdapter.is_editable_target(
            tag_name=tag_name,
            content_editable=content_editable,
        )
        return key, tuple(normalized_modifiers), editable

    def keydown_policy(
        self,
        *,
        key: str,
        modifiers: Iterable[str],
        tag_name: str = "",
        content_editable: bool = False,
    ) -> WebViewCommand:
        try:
            safe_key, safe_modifiers, editable = self._keyboard_ingress(
                key=key,
                modifiers=modifiers,
                tag_name=tag_name,
                content_editable=content_editable,
            )
        except (TypeError, ValueError):
            # Malformed browser metadata must never cause the application to
            # steal a keystroke. Treat the uncertain target as editable and let
            # the browser/native control own the event.
            return WebViewCommand(
                "keydown-policy",
                {
                    "global_keymap": False,
                    "prevent_default": False,
                    "editable": True,
                },
            )
        handle = should_global_keymap_handle(
            key=safe_key,
            modifiers=safe_modifiers,
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
