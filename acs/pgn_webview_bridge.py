"""Strict browser-command boundary for the DEV1 PGN/GameTree WebView surface.

Only small presentation commands are accepted here. The bridge cannot dispatch
arbitrary application/chess action ids and never returns raw backend values.
"""
from __future__ import annotations

from collections.abc import Mapping

from .full_product_ui_shell import concise_user_error
from .pgn_webview_projection import PgnWebViewEvent, PgnWebViewProjection


class PgnWebViewBridge:
    def __init__(self, projection: PgnWebViewProjection) -> None:
        if not isinstance(projection, PgnWebViewProjection):
            raise TypeError("projection must be PgnWebViewProjection")
        self._projection = projection

    @property
    def projection(self) -> PgnWebViewProjection:
        return self._projection

    def _generic_error(self) -> PgnWebViewEvent:
        return PgnWebViewEvent(
            "error",
            {
                "message": concise_user_error(
                    "",
                    language=self._projection.language,
                )
            },
        )

    @staticmethod
    def _payload(value: object) -> dict[str, object]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise TypeError("PGN browser payload must be a mapping")
        if len(value) > 4:
            raise ValueError("PGN browser payload has too many fields")
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise TypeError("PGN browser payload keys must be text")
            token = key.strip()
            if len(token) > 64 or token in normalized:
                raise ValueError("invalid PGN browser payload key")
            normalized[token] = item
        return normalized

    @staticmethod
    def _exact_fields(payload: Mapping[str, object], allowed: set[str]) -> None:
        if set(payload) != allowed:
            raise ValueError("PGN browser payload fields are invalid")

    @staticmethod
    def _text(value: object, *, name: str, limit: int) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{name} must be text")
        if "\x00" in value or len(value) > limit:
            raise ValueError(f"{name} is invalid")
        token = value.strip() if name != "comment text" else value
        if name != "comment text" and not token:
            raise ValueError(f"{name} is invalid")
        return token

    def dispatch(
        self,
        command: object,
        payload: Mapping[str, object] | None = None,
    ) -> PgnWebViewEvent:
        try:
            if not isinstance(command, str):
                raise TypeError("PGN browser command must be text")
            command_id = command.strip()
            if not command_id or len(command_id) > 64:
                raise ValueError("PGN browser command is invalid")
            data = self._payload(payload)

            if command_id == "pgn.select":
                self._exact_fields(data, {"node_id"})
                node_id = self._text(data["node_id"], name="node id", limit=4096)
                return self._projection.select(node_id)
            if command_id == "pgn.move":
                self._exact_fields(data, {"delta"})
                delta = data["delta"]
                if type(delta) is not int or delta not in {-1, 1}:
                    raise ValueError("PGN selection delta must be -1 or 1")
                return self._projection.move_selection(delta)
            if command_id == "pgn.parent":
                self._exact_fields(data, set())
                return self._projection.select_parent()
            if command_id == "pgn.previous_game":
                self._exact_fields(data, set())
                return self._projection.previous_game()
            if command_id == "pgn.next_game":
                self._exact_fields(data, set())
                return self._projection.next_game()
            if command_id == "pgn.comment_edit":
                self._exact_fields(data, {"text"})
                text = self._text(data["text"], name="comment text", limit=8000)
                return self._projection.edit_comment(text)
            if command_id == "pgn.comment_delete":
                self._exact_fields(data, set())
                return self._projection.delete_comment()
            if command_id == "pgn.variation_delete":
                self._exact_fields(data, set())
                return self._projection.delete_variation()
            if command_id == "pgn.variation_promote":
                self._exact_fields(data, set())
                return self._projection.promote_variation()
            if command_id == "pgn.copy_selection":
                self._exact_fields(data, set())
                return self._projection.copy_selection()
            if command_id == "pgn.export_selection":
                self._exact_fields(data, set())
                return self._projection.export_selection()
            raise ValueError("unsupported PGN browser command")
        except Exception:
            # Browser validation is an internal seam. Never echo command text,
            # node ids, paths, PGN contents, backend exceptions, or provider data.
            return self._generic_error()
