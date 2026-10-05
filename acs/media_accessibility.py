from __future__ import annotations

"""Accessible presentation boundary for canonical Media Restore Position.

The canonical :class:`MediaApplicationService` remains the only owner of media
cursor transactions and the only component allowed to invoke the injected chess
application restore command.  This module only projects that service into a
small browser/screen-reader-safe DTO and maps failures to bounded user text.

Opaque canonical chess references deliberately never cross this boundary.
"""

from typing import Any

from .media_application import (
    MediaApplicationCode,
    MediaApplicationError,
    MediaApplicationService,
    MediaApplicationSnapshot,
)


_SUPPORTED_LANGUAGES = frozenset({"en", "uk"})
_RESTORE_FOCUS = "media-restore-position"
_STATUS_FOCUS = "media-sync-status"


class MediaAccessibilityError(ValueError):
    """Invalid presentation composition or presentation-only input."""


def _language(value: object) -> str:
    if type(value) is not str:
        raise MediaAccessibilityError("language must be text")
    selected = value.strip().lower()
    if selected not in _SUPPORTED_LANGUAGES:
        raise MediaAccessibilityError("unsupported media accessibility language")
    return selected


def _format_time(position_ms: int) -> str:
    if type(position_ms) is not int or isinstance(position_ms, bool) or position_ms < 0:
        raise MediaAccessibilityError("media position must be a non-negative integer")
    milliseconds = position_ms % 1000
    total_seconds = position_ms // 1000
    seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
    return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def _copyable_status(qualification: str, position_ms: int, language: str) -> str:
    time_text = _format_time(position_ms)
    if language == "uk":
        messages = {
            "confirmed": f"Позицію шахів підтверджено для часу медіа {time_text}.",
            "ambiguous": "Позиція медіа неоднозначна. Відновлення шахової позиції вимкнено.",
            "candidate": "Є непідтверджені кандидати позиції. Відновлення шахової позиції вимкнено.",
            "unlinked": "Для поточного часу медіа немає синхронізованої шахової позиції.",
        }
    else:
        messages = {
            "confirmed": f"A confirmed chess position is synchronized at media time {time_text}.",
            "ambiguous": "The media position is ambiguous. Chess-position restore is disabled.",
            "candidate": "The media position has unconfirmed candidates. Chess-position restore is disabled.",
            "unlinked": "No chess position is synchronized with the current media time.",
        }
    return messages.get(qualification, messages["unlinked"])


def _restore_label(language: str) -> str:
    return "Відновити позицію медіа" if language == "uk" else "Restore Media Position"


def _restore_description(language: str) -> str:
    if language == "uk":
        return (
            "Відновлює підтверджену шахову позицію, синхронізовану з поточним "
            "часом медіа. Тимчасовий аналіз не використовується як джерело істини."
        )
    return (
        "Restores the confirmed chess position synchronized with the current media "
        "time. Temporary analysis is not used as chess truth."
    )


def _restore_error(code: MediaApplicationCode | None, language: str) -> str:
    if language == "uk":
        if code is MediaApplicationCode.AMBIGUOUS_POSITION:
            return "Позиція медіа неоднозначна. Нічого не відновлено."
        if code is MediaApplicationCode.NO_CONFIRMED_POSITION:
            return "Для поточного часу медіа немає підтвердженої позиції. Нічого не відновлено."
        return (
            "Не вдалося підтвердити результат відновлення позиції медіа. "
            "Перевірте поточну шахову дошку перед продовженням."
        )
    if code is MediaApplicationCode.AMBIGUOUS_POSITION:
        return "The media position is ambiguous. Nothing was restored."
    if code is MediaApplicationCode.NO_CONFIRMED_POSITION:
        return "There is no confirmed position at the current media time. Nothing was restored."
    return (
        "The Restore Media Position result could not be confirmed. "
        "Check the current chess board before continuing."
    )


def _snapshot_failure(language: str) -> dict[str, Any]:
    message = (
        "Не вдалося безпечно прочитати стан синхронізації медіа."
        if language == "uk"
        else "The media synchronization state could not be read safely."
    )
    return {
        "ok": False,
        "revision": None,
        "positionMs": None,
        "positionText": "",
        "qualification": "unavailable",
        "restoreEnabled": False,
        "restoreLabel": _restore_label(language),
        "restoreDescription": _restore_description(language),
        "statusText": message,
        "announcement": message,
        "focusTarget": _STATUS_FOCUS,
    }


class MediaAccessibilityBridge:
    """Project canonical Media application state without exposing chess refs."""

    def __init__(self, service: MediaApplicationService, *, language: str = "en") -> None:
        if not isinstance(service, MediaApplicationService):
            raise TypeError("service must be MediaApplicationService")
        self._service = service
        self._language = _language(language)

    @property
    def language(self) -> str:
        return self._language

    def set_language(self, language: str) -> dict[str, Any]:
        self._language = _language(language)
        return self.snapshot()

    def _present(self, snapshot: MediaApplicationSnapshot) -> dict[str, Any]:
        if type(snapshot) is not MediaApplicationSnapshot:
            raise MediaAccessibilityError("canonical media snapshot is invalid")
        restore_enabled = snapshot.can_restore is True and snapshot.qualification == "confirmed"
        return {
            "ok": True,
            "revision": snapshot.revision,
            "positionMs": snapshot.position_ms,
            "positionText": _format_time(snapshot.position_ms),
            "qualification": snapshot.qualification,
            "restoreEnabled": restore_enabled,
            "restoreLabel": _restore_label(self._language),
            "restoreDescription": _restore_description(self._language),
            "statusText": _copyable_status(
                snapshot.qualification,
                snapshot.position_ms,
                self._language,
            ),
            "announcement": "",
            "focusTarget": _RESTORE_FOCUS if restore_enabled else _STATUS_FOCUS,
        }

    def snapshot(self) -> dict[str, Any]:
        """Return visible/copyable state with no canonical chess reference."""

        try:
            return self._present(self._service.snapshot())
        except Exception:
            return _snapshot_failure(self._language)

    def restore_position(self) -> dict[str, Any]:
        """Restore the current media position; browser callers provide no chess data."""

        try:
            result = self._service.restore_media_position()
        except MediaApplicationError as exc:
            state = self.snapshot()
            state["ok"] = False
            state["announcement"] = _restore_error(exc.code, self._language)
            state["focusTarget"] = (
                _RESTORE_FOCUS if state.get("restoreEnabled") is True else _STATUS_FOCUS
            )
            return state
        except Exception:
            # The canonical application may have performed an external chess
            # effect before an exception escaped. Never expose private details,
            # and never claim rollback that this presentation layer cannot prove.
            state = self.snapshot()
            state["ok"] = False
            state["announcement"] = _restore_error(None, self._language)
            state["focusTarget"] = (
                _RESTORE_FOCUS if state.get("restoreEnabled") is True else _STATUS_FOCUS
            )
            return state

        state = self.snapshot()
        if state.get("ok") is not True:
            return state
        time_text = _format_time(result.position_ms)
        state["announcement"] = (
            f"Відновлено шахову позицію для часу медіа {time_text}."
            if self._language == "uk"
            else f"Restored the chess position synchronized with media time {time_text}."
        )
        state["focusTarget"] = _RESTORE_FOCUS
        return state


__all__ = ["MediaAccessibilityBridge", "MediaAccessibilityError"]
