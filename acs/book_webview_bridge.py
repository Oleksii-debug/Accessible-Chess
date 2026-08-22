"""Strict browser-command boundary for the DEV1 Book Reader WebView surface."""
from __future__ import annotations

from collections.abc import Mapping

from .book_webview_projection import BookWebViewEvent, BookWebViewProjection
from .full_product_ui_shell import concise_user_error


class BookWebViewBridge:
    def __init__(self, projection: BookWebViewProjection) -> None:
        if not isinstance(projection, BookWebViewProjection):
            raise TypeError("projection must be BookWebViewProjection")
        self._projection = projection

    @property
    def projection(self) -> BookWebViewProjection:
        return self._projection

    def _error(self) -> BookWebViewEvent:
        return BookWebViewEvent(
            "error",
            {"message": concise_user_error("", language=self._projection.language)},
        )

    @staticmethod
    def _payload(value: object) -> dict[str, object]:
        if value is None:
            return {}
        if not isinstance(value, Mapping) or len(value) > 2:
            raise ValueError("invalid book browser payload")
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip() or len(key.strip()) > 64:
                raise ValueError("invalid book browser payload key")
            token = key.strip()
            if token in result:
                raise ValueError("duplicate book browser payload key")
            result[token] = item
        return result

    @staticmethod
    def _exact(data: Mapping[str, object], fields: set[str]) -> None:
        if set(data) != fields:
            raise ValueError("invalid book browser payload fields")

    @staticmethod
    def _bookmark_name(value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("bookmark name must be text")
        name = value.strip()
        if not name or "\x00" in name or len(name) > 256:
            raise ValueError("invalid bookmark name")
        return name

    def dispatch(
        self,
        command: object,
        payload: Mapping[str, object] | None = None,
    ) -> BookWebViewEvent:
        try:
            if not isinstance(command, str) or not command.strip() or len(command.strip()) > 64:
                raise ValueError("invalid book browser command")
            command_id = command.strip()
            data = self._payload(payload)
            no_payload = {
                "book.previous_block": self._projection.previous_block,
                "book.next_block": self._projection.next_block,
                "book.previous_heading": self._projection.previous_heading,
                "book.next_heading": self._projection.next_heading,
                "book.next_position": self._projection.next_position,
                "book.next_game": self._projection.next_game,
                "book.open_position": self._projection.open_current_position,
                "book.return_from_board": self._projection.return_from_board,
            }
            if command_id in no_payload:
                self._exact(data, set())
                return self._projection.safe_call(no_payload[command_id])
            if command_id == "book.bookmark":
                self._exact(data, {"name"})
                name = self._bookmark_name(data["name"])
                return self._projection.safe_call(lambda: self._projection.bookmark(name))
            if command_id == "book.restore_bookmark":
                self._exact(data, {"name"})
                name = self._bookmark_name(data["name"])
                return self._projection.safe_call(lambda: self._projection.restore_bookmark(name))
            if command_id == "book.language":
                self._exact(data, {"language"})
                language = data["language"]
                if not isinstance(language, str) or len(language) > 8:
                    raise ValueError("invalid language")
                return self._projection.safe_call(lambda: self._projection.set_language(language))
            raise ValueError("unsupported book browser command")
        except Exception:
            # Never reflect a bookmark, FEN, source anchor, local path, or
            # canonical service exception into browser/NVDA error output.
            return self._error()
