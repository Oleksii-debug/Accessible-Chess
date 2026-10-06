"""Strict browser-command bridge for the accessible BookReader WebView surface."""
from __future__ import annotations

from collections.abc import Mapping

from .book_webview_projection import BookWebViewEvent, BookWebViewProjection


class BookWebViewBridge:
    def __init__(self, projection: BookWebViewProjection) -> None:
        if not isinstance(projection, BookWebViewProjection):
            raise TypeError("projection must be BookWebViewProjection")
        self._projection = projection

    @property
    def projection(self) -> BookWebViewProjection:
        return self._projection

    @staticmethod
    def _payload(value: object) -> dict[str, object]:
        if value is None:
            return {}
        # PyWebView JSON objects arrive as built-in dicts. Reject Mapping/dict
        # subclasses before len()/items() can execute hostile Python hooks.
        if type(value) is not dict:
            raise TypeError("book browser payload must be a mapping")
        if len(value) > 2:
            raise ValueError("book browser payload has too many fields")
        out: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("book browser payload keys must be text")
            if len(key) > 64:
                raise ValueError("invalid book browser payload key")
            token = key.strip()
            if not token or token in out:
                raise ValueError("invalid book browser payload key")
            out[token] = item
        return out

    @staticmethod
    def _exact(payload: Mapping[str, object], allowed: set[str]) -> None:
        if set(payload) != allowed:
            raise ValueError("book browser payload fields are invalid")

    def dispatch(
        self,
        command: object,
        payload: Mapping[str, object] | None = None,
    ) -> BookWebViewEvent:
        try:
            if type(command) is not str:
                raise TypeError("book browser command must be text")
            if len(command) > 64:
                raise ValueError("invalid book browser command")
            command_id = command.strip()
            if not command_id:
                raise ValueError("invalid book browser command")
            data = BookWebViewBridge._payload(payload)

            projection_type = type(self._projection)
            no_payload = {
                "book.previous": projection_type.previous,
                "book.next": projection_type.next,
                "book.previous_heading": projection_type.previous_heading,
                "book.next_heading": projection_type.next_heading,
                "book.previous_position": projection_type.previous_position,
                "book.next_position": projection_type.next_position,
                "book.previous_game": projection_type.previous_game,
                "book.next_game": projection_type.next_game,
                "book.open_position": projection_type.open_position,
                "book.open_game": projection_type.open_game,
                "book.return_from_board": projection_type.return_from_board,
            }
            callback = no_payload.get(command_id)
            if callback is not None:
                BookWebViewBridge._exact(data, set())
                return callback(self._projection)
            if command_id == "book.bookmark.save":
                BookWebViewBridge._exact(data, {"name"})
                return projection_type.save_bookmark(self._projection, data["name"])
            if command_id == "book.bookmark.restore":
                BookWebViewBridge._exact(data, {"name"})
                return projection_type.restore_bookmark(self._projection, data["name"])
            if command_id == "book.language":
                BookWebViewBridge._exact(data, {"language"})
                return projection_type.set_language(self._projection, data["language"])
            raise ValueError("unsupported book browser command")
        except BaseException:
            # Do not echo FEN, bookmark input, local paths, source data or internals.
            projection = self._projection
            projection_type = type(projection)
            return projection_type.generic_error(projection)
