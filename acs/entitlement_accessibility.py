from __future__ import annotations

"""Accessible end-user composition for entitlement status and recovery intents.

The entitlement authority remains outside presentation.  This adapter consumes
only the existing provider-neutral projection from :mod:`acs.ui_entitlement` and
emits semantic state suitable for the Windows/WebView shell.  Recovery actions
are delegated as stable intents; authentication, networking, billing and update
implementation remain owned by their respective application services.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .ui_entitlement import EntitlementView, project_entitlement, semantic_contract


_ALLOWED_ACTIONS = frozenset(
    {
        "account.status",
        "account.login",
        "entitlement.refresh",
        "app.update",
    }
)


@dataclass(frozen=True, slots=True)
class EntitlementAccessibleSnapshot:
    """Detached semantic snapshot for one access-status screen render."""

    view: EntitlementView
    semantic: Mapping[str, Any]
    focus_target: str

    def as_dict(self) -> dict[str, Any]:
        return {
            **dict(self.semantic),
            "focusTarget": self.focus_target,
        }


class EntitlementAccessibilityPresenter:
    """Bind neutral entitlement state to one accessible Product surface.

    The provider is re-read before every delegated action.  A browser/native
    request therefore cannot replay an action that belonged to an older access
    state (for example ``account.login`` after a successful refresh).
    """

    def __init__(
        self,
        state_provider: Callable[[], Mapping[str, Any] | None],
        dispatch: Callable[[str, Mapping[str, object]], Any],
        *,
        language: str = "uk",
    ) -> None:
        if not callable(state_provider):
            raise TypeError("entitlement state provider must be callable")
        if not callable(dispatch):
            raise TypeError("entitlement action dispatcher must be callable")
        if language not in {"uk", "en"}:
            raise ValueError("entitlement UI language must be uk or en")
        self._state_provider = state_provider
        self._dispatch = dispatch
        self._language = language

    @property
    def language(self) -> str:
        return self._language

    def set_language(self, language: str) -> None:
        if language not in {"uk", "en"}:
            raise ValueError("entitlement UI language must be uk or en")
        self._language = language

    def _view(self) -> EntitlementView:
        try:
            payload = self._state_provider()
            if payload is not None and not isinstance(payload, Mapping):
                payload = None
            view = project_entitlement(payload, lang=self._language)
        except Exception:
            # Provider or malformed projection internals must not cross the
            # presentation boundary.  Missing state is the canonical blocking,
            # data-preserving recovery projection and remains keyboard reachable.
            view = project_entitlement(None, lang=self._language)
        if view.action_id is not None and view.action_id not in _ALLOWED_ACTIONS:
            raise ValueError("entitlement projection exposed an unsupported action")
        return view

    def snapshot(self) -> EntitlementAccessibleSnapshot:
        view = self._view()
        semantic = semantic_contract(view)
        focus_target = "entitlement-action" if view.action_id else "entitlement-status"
        return EntitlementAccessibleSnapshot(
            view=view,
            semantic=semantic,
            focus_target=focus_target,
        )

    def activate(self, action_id: str) -> Any:
        """Dispatch only the action currently authorized by the live projection."""

        if not isinstance(action_id, str) or not action_id.strip():
            raise ValueError("entitlement action id is required")
        requested = action_id.strip()
        current = self._view().action_id
        if current is None or requested != current:
            raise ValueError("entitlement action is stale or unavailable")
        if requested not in _ALLOWED_ACTIONS:
            raise ValueError("unsupported entitlement action")
        return self._dispatch(requested, {})
