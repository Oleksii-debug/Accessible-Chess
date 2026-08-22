"""Strict browser-command bridge for the Library/Search WebView surface."""
from __future__ import annotations

from collections.abc import Mapping

from .library_webview_projection import LibraryWebViewEvent, LibraryWebViewProjection


class LibraryWebViewBridge:
    def __init__(self, projection: LibraryWebViewProjection) -> None:
        if not isinstance(projection, LibraryWebViewProjection):
            raise TypeError("projection must be LibraryWebViewProjection")
        self._projection = projection

    @property
    def projection(self) -> LibraryWebViewProjection:
        return self._projection

    @staticmethod
    def _payload(value: object) -> dict[str, object]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise TypeError("library browser payload must be a mapping")
        if len(value) > 8:
            raise ValueError("library browser payload has too many fields")
        out: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("library browser payload keys must be text")
            token = key.strip()
            if not token or len(token) > 64 or token in out:
                raise ValueError("invalid library browser payload key")
            out[token] = item
        return out

    @staticmethod
    def _exact(payload: Mapping[str, object], allowed: set[str]) -> None:
        if set(payload) != allowed:
            raise ValueError("library browser payload fields are invalid")

    def dispatch(
        self,
        command: object,
        payload: Mapping[str, object] | None = None,
    ) -> LibraryWebViewEvent:
        try:
            if not isinstance(command, str):
                raise TypeError("library browser command must be text")
            command_id = command.strip()
            if not command_id or len(command_id) > 64:
                raise ValueError("invalid library browser command")
            data = self._payload(payload)

            if command_id == "library.search":
                fields = {"player", "event", "eco", "opening", "result", "source_name"}
                self._exact(data, fields)
                return self._projection.search(data)
            if command_id == "library.reset":
                self._exact(data, set())
                return self._projection.reset()
            if command_id == "library.select":
                self._exact(data, {"game_id"})
                game_id = data["game_id"]
                if type(game_id) is not int:
                    raise TypeError("game_id must be an integer")
                return self._projection.select(game_id)
            if command_id == "library.move":
                self._exact(data, {"delta"})
                delta = data["delta"]
                if type(delta) is not int or delta not in {-1, 1}:
                    raise ValueError("delta must be -1 or 1")
                return self._projection.move_selection(delta)
            if command_id == "library.previous_page":
                self._exact(data, set())
                return self._projection.previous_page()
            if command_id == "library.next_page":
                self._exact(data, set())
                return self._projection.next_page()
            if command_id == "library.open":
                self._exact(data, set())
                return self._projection.open_selected()
            if command_id in {"library.import", "library.export", "library.cancel_import"}:
                self._exact(data, set())
                return self._projection.external_action(command_id)
            raise ValueError("unsupported library browser command")
        except Exception:
            # Never echo query text, ids, local paths, SQL/provider text or backend details.
            return self._projection.generic_error()
