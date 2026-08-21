from __future__ import annotations

"""Stage 1 native-menu adapter for central Action Registry dispatch.

The frozen Windows menu remains the presentation owner. This proxy changes
only callbacks for actions that already have stable central action IDs, so the
native menu and WebView keyboard path converge on the same dispatcher without
forking chess state or rewriting the QA-proven MenuStrip implementation.

Construction intentionally accepts partial release-window test doubles. Stable
registry actions still fail closed at invocation time unless the wrapped API
exposes the canonical ``dispatch_action`` entry point; they never fall back to
legacy direct methods.
"""

from typing import Any


class Stage1NativeMenuActionProxy:
    _DIRECT_ACTIONS = {
        "undo": "edit.undo",
        "redo": "edit.redo",
        "review_previous": "history.previous",
        "review_next": "history.next",
        "restart_analysis": "analysis.restart",
        "toggle_analysis_lock": "analysis.lock_target",
        "explore_analysis_pv": "analysis.explore_pv",
        "return_from_analysis": "analysis.return",
        "insert_analysis_move": "analysis.insert_move",
        "insert_analysis_line": "analysis.insert_line",
    }

    def __init__(self, api: Any) -> None:
        self._api = api

    @property
    def wrapped_api(self) -> Any:
        return self._api

    def _dispatch_action(self, action_id: str) -> Any:
        dispatch = getattr(self._api, "dispatch_action", None)
        if not callable(dispatch):
            raise TypeError("native menu API must expose dispatch_action")
        return dispatch(action_id)

    def __getattr__(self, name: str) -> Any:
        action_id = self._DIRECT_ACTIONS.get(name)
        if action_id is not None:
            return lambda: self._dispatch_action(action_id)
        return getattr(self._api, name)

    def select_relative_analysis_pv(self, delta: int) -> Any:
        if type(delta) is not int or delta not in {-1, 1}:
            raise ValueError("native analysis PV delta must be -1 or 1")
        return self._dispatch_action(
            "analysis.previous_pv" if delta < 0 else "analysis.next_pv"
        )
