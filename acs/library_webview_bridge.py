"""Library/Search browser adapter for the DEV1 presentation layer."""
from __future__ import annotations

from collections.abc import Mapping

from .full_product_ui_shell import concise_user_error
from .library_webview_projection import LibraryWebViewEvent, LibraryWebViewProjection
from .search_service import GameSearchQuery


_BROWSER_MAX_SAFE_INTEGER = (1 << 53) - 1


class LibraryWebViewBridge:
    _SEARCH_FIELDS = frozenset(
        {"player", "event", "eco", "opening", "result", "source_id", "source_name", "limit", "date_from", "date_to"}
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
        if type(value) is not dict:
            raise ValueError("invalid library browser payload")
        if len(value) > 10:
            raise ValueError("invalid library browser payload")
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str or len(key) > 64 or "\x00" in key:
                raise ValueError("invalid library browser payload key")
            token = key.strip()
            if not token:
                raise ValueError("invalid library browser payload key")
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
        if value is None:
            return None
        if type(value) is not str:
            raise ValueError(f"invalid {name}")
        if value == "":
            return None
        if "\x00" in value or len(value) > 256:
            raise ValueError(f"invalid {name}")
        return value

    @staticmethod
    def _positive_int(value: object, name: str) -> int | None:
        if value is None:
            return None
        if type(value) is int:
            integer = value
        elif type(value) is str:
            if value == "":
                return None
            if len(value) > 19 or not value.isascii() or not value.isdecimal():
                raise ValueError(f"invalid {name}")
            integer = int(value)
        else:
            raise ValueError(f"invalid {name}")
        if integer <= 0 or integer > (1 << 63) - 1:
            raise ValueError(f"invalid {name}")
        return integer

    @staticmethod
    def _browser_game_id(value: object) -> int:
        integer = LibraryWebViewBridge._positive_int(value, "game_id")
        if integer is None or integer > _BROWSER_MAX_SAFE_INTEGER:
            raise ValueError("invalid browser-safe game_id")
        return integer

    @staticmethod
    def _limit(value: object) -> int:
        if value is None:
            return 50
        if type(value) is int:
            integer = value
        elif type(value) is str:
            if value == "":
                return 50
            if len(value) > 3 or not value.isascii() or not value.isdecimal():
                raise ValueError("invalid limit")
            integer = int(value)
        else:
            raise ValueError("invalid limit")
        if not 1 <= integer <= 200:
            raise ValueError("invalid limit")
        return integer

    @staticmethod
    def _result(value: object) -> str | None:
        if value is None:
            return None
        if type(value) is not str:
            raise ValueError("invalid result")
        if value == "":
            return None
        if value not in {"1-0", "0-1", "1/2-1/2", "*"}:
            raise ValueError("invalid result")
        return value

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
            date_from=self._text(data.get("date_from"), "date_from"),
            date_to=self._text(data.get("date_to"), "date_to"),
            limit=self._limit(data.get("limit")),
        ).normalized()

    def _export_method(self, name: str):
        method = getattr(self._projection, name, None)
        if not callable(method):
            raise ValueError("Library export projection is unavailable")
        return method

    def dispatch(self, command: object, payload: Mapping[str, object] | None = None) -> LibraryWebViewEvent:
        try:
            if type(command) is not str or len(command) > 64 or "\x00" in command:
                raise ValueError("invalid library browser command")
            command_id = command.strip()
            if not command_id:
                raise ValueError("invalid library browser command")
            data = self._payload(payload)
            if command_id == "library.search":
                return self._projection.search(self._query(data))
            if command_id == "library.reset_filters":
                self._exact(data, set())
                return self._projection.reset_filters()
            if command_id == "library.select":
                self._exact(data, {"game_id"})
                game_id = self._browser_game_id(data["game_id"])
                return self._projection.select(game_id)
            if command_id == "library.move":
                self._exact(data, {"delta"})
                delta = data["delta"]
                if type(delta) is not int or delta not in {-1, 1}:
                    raise ValueError("invalid selection delta")
                return self._projection.move_selection(delta)
            if command_id == "library.toggle_export_selection":
                self._exact(data, {"game_id"})
                game_id = self._browser_game_id(data["game_id"])
                return self._export_method("toggle_export_selection")(game_id)
            if command_id == "library.clear_export_selection":
                self._exact(data, set())
                return self._export_method("clear_export_selection")()
            if command_id == "library.export_selected":
                self._exact(data, set())
                return self._export_method("request_export_selected")()
            if command_id == "library.export_filtered":
                self._exact(data, set())
                return self._export_method("request_export_filtered")()
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
                cancel_operation = getattr(
                    self._projection, "request_cancel_operation", None
                )
                if callable(cancel_operation):
                    return cancel_operation()
                return self._projection.import_projection.request_cancel()
            if command_id == "library.language":
                self._exact(data, {"language"})
                language = data["language"]
                if type(language) is not str or len(language) > 8:
                    raise ValueError("invalid language")
                return self._projection.set_language(language)
            raise ValueError("unsupported library browser command")
        except BaseException:
            return self._error()
