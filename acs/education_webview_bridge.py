from __future__ import annotations

"""Strict command bridge for the read-only Education WebView projection."""

from collections.abc import Mapping
import re

from .education_webview_projection import EducationWebViewEvent, EducationWebViewProjection
from .full_product_ui_shell import concise_user_error


_ITEM_KEY_RE = re.compile(r"^[0-9a-f]{64}$")


class EducationWebViewBridge:
    def __init__(self, projection: EducationWebViewProjection) -> None:
        if not isinstance(projection, EducationWebViewProjection):
            raise TypeError("projection must be EducationWebViewProjection")
        self._projection = projection

    @property
    def projection(self) -> EducationWebViewProjection:
        return self._projection

    def _error(self) -> EducationWebViewEvent:
        return EducationWebViewEvent(
            "error",
            {"message": concise_user_error("", language=self._projection.language)},
        )

    @staticmethod
    def _payload(value: object) -> dict[str, object]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise TypeError("education browser payload must be a mapping")
        if len(value) > 2:
            raise ValueError("education browser payload has too many fields")
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str or not key or len(key) > 40 or "\x00" in key:
                raise ValueError("education browser payload key is invalid")
            result[key] = item
        return result

    @staticmethod
    def _exact(payload: Mapping[str, object], expected: set[str]) -> None:
        if set(payload) != expected:
            raise ValueError("education browser payload fields are invalid")

    @staticmethod
    def _text(value: object, *, name: str, limit: int) -> str:
        if type(value) is not str:
            raise TypeError(f"education {name} must be text")
        token = value.strip()
        if not token or len(token) > limit or "\x00" in token:
            raise ValueError(f"education {name} is invalid")
        return token

    @staticmethod
    def _direction(value: object) -> int:
        if type(value) is not int or value not in {-1, 1}:
            raise ValueError("education direction must be -1 or 1")
        return value

    def dispatch(
        self,
        command: object,
        payload: Mapping[str, object] | None = None,
    ) -> EducationWebViewEvent:
        try:
            command_id = self._text(command, name="command", limit=80)
            data = self._payload(payload)
            if command_id == "education.snapshot":
                self._exact(data, set())
                return EducationWebViewEvent("render", {"snapshot": self._projection.snapshot()})
            if command_id == "education.select":
                self._exact(data, {"kind", "item_key"})
                item_key = self._text(data["item_key"], name="item key", limit=64)
                if not _ITEM_KEY_RE.fullmatch(item_key):
                    raise ValueError("education item key is invalid")
                return self._projection.select(
                    self._text(data["kind"], name="kind", limit=24),
                    item_key,
                )
            if command_id == "education.move":
                self._exact(data, {"kind", "direction"})
                return self._projection.move_selection(
                    self._text(data["kind"], name="kind", limit=24),
                    self._direction(data["direction"]),
                )
            if command_id == "education.page":
                self._exact(data, {"kind", "direction"})
                return self._projection.change_page(
                    self._text(data["kind"], name="kind", limit=24),
                    self._direction(data["direction"]),
                )
            if command_id == "education.open":
                self._exact(data, {"kind"})
                return self._projection.open_selected(
                    self._text(data["kind"], name="kind", limit=24)
                )
            if command_id == "education.new_class":
                self._exact(data, set())
                return self._projection.new_class()
            raise ValueError("unsupported education browser command")
        except Exception:
            return self._error()
