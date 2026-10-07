from __future__ import annotations

"""Accessible live orchestration above the canonical structured-broadcast boundary.

This module owns provider request metadata, explicit game selection, media-clock
offset mapping and bounded navigation across canonical live revisions. It never
parses PGN or derives chess legality. All chess references come from
``CanonicalBroadcastGame`` values already validated by the injected canonical
application authority in :mod:`acs.structured_broadcast`.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from .structured_broadcast import (
    BroadcastApplyResult,
    BroadcastConnectionState,
    BroadcastContractError,
    BroadcastErrorCode,
    BroadcastReconnectPolicy,
    CanonicalBroadcastGame,
    LICHESS_BROADCAST_PROVIDER,
    LichessBroadcastRound,
)

MAX_CLOCK_OFFSET_MS = 24 * 60 * 60 * 1000
MAX_LIVE_POSITION_HISTORY = 512


class LiveSelectionState(str, Enum):
    NONE = "none"
    SELECTED = "selected"
    AMBIGUOUS = "ambiguous"


class LiveEventKind(str, Enum):
    CONNECTION = "connection"
    SELECTION = "selection"
    POSITION = "position"
    NAVIGATION = "navigation"


class LiveBroadcastErrorCode(str, Enum):
    INVALID_OFFSET = "invalid_offset"
    INVALID_NAVIGATION = "invalid_navigation"
    HISTORY_EMPTY = "history_empty"


class LiveBroadcastError(ValueError):
    def __init__(self, message: str, *, code: LiveBroadcastErrorCode) -> None:
        super().__init__(message)
        self.code = LiveBroadcastErrorCode(code)


def _exact_text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise TypeError(f"{name} must be non-empty exact text")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ValueError(f"{name} contains unsafe text")
    return value


def _nonnegative_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise TypeError(f"{name} must be a non-negative exact integer")
    return value


@dataclass(frozen=True, slots=True)
class BroadcastStreamRequest:
    provider: str
    url: str
    expected_media_type: str
    oauth_scopes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _exact_text(self.provider, "provider"))
        object.__setattr__(self, "url", _exact_text(self.url, "url"))
        object.__setattr__(
            self,
            "expected_media_type",
            _exact_text(self.expected_media_type, "expected_media_type"),
        )
        if type(self.oauth_scopes) is not tuple or any(
            type(scope) is not str or not scope.strip() for scope in self.oauth_scopes
        ):
            raise TypeError("oauth_scopes must be an exact tuple of text scopes")


@runtime_checkable
class StructuredBroadcastProvider(Protocol):
    """Provider seam consumed by a bounded transport owned outside chess logic."""

    @property
    def provider_name(self) -> str: ...

    def stream_request(self) -> BroadcastStreamRequest: ...

    def reconnect_delay_ms(
        self, attempt: int, *, retry_after_ms: int | None = None
    ) -> int: ...


@dataclass(frozen=True, slots=True)
class LichessStructuredBroadcastProvider:
    round: LichessBroadcastRound
    reconnect_policy: BroadcastReconnectPolicy = BroadcastReconnectPolicy()

    def __post_init__(self) -> None:
        if type(self.round) is not LichessBroadcastRound:
            raise TypeError("round must be an exact LichessBroadcastRound")
        if type(self.reconnect_policy) is not BroadcastReconnectPolicy:
            raise TypeError("reconnect_policy must be an exact BroadcastReconnectPolicy")

    @property
    def provider_name(self) -> str:
        return LICHESS_BROADCAST_PROVIDER

    def stream_request(self) -> BroadcastStreamRequest:
        return BroadcastStreamRequest(
            provider=self.provider_name,
            url=self.round.stream_url(),
            expected_media_type=self.round.expected_media_type,
            oauth_scopes=self.round.required_oauth_scopes,
        )

    def reconnect_delay_ms(
        self, attempt: int, *, retry_after_ms: int | None = None
    ) -> int:
        return self.reconnect_policy.delay_ms(attempt, retry_after_ms=retry_after_ms)


@dataclass(frozen=True, slots=True)
class LiveGameSelection:
    state: LiveSelectionState
    selected_game_id: str | None
    available_game_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        try:
            state = LiveSelectionState(self.state)
        except (TypeError, ValueError) as exc:
            raise TypeError("state must be a LiveSelectionState") from exc
        object.__setattr__(self, "state", state)
        if type(self.available_game_ids) is not tuple or any(
            type(game_id) is not str or not game_id.strip()
            for game_id in self.available_game_ids
        ):
            raise TypeError("available_game_ids must be an exact tuple of text ids")
        if len(set(self.available_game_ids)) != len(self.available_game_ids):
            raise ValueError("available_game_ids cannot contain duplicates")
        selected = self.selected_game_id
        if state is LiveSelectionState.SELECTED:
            selected = _exact_text(selected, "selected_game_id")
            if selected not in self.available_game_ids:
                raise ValueError("selected_game_id must be available")
        elif selected is not None:
            raise ValueError("only selected state may carry selected_game_id")

    @property
    def ambiguous(self) -> bool:
        return self.state is LiveSelectionState.AMBIGUOUS


def resolve_game_selection(
    games: tuple[CanonicalBroadcastGame, ...],
    requested_game_id: str | None = None,
) -> LiveGameSelection:
    if type(games) is not tuple or any(type(game) is not CanonicalBroadcastGame for game in games):
        raise TypeError("games must be an exact tuple of CanonicalBroadcastGame values")
    ids = tuple(sorted(game.provider_game_id for game in games))
    if len(set(ids)) != len(ids):
        raise BroadcastContractError(
            "live broadcast games contain duplicate provider identities",
            code=BroadcastErrorCode.DUPLICATE_GAME,
        )
    if requested_game_id is not None:
        game_id = _exact_text(requested_game_id, "requested_game_id")
        if game_id not in ids:
            raise BroadcastContractError(
                "requested live broadcast game is not available",
                code=BroadcastErrorCode.GAME_NOT_FOUND,
            )
        return LiveGameSelection(LiveSelectionState.SELECTED, game_id, ids)
    if not ids:
        return LiveGameSelection(LiveSelectionState.NONE, None, ())
    if len(ids) == 1:
        return LiveGameSelection(LiveSelectionState.SELECTED, ids[0], ids)
    return LiveGameSelection(LiveSelectionState.AMBIGUOUS, None, ids)


@dataclass(frozen=True, slots=True)
class MediaClockOffset:
    """Signed mapping where media_time = structured_time + offset_ms."""

    offset_ms: int = 0

    def __post_init__(self) -> None:
        if type(self.offset_ms) is not int or abs(self.offset_ms) > MAX_CLOCK_OFFSET_MS:
            raise LiveBroadcastError(
                f"media clock offset must be an exact integer within +/-{MAX_CLOCK_OFFSET_MS} ms",
                code=LiveBroadcastErrorCode.INVALID_OFFSET,
            )

    def media_time_ms(self, structured_time_ms: int) -> int:
        timestamp = _nonnegative_int(structured_time_ms, "structured_time_ms")
        result = timestamp + self.offset_ms
        if result < 0:
            raise LiveBroadcastError(
                "media clock mapping would be negative",
                code=LiveBroadcastErrorCode.INVALID_OFFSET,
            )
        return result

    def structured_time_ms(self, media_time_ms: int) -> int:
        timestamp = _nonnegative_int(media_time_ms, "media_time_ms")
        result = timestamp - self.offset_ms
        if result < 0:
            raise LiveBroadcastError(
                "structured clock mapping would be negative",
                code=LiveBroadcastErrorCode.INVALID_OFFSET,
            )
        return result


@dataclass(frozen=True, slots=True)
class LivePositionRevision:
    provider_game_id: str
    chess_ref: str
    canonical_revision: str
    sequence: int
    observed_at_ms: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_game_id",
            _exact_text(self.provider_game_id, "provider_game_id"),
        )
        object.__setattr__(self, "chess_ref", _exact_text(self.chess_ref, "chess_ref"))
        object.__setattr__(
            self,
            "canonical_revision",
            _exact_text(self.canonical_revision, "canonical_revision"),
        )
        object.__setattr__(self, "sequence", _nonnegative_int(self.sequence, "sequence"))
        object.__setattr__(
            self,
            "observed_at_ms",
            _nonnegative_int(self.observed_at_ms, "observed_at_ms"),
        )


class LivePositionHistory:
    """Bounded current/previous/next navigation without stealing the live cursor."""

    __slots__ = (
        "provider_game_id",
        "_items",
        "_cursor",
        "_follow_live",
        "_truncated",
        "_last_sequence",
        "_last_observed_at_ms",
    )

    def __init__(self, provider_game_id: str) -> None:
        self.provider_game_id = _exact_text(provider_game_id, "provider_game_id")
        self._items: list[LivePositionRevision] = []
        self._cursor = -1
        self._follow_live = True
        self._truncated = False
        self._last_sequence: int | None = None
        self._last_observed_at_ms: int | None = None

    @property
    def items(self) -> tuple[LivePositionRevision, ...]:
        return tuple(self._items)

    @property
    def current(self) -> LivePositionRevision | None:
        if self._cursor < 0:
            return None
        return self._items[self._cursor]

    @property
    def follow_live(self) -> bool:
        return self._follow_live

    @property
    def history_truncated(self) -> bool:
        return self._truncated

    def record(self, result: BroadcastApplyResult) -> bool:
        if type(result) is not BroadcastApplyResult:
            raise TypeError("result must be an exact BroadcastApplyResult")
        sequence = _nonnegative_int(result.sequence, "result.sequence")
        observed_at_ms = _nonnegative_int(result.observed_at_ms, "result.observed_at_ms")
        if type(result.games) is not tuple or any(
            type(game) is not CanonicalBroadcastGame for game in result.games
        ):
            raise TypeError("result.games must contain exact canonical game values")
        game_ids = tuple(game.provider_game_id for game in result.games)
        if len(set(game_ids)) != len(game_ids):
            raise BroadcastContractError(
                "live result contains duplicate provider identities",
                code=BroadcastErrorCode.DUPLICATE_GAME,
            )
        game = next(
            (game for game in result.games if game.provider_game_id == self.provider_game_id),
            None,
        )
        if game is None:
            return False

        if self._last_sequence is not None:
            assert self._last_observed_at_ms is not None
            if sequence < self._last_sequence or observed_at_ms < self._last_observed_at_ms:
                raise BroadcastContractError(
                    "live position history moved backwards",
                    code=BroadcastErrorCode.OUT_OF_ORDER,
                )
            if sequence == self._last_sequence:
                latest = self._items[-1]
                if (
                    latest.canonical_revision != game.canonical_revision
                    or latest.chess_ref != game.chess_ref
                ):
                    raise BroadcastContractError(
                        "one live sequence maps to conflicting canonical state",
                        code=BroadcastErrorCode.REVISION_CONFLICT,
                    )
                self._last_observed_at_ms = observed_at_ms
                return False

        if self._items:
            latest = self._items[-1]
            if latest.canonical_revision == game.canonical_revision:
                if latest.chess_ref != game.chess_ref:
                    raise BroadcastContractError(
                        "one canonical revision maps to conflicting chess references",
                        code=BroadcastErrorCode.REVISION_CONFLICT,
                    )
                self._last_sequence = sequence
                self._last_observed_at_ms = observed_at_ms
                return False

        revision = LivePositionRevision(
            provider_game_id=game.provider_game_id,
            chess_ref=game.chess_ref,
            canonical_revision=game.canonical_revision,
            sequence=sequence,
            observed_at_ms=observed_at_ms,
        )
        was_following = self._follow_live or self._cursor < 0
        self._items.append(revision)
        if len(self._items) > MAX_LIVE_POSITION_HISTORY:
            if not was_following and self._cursor == 0:
                # Keep the exact position the user is reading. Drop the next
                # oldest item instead of silently moving the browse cursor.
                self._items.pop(1)
            else:
                self._items.pop(0)
                if self._cursor > 0:
                    self._cursor -= 1
            self._truncated = True
        if was_following:
            self._cursor = len(self._items) - 1
            self._follow_live = True
        self._last_sequence = sequence
        self._last_observed_at_ms = observed_at_ms
        return True

    def previous(self) -> LivePositionRevision:
        if not self._items:
            raise LiveBroadcastError("live position history is empty", code=LiveBroadcastErrorCode.HISTORY_EMPTY)
        if self._cursor <= 0:
            raise LiveBroadcastError("already at oldest retained live position", code=LiveBroadcastErrorCode.INVALID_NAVIGATION)
        self._cursor -= 1
        self._follow_live = False
        return self._items[self._cursor]

    def next(self) -> LivePositionRevision:
        if not self._items:
            raise LiveBroadcastError("live position history is empty", code=LiveBroadcastErrorCode.HISTORY_EMPTY)
        if self._cursor >= len(self._items) - 1:
            raise LiveBroadcastError("already at latest live position", code=LiveBroadcastErrorCode.INVALID_NAVIGATION)
        self._cursor += 1
        self._follow_live = self._cursor == len(self._items) - 1
        return self._items[self._cursor]

    def jump_to_live(self) -> LivePositionRevision:
        if not self._items:
            raise LiveBroadcastError("live position history is empty", code=LiveBroadcastErrorCode.HISTORY_EMPTY)
        self._cursor = len(self._items) - 1
        self._follow_live = True
        return self._items[self._cursor]


@dataclass(frozen=True, slots=True)
class AccessibleLiveEvent:
    """One status string shared by visible/copyable UI and screen-reader output."""

    kind: LiveEventKind
    visible_text: str
    announcement_text: str

    def __post_init__(self) -> None:
        try:
            kind = LiveEventKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise TypeError("kind must be a LiveEventKind") from exc
        object.__setattr__(self, "kind", kind)
        visible = _exact_text(self.visible_text, "visible_text")
        announcement = _exact_text(self.announcement_text, "announcement_text")
        if visible != announcement:
            raise ValueError("live event text must remain visible and announcement-equivalent")


def connection_event(state: BroadcastConnectionState) -> AccessibleLiveEvent:
    if type(state) is not BroadcastConnectionState:
        raise TypeError("state must be an exact BroadcastConnectionState")
    text = {
        BroadcastConnectionState.CONNECTED: "Live broadcast connected.",
        BroadcastConnectionState.STALE: "Live broadcast is stale; waiting for updates.",
        BroadcastConnectionState.DISCONNECTED: "Live broadcast disconnected.",
    }[state]
    return AccessibleLiveEvent(LiveEventKind.CONNECTION, text, text)


def selection_event(selection: LiveGameSelection) -> AccessibleLiveEvent:
    if type(selection) is not LiveGameSelection:
        raise TypeError("selection must be an exact LiveGameSelection")
    if selection.state is LiveSelectionState.NONE:
        text = "No live broadcast games are available."
    elif selection.state is LiveSelectionState.AMBIGUOUS:
        text = f"Multiple live games are available: {len(selection.available_game_ids)}. Select a game."
    else:
        text = f"Live game selected: {selection.selected_game_id}."
    return AccessibleLiveEvent(LiveEventKind.SELECTION, text, text)


def position_event(revision: LivePositionRevision) -> AccessibleLiveEvent:
    if type(revision) is not LivePositionRevision:
        raise TypeError("revision must be an exact LivePositionRevision")
    text = f"Live position updated for game {revision.provider_game_id}."
    return AccessibleLiveEvent(LiveEventKind.POSITION, text, text)


def navigation_event(history: LivePositionHistory) -> AccessibleLiveEvent:
    if type(history) is not LivePositionHistory or history.current is None:
        raise LiveBroadcastError("live position history is empty", code=LiveBroadcastErrorCode.HISTORY_EMPTY)
    index = history.items.index(history.current) + 1
    suffix = " Following live." if history.follow_live else " Browsing earlier live position."
    truncation = " Older live history was truncated." if history.history_truncated else ""
    text = f"Live position {index} of {len(history.items)}.{suffix}{truncation}"
    return AccessibleLiveEvent(LiveEventKind.NAVIGATION, text, text)
