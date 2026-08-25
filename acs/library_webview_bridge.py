"""Library/Search browser adapter for the DEV1 presentation layer."""
from __future__ import annotations

from collections.abc import Mapping

from .full_product_ui_shell import concise_user_error
from .library_webview_projection import LibraryWebViewEvent, LibraryWebViewProjection
from .search_service import GameSearchQuery


class LibraryWebViewBridge:
    _SEARCH_FIELDS = frozenset(
        {"player", "event", "eco", "opening", "result", "source_id", "source_name", "limit"}
    )

    def __init__(self, projection: LibraryWebViewProjection) -> None:
        if not isinstance(projection, LibraryWebViewProjection):
            raise TypeError("projection must be LibraryWebViewProjection")
        self._projection = projection

    @property
    def projection(self) -> LibraryWebViewProjection:
        return self._projection

    def _error(self) -> LibraryWebViewEvent:
        return LibraryWebViewEvent(
            "error",
            {"message": concise_user_error("", language=self._projection.language)},
        )

    @staticmethod
    def _payload(value: object) -> dict[str, object]:
        if value is None:
            return {}
        if not isinstance(value, Mapping) or len(value) > 8:
            raise ValueError("invalid library browser payload")
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip() or len(key.strip()) > 64:
                raise ValueError("invalid library browser payload key")
            token = key.strip()
            if token in result:
                raise ValueError("duplicate library browser payload key")
            result[token] = item
        return result

    @staticmethod
    def _exact(data: Mapping[str, object], fields: set[str]) -> None:
        if set(data) != fields:
            raise ValueError("invalid library browser payload fields")

    @staticmethod
    def _text(value: object, name: str) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str) or "\x00" in value or len(value) > 256:
            raise ValueError(f"invalid {name}")
        return value

    @staticmethod
    def _positive_int(value: object, name: str) -> int | None:
        if value is None or value == "":
            return None
        if type(value) is int:
            integer = value
        elif isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 19:
            integer = int(value)
        else:
            raise ValueError(f"invalid {name}")
        if integer <= 0 or integer > (1 << 63) - 1:
            raise ValueError(f"invalid {name}")
        return integer

    @staticmethod
    def _limit(value: object) -> int:
        if value is None or value == "":
            return 50
        if type(value) is int:
            integer = value
        elif isinstance(value, str) and value.isascii() and value.isdecimal():
            integer = int(value)
        else:
            raise ValueError("invalid limit")
        if not 1 <= integer <= 200:
            raise ValueError("invalid limit")
        return integer

    @staticmethod
    def _result(value: object) -> str | None:
        if value is None or value == "":
            return None
        if value not in {"1-0", "0-1", "1/2-1/2", "*"}:
            raise ValueError("invalid result")
        return str(value)

    def _query(self, data: Mapping[str, object]) -> GameSearchQuery:
        if set(data).difference(self._SEARCH_FIELDS):
            raise ValueError("unsupported search field")
        return GameSearchQuery(
            player=self._text(data.get("player"), "player"),
            event=self._text(data.get("event"), "event"),
            eco=self._text(data.get("eco"), "eco"),
            opening=self._text(data.get("opening"), "opening"),
            result=self._result(data.get("result")),
            source_id=self._positive_int(data.get("source_id"), "source_id"),
            source_name=self._text(data.get("source_name"), "source_name"),
            limit=self._limit(data.get("limit")),
        ).normalized()

    def dispatch(self, command: object, payload: Mapping[str, object] | None = None) -> LibraryWebViewEvent:
        try:
            if not isinstance(command, str) or not command.strip() or len(command.strip()) > 64:
                raise ValueError("invalid library browser command")
            command_id = command.strip()
            data = self._payload(payload)
            if command_id == "library.search":
                return self._projection.search(self._query(data))
            if command_id == "library.reset_filters":
                self._exact(data, set())
                return self._projection.reset_filters()
            if command_id == "library.select":
                self._exact(data, {"game_id"})
                game_id = self._positive_int(data["game_id"], "game_id")
                if game_id is None:
                    raise ValueError("game id required")
                return self._projection.select(game_id)
            if command_id == "library.move":
                self._exact(data, {"delta"})
                delta = data["delta"]
                if type(delta) is not int or delta not in {-1, 1}:
                    raise ValueError("invalid selection delta")
                return self._projection.move_selection(delta)
            if command_id == "library.previous_page":
                self._exact(data, set())
                return self._projection.previous_page()
            if command_id == "library.next_page":
                self._exact(data, set())
                return self._projection.next_page()
            if command_id == "library.open_game":
                self._exact(data, set())
                return self._projection.open_selected()
            if command_id == "library.import":
                self._exact(data, set())
                return self._projection.import_projection.request_import()
            if command_id == "library.cancel_import":
                self._exact(data, set())
                return self._projection.import_projection.request_cancel()
            if command_id == "library.language":
                self._exact(data, {"language"})
                language = data["language"]
                if not isinstance(language, str) or len(language) > 8:
                    raise ValueError("invalid language")
                return self._projection.set_language(language)
            raise ValueError("unsupported library browser command")
        except Exception:
            return self._error()
