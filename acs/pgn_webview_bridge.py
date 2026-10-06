"""Strict browser-command boundary for the DEV1 PGN/GameTree WebView surface.

Only small presentation commands are accepted here. The bridge cannot dispatch
arbitrary application/chess action ids and never returns raw backend values.
"""
from __future__ import annotations

from collections.abc import Mapping

from .full_product_ui_shell import concise_user_error
from .pgn_webview_projection import PgnWebViewEvent, PgnWebViewProjection, _utf16_units


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
        # PyWebView JSON objects arrive as built-in dicts. Reject Mapping/dict
        # subclasses before len()/items() can execute custom Python hooks.
        if type(value) is not dict:
            raise TypeError("PGN browser payload must be a mapping")
        if len(value) > 4:
            raise ValueError("PGN browser payload has too many fields")
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("PGN browser payload keys must be text")
            if len(key) > 64 or "\x00" in key:
                raise ValueError("invalid PGN browser payload key")
            token = key.strip()
            if not token or token in normalized:
                raise ValueError("invalid PGN browser payload key")
            normalized[token] = item
        return normalized

    @staticmethod
    def _exact_fields(payload: Mapping[str, object], allowed: set[str]) -> None:
        if set(payload) != allowed:
            raise ValueError("PGN browser payload fields are invalid")

    @staticmethod
    def _text(value: object, *, name: str, limit: int) -> str:
        if type(value) is not str:
            raise TypeError(f"{name} must be text")
        if _utf16_units(value) > limit or "\x00" in value:
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
            if type(command) is not str:
                raise TypeError("PGN browser command must be text")
            if len(command) > 64 or "\x00" in command:
                raise ValueError("PGN browser command is invalid")
            command_id = command.strip()
            if not command_id:
                raise ValueError("PGN browser command is invalid")
            data = self._payload(payload)
            has_presentation_token = "presentation_token" in data
            raw_presentation_token = data.pop("presentation_token", None)
            presentation_token: str | None = None
            if has_presentation_token:
                if (
                    type(raw_presentation_token) is not str
                    or len(raw_presentation_token) != 64
                    or any(
                        character not in "0123456789abcdef"
                        for character in raw_presentation_token
                    )
                ):
                    raise ValueError("PGN presentation token is invalid")
                presentation_token = raw_presentation_token

            def presentation_guard() -> PgnWebViewEvent | None:
                return self._projection.browser_presentation_guard(
                    presentation_token
                )

            if command_id == "pgn.refresh":
                self._exact_fields(data, set())
                return self._projection.refresh_view()

            if command_id == "pgn.select":
                self._exact_fields(data, {"node_id"})
                node_id = self._text(data["node_id"], name="node id", limit=4096)
                guarded = presentation_guard()
                if guarded is not None:
                    return guarded
                return self._projection.select(node_id)
            if command_id == "pgn.move":
                self._exact_fields(data, {"delta"})
                delta = data["delta"]
                if type(delta) is not int or delta not in {-1, 1}:
                    raise ValueError("PGN selection delta must be -1 or 1")
                guarded = presentation_guard()
                if guarded is not None:
                    return guarded
                return self._projection.move_selection(delta)
            if command_id == "pgn.parent":
                self._exact_fields(data, set())
                guarded = presentation_guard()
                if guarded is not None:
                    return guarded
                return self._projection.select_parent()
            if command_id == "pgn.previous_game":
                self._exact_fields(data, set())
                guarded = presentation_guard()
                if guarded is not None:
                    return guarded
                return self._projection.previous_game()
            if command_id == "pgn.next_game":
                self._exact_fields(data, set())
                guarded = presentation_guard()
                if guarded is not None:
                    return guarded
                return self._projection.next_game()
            if command_id == "pgn.tag_edit":
                self._exact_fields(data, {"name", "value"})
                name = self._text(data["name"], name="tag name", limit=80)
                value = data["value"]
                if type(value) is not str or _utf16_units(value) > 360 or "\x00" in value:
                    raise ValueError("tag value is invalid")
                guarded = presentation_guard()
                if guarded is not None:
                    return guarded
                return self._projection.edit_tag(name, value)
            if command_id == "pgn.tag_delete":
                self._exact_fields(data, {"name"})
                name = self._text(data["name"], name="tag name", limit=80)
                guarded = presentation_guard()
                if guarded is not None:
                    return guarded
                return self._projection.delete_tag(name)
            if command_id == "pgn.append_moves":
                self._exact_fields(data, {"text"})
                text = self._text(data["text"], name="continuation text", limit=8192)
                guarded = presentation_guard()
                if guarded is not None:
                    return guarded
                return self._projection.append_moves(text)
            if command_id == "pgn.search":
                self._exact_fields(data, {"text"})
                text = self._text(data["text"], name="search text", limit=4096)
                guarded = presentation_guard()
                if guarded is not None:
                    return guarded
                return self._projection.search(text)
            if command_id == "pgn.comment_edit":
                if set(data) == {"text"}:
                    text = self._text(data["text"], name="comment text", limit=8000)
                    slot = None
                    index = None
                else:
                    self._exact_fields(data, {"text", "slot", "index"})
                    text = self._text(data["text"], name="comment text", limit=8000)
                    slot = self._text(data["slot"], name="comment slot", limit=16)
                    index = data["index"]
                    if type(index) is not int or index < -1 or index > 255:
                        raise ValueError("comment index is invalid")
                guarded = presentation_guard()
                if guarded is not None:
                    return guarded
                return self._projection.edit_comment(text, slot=slot, index=index)
            if command_id == "pgn.comment_delete":
                if not data:
                    slot = None
                    index = None
                else:
                    self._exact_fields(data, {"slot", "index"})
                    slot = self._text(data["slot"], name="comment slot", limit=16)
                    index = data["index"]
                    if type(index) is not int or index < 0 or index > 255:
                        raise ValueError("comment index is invalid")
                guarded = presentation_guard()
                if guarded is not None:
                    return guarded
                return self._projection.delete_comment(slot=slot, index=index)
            if command_id == "pgn.nag_edit":
                self._exact_fields(data, {"text"})
                raw = data["text"]
                if type(raw) is not str or _utf16_units(raw) > 512 or "\x00" in raw:
                    raise ValueError("NAG text is invalid")
                text = raw.strip()
                guarded = presentation_guard()
                if guarded is not None:
                    return guarded
                return self._projection.edit_nags(text)
            if command_id == "pgn.variation_add":
                self._exact_fields(data, {"text"})
                text = self._text(data["text"], name="variation text", limit=8192)
                guarded = presentation_guard()
                if guarded is not None:
                    return guarded
                return self._projection.add_variation(text)
            if command_id == "pgn.variation_delete":
                self._exact_fields(data, set())
                guarded = presentation_guard()
                if guarded is not None:
                    return guarded
                return self._projection.delete_variation()
            if command_id == "pgn.variation_promote":
                self._exact_fields(data, set())
                guarded = presentation_guard()
                if guarded is not None:
                    return guarded
                return self._projection.promote_variation()
            if command_id == "pgn.copy_selection":
                self._exact_fields(data, set())
                guarded = presentation_guard()
                if guarded is not None:
                    return guarded
                return self._projection.copy_selection()
            if command_id == "pgn.export_selection":
                self._exact_fields(data, set())
                guarded = presentation_guard()
                if guarded is not None:
                    return guarded
                return self._projection.export_selection()
            raise ValueError("unsupported PGN browser command")
        except Exception:
            # Browser validation is an internal seam. Never echo command text,
            # node ids, paths, PGN contents, backend exceptions, or provider data.
            return self._generic_error()
