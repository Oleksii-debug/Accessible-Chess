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
        if not isinstance(value, Mapping):
            raise TypeError("book browser payload must be a mapping")
        if len(value) > 2:
            raise ValueError("book browser payload has too many fields")
        out: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("book browser payload keys must be text")
            token = key.strip()
            if not token or len(token) > 64 or token in out:
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
            if not isinstance(command, str):
                raise TypeError("book browser command must be text")
            command_id = command.strip()
            if not command_id or len(command_id) > 64:
                raise ValueError("invalid book browser command")
            data = self._payload(payload)

            no_payload = {
                "book.previous": self._projection.previous,
                "book.next": self._projection.next,
                "book.previous_heading": self._projection.previous_heading,
                "book.next_heading": self._projection.next_heading,
                "book.next_position": self._projection.next_position,
                "book.next_game": self._projection.next_game,
                "book.open_position": self._projection.open_position,
                "book.return_from_board": self._projection.return_from_board,
            }
            callback = no_payload.get(command_id)
            if callback is not None:
                self._exact(data, set())
                return callback()
            if command_id == "book.bookmark.save":
                self._exact(data, {"name"})
                return self._projection.save_bookmark(data["name"])
            if command_id == "book.bookmark.restore":
                self._exact(data, {"name"})
                return self._projection.restore_bookmark(data["name"])
            if command_id == "book.language":
                self._exact(data, {"language"})
                return self._projection.set_language(data["language"])
            raise ValueError("unsupported book browser command")
        except Exception:
            # Do not echo FEN, bookmark input, local paths, source data or internals.
            return self._projection.generic_error()
