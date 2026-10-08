from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .clock_service import ClockSnapshot, ClockState, TimeControl
from .game_lifecycle import EndReason, GameOutcome, GameStatus, LifecycleSnapshot


MULTIPLAYER_SCHEMA_VERSION = 1
MAX_WIRE_BYTES = 128_000
MAX_TEXT = 128
MAX_MOVE_TEXT = 32
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_REVISION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class MultiplayerContractError(ValueError):
    """Stable contract error for multiplayer coordination data."""


class ChallengeState(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ChallengeIntentKind(str, Enum):
    ACCEPT = "accept"
    DECLINE = "decline"
    CANCEL = "cancel"


class PresenceState(str, Enum):
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    DISCONNECTED = "disconnected"


class GameIntentKind(str, Enum):
    MOVE = "move"
    OFFER_DRAW = "offer_draw"
    ACCEPT_DRAW = "accept_draw"
    DECLINE_DRAW = "decline_draw"
    RESIGN = "resign"
    REQUEST_REMATCH = "request_rematch"
    ACCEPT_REMATCH = "accept_rematch"
    RECONNECT = "reconnect"
    REQUEST_SYNC = "request_sync"


@dataclass(frozen=True)
class ChallengeSnapshot:
    challenge_id: str
    challenger_id: str
    opponent_id: str
    time_control: TimeControl
    revision: int = 0
    state: ChallengeState = ChallengeState.PENDING
    version: int = MULTIPLAYER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _version(self.version)
        challenge_id = _id(self.challenge_id, "challenge id")
        challenger_id = _id(self.challenger_id, "challenger id")
        opponent_id = _id(self.opponent_id, "opponent id")
        if challenger_id == opponent_id:
            raise MultiplayerContractError("challenge participants must be distinct")
        if not isinstance(self.time_control, TimeControl):
            raise MultiplayerContractError("challenge time_control must be TimeControl")
        revision = _non_negative_int(self.revision, "challenge revision")
        try:
            state = ChallengeState(self.state)
        except (TypeError, ValueError) as exc:
            raise MultiplayerContractError("unsupported challenge state") from exc
        object.__setattr__(self, "challenge_id", challenge_id)
        object.__setattr__(self, "challenger_id", challenger_id)
        object.__setattr__(self, "opponent_id", opponent_id)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "version", MULTIPLAYER_SCHEMA_VERSION)

    def to_record(self) -> dict[str, object]:
        return {
            "version": self.version,
            "challenge_id": self.challenge_id,
            "challenger_id": self.challenger_id,
            "opponent_id": self.opponent_id,
            "time_control": _time_control_record(self.time_control),
            "revision": self.revision,
            "state": self.state.value,
        }

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "ChallengeSnapshot":
        data = _mapping(value, "challenge snapshot")
        _exact_keys(
            data,
            {
                "version",
                "challenge_id",
                "challenger_id",
                "opponent_id",
                "time_control",
                "revision",
                "state",
            },
            "challenge snapshot",
        )
        return cls(
            version=data["version"],
            challenge_id=data["challenge_id"],
            challenger_id=data["challenger_id"],
            opponent_id=data["opponent_id"],
            time_control=_time_control_from_record(data["time_control"]),
            revision=data["revision"],
            state=data["state"],
        )


@dataclass(frozen=True)
class ChallengeIntent:
    challenge_id: str
    actor_id: str
    expected_revision: int
    kind: ChallengeIntentKind
    version: int = MULTIPLAYER_SCHEMA_VERSION
    intent_id: str = field(init=False)

    def __post_init__(self) -> None:
        _version(self.version)
        challenge_id = _id(self.challenge_id, "challenge id")
        actor_id = _id(self.actor_id, "actor id")
        revision = _non_negative_int(self.expected_revision, "expected challenge revision")
        try:
            kind = ChallengeIntentKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise MultiplayerContractError("unsupported challenge intent") from exc
        canonical = {
            "version": MULTIPLAYER_SCHEMA_VERSION,
            "challenge_id": challenge_id,
            "actor_id": actor_id,
            "expected_revision": revision,
            "kind": kind.value,
        }
        object.__setattr__(self, "challenge_id", challenge_id)
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "expected_revision", revision)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "version", MULTIPLAYER_SCHEMA_VERSION)
        object.__setattr__(self, "intent_id", _digest(canonical))

    def to_record(self) -> dict[str, object]:
        return {
            "version": self.version,
            "intent_id": self.intent_id,
            "challenge_id": self.challenge_id,
            "actor_id": self.actor_id,
            "expected_revision": self.expected_revision,
            "kind": self.kind.value,
        }

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "ChallengeIntent":
        data = _mapping(value, "challenge intent")
        _exact_keys(
            data,
            {"version", "intent_id", "challenge_id", "actor_id", "expected_revision", "kind"},
            "challenge intent",
        )
        supplied = _digest_text(data["intent_id"])
        intent = cls(
            version=data["version"],
            challenge_id=data["challenge_id"],
            actor_id=data["actor_id"],
            expected_revision=data["expected_revision"],
            kind=data["kind"],
        )
        if supplied != intent.intent_id:
            raise MultiplayerContractError("challenge intent id does not match content")
        return intent


def validate_challenge_intent(
    snapshot: ChallengeSnapshot,
    intent: ChallengeIntent,
) -> None:
    if not isinstance(snapshot, ChallengeSnapshot) or not isinstance(intent, ChallengeIntent):
        raise MultiplayerContractError("challenge validation requires typed values")
    if snapshot.challenge_id != intent.challenge_id:
        raise MultiplayerContractError("challenge intent targets a different challenge")
    if snapshot.revision != intent.expected_revision:
        raise MultiplayerContractError("challenge intent is stale")
    if snapshot.state is not ChallengeState.PENDING:
        raise MultiplayerContractError("challenge is already terminal")
    if intent.kind in {ChallengeIntentKind.ACCEPT, ChallengeIntentKind.DECLINE}:
        if intent.actor_id != snapshot.opponent_id:
            raise MultiplayerContractError("only the challenged opponent may respond")
    elif intent.kind is ChallengeIntentKind.CANCEL:
        if intent.actor_id != snapshot.challenger_id:
            raise MultiplayerContractError("only the challenger may cancel")


class ChallengeSnapshotTracker:
    """Accept server-authoritative challenge snapshots without inventing local truth."""

    def __init__(self, initial: ChallengeSnapshot | None = None) -> None:
        if initial is not None and not isinstance(initial, ChallengeSnapshot):
            raise MultiplayerContractError("initial challenge snapshot must be typed")
        self._snapshot = initial

    @property
    def snapshot(self) -> ChallengeSnapshot | None:
        return self._snapshot

    def apply(self, incoming: ChallengeSnapshot) -> bool:
        if not isinstance(incoming, ChallengeSnapshot):
            raise MultiplayerContractError("incoming challenge snapshot must be typed")
        current = self._snapshot
        if current is None:
            self._snapshot = incoming
            return True
        if incoming.challenge_id != current.challenge_id:
            raise MultiplayerContractError("challenge snapshot belongs to a different challenge")
        _assert_challenge_identity_stable(current, incoming)
        if incoming.revision < current.revision:
            raise MultiplayerContractError("stale challenge snapshot")
        if incoming.revision == current.revision:
            if incoming == current:
                return False
            raise MultiplayerContractError("conflicting challenge snapshot at same revision")
        if current.state is not ChallengeState.PENDING:
            raise MultiplayerContractError("terminal challenge cannot transition")
        if incoming.state is ChallengeState.PENDING:
            raise MultiplayerContractError("challenge revision advanced without a state transition")
        self._snapshot = incoming
        return True


@dataclass(frozen=True)
class MultiplayerGameSnapshot:
    game_id: str
    sequence: int
    white_player_id: str
    black_player_id: str
    time_control: TimeControl
    position_revision: str
    side_to_move: str
    clock: ClockSnapshot
    lifecycle: LifecycleSnapshot
    white_presence: PresenceState = PresenceState.CONNECTED
    black_presence: PresenceState = PresenceState.CONNECTED
    rematch_of: str | None = None
    rematch_requested_by: str | None = None
    version: int = MULTIPLAYER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _version(self.version)
        game_id = _id(self.game_id, "game id")
        white = _id(self.white_player_id, "white player id")
        black = _id(self.black_player_id, "black player id")
        if white == black:
            raise MultiplayerContractError("multiplayer players must be distinct")
        sequence = _non_negative_int(self.sequence, "server sequence")
        position_revision = _position_revision(self.position_revision)
        side = _side(self.side_to_move)
        if not isinstance(self.time_control, TimeControl):
            raise MultiplayerContractError("game time_control must be TimeControl")
        if not isinstance(self.clock, ClockSnapshot):
            raise MultiplayerContractError("game clock must be ClockSnapshot")
        if not isinstance(self.lifecycle, LifecycleSnapshot):
            raise MultiplayerContractError("game lifecycle must be LifecycleSnapshot")
        try:
            white_presence = PresenceState(self.white_presence)
            black_presence = PresenceState(self.black_presence)
        except (TypeError, ValueError) as exc:
            raise MultiplayerContractError("unsupported player presence state") from exc
        rematch_of = None if self.rematch_of is None else _id(self.rematch_of, "rematch game id")
        if rematch_of == game_id:
            raise MultiplayerContractError("game cannot be a rematch of itself")
        rematch_requested_by = (
            None
            if self.rematch_requested_by is None
            else _id(self.rematch_requested_by, "rematch requester id")
        )
        if rematch_requested_by is not None:
            if rematch_requested_by not in {white, black}:
                raise MultiplayerContractError("rematch requester must be one of the players")
            if self.lifecycle.status is not GameStatus.FINISHED:
                raise MultiplayerContractError("active game cannot carry a rematch request")
        _validate_game_clock(self.time_control, side, self.clock, self.lifecycle)
        object.__setattr__(self, "game_id", game_id)
        object.__setattr__(self, "sequence", sequence)
        object.__setattr__(self, "white_player_id", white)
        object.__setattr__(self, "black_player_id", black)
        object.__setattr__(self, "position_revision", position_revision)
        object.__setattr__(self, "side_to_move", side)
        object.__setattr__(self, "white_presence", white_presence)
        object.__setattr__(self, "black_presence", black_presence)
        object.__setattr__(self, "rematch_of", rematch_of)
        object.__setattr__(self, "rematch_requested_by", rematch_requested_by)
        object.__setattr__(self, "version", MULTIPLAYER_SCHEMA_VERSION)

    def side_for(self, participant_id: str) -> str:
        actor = _id(participant_id, "participant id")
        if actor == self.white_player_id:
            return "w"
        if actor == self.black_player_id:
            return "b"
        raise MultiplayerContractError("participant is not a player in this game")

    def to_record(self) -> dict[str, object]:
        return {
            "version": self.version,
            "game_id": self.game_id,
            "sequence": self.sequence,
            "white_player_id": self.white_player_id,
            "black_player_id": self.black_player_id,
            "time_control": _time_control_record(self.time_control),
            "position_revision": self.position_revision,
            "side_to_move": self.side_to_move,
            "clock": _clock_record(self.clock),
            "lifecycle": _lifecycle_record(self.lifecycle),
            "white_presence": self.white_presence.value,
            "black_presence": self.black_presence.value,
            "rematch_of": self.rematch_of,
            "rematch_requested_by": self.rematch_requested_by,
        }

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "MultiplayerGameSnapshot":
        data = _mapping(value, "multiplayer game snapshot")
        _exact_keys(
            data,
            {
                "version",
                "game_id",
                "sequence",
                "white_player_id",
                "black_player_id",
                "time_control",
                "position_revision",
                "side_to_move",
                "clock",
                "lifecycle",
                "white_presence",
                "black_presence",
                "rematch_of",
                "rematch_requested_by",
            },
            "multiplayer game snapshot",
        )
        return cls(
            version=data["version"],
            game_id=data["game_id"],
            sequence=data["sequence"],
            white_player_id=data["white_player_id"],
            black_player_id=data["black_player_id"],
            time_control=_time_control_from_record(data["time_control"]),
            position_revision=data["position_revision"],
            side_to_move=data["side_to_move"],
            clock=_clock_from_record(data["clock"]),
            lifecycle=_lifecycle_from_record(data["lifecycle"]),
            white_presence=data["white_presence"],
            black_presence=data["black_presence"],
            rematch_of=data["rematch_of"],
            rematch_requested_by=data["rematch_requested_by"],
        )


@dataclass(frozen=True)
class GameIntent:
    game_id: str
    actor_id: str
    expected_sequence: int
    kind: GameIntentKind
    move_text: str | None = None
    resume_from_sequence: int | None = None
    version: int = MULTIPLAYER_SCHEMA_VERSION
    intent_id: str = field(init=False)

    def __post_init__(self) -> None:
        _version(self.version)
        game_id = _id(self.game_id, "game id")
        actor_id = _id(self.actor_id, "actor id")
        expected = _non_negative_int(self.expected_sequence, "expected server sequence")
        try:
            kind = GameIntentKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise MultiplayerContractError("unsupported multiplayer game intent") from exc
        move_text = self.move_text
        resume = self.resume_from_sequence
        if kind is GameIntentKind.MOVE:
            if not isinstance(move_text, str) or not move_text.strip():
                raise MultiplayerContractError("move intent requires bounded move text")
            move_text = move_text.strip()
            if len(move_text) > MAX_MOVE_TEXT:
                raise MultiplayerContractError("move text exceeds length limit")
            if any(ord(character) < 32 or ord(character) == 127 for character in move_text):
                raise MultiplayerContractError("move text contains control characters")
            if resume is not None:
                raise MultiplayerContractError("move intent cannot carry reconnect sequence")
        elif kind is GameIntentKind.RECONNECT:
            if move_text is not None:
                raise MultiplayerContractError("reconnect intent cannot carry move text")
            resume = _non_negative_int(resume, "resume sequence")
            if resume > expected:
                raise MultiplayerContractError("resume sequence cannot exceed expected sequence")
        else:
            if move_text is not None or resume is not None:
                raise MultiplayerContractError("intent carries fields that are not valid for its kind")
            move_text = None
        canonical = {
            "version": MULTIPLAYER_SCHEMA_VERSION,
            "game_id": game_id,
            "actor_id": actor_id,
            "expected_sequence": expected,
            "kind": kind.value,
            "move_text": move_text,
            "resume_from_sequence": resume,
        }
        object.__setattr__(self, "game_id", game_id)
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "expected_sequence", expected)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "move_text", move_text)
        object.__setattr__(self, "resume_from_sequence", resume)
        object.__setattr__(self, "version", MULTIPLAYER_SCHEMA_VERSION)
        object.__setattr__(self, "intent_id", _digest(canonical))

    def to_record(self) -> dict[str, object]:
        return {
            "version": self.version,
            "intent_id": self.intent_id,
            "game_id": self.game_id,
            "actor_id": self.actor_id,
            "expected_sequence": self.expected_sequence,
            "kind": self.kind.value,
            "move_text": self.move_text,
            "resume_from_sequence": self.resume_from_sequence,
        }

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "GameIntent":
        data = _mapping(value, "game intent")
        _exact_keys(
            data,
            {
                "version",
                "intent_id",
                "game_id",
                "actor_id",
                "expected_sequence",
                "kind",
                "move_text",
                "resume_from_sequence",
            },
            "game intent",
        )
        supplied = _digest_text(data["intent_id"])
        intent = cls(
            version=data["version"],
            game_id=data["game_id"],
            actor_id=data["actor_id"],
            expected_sequence=data["expected_sequence"],
            kind=data["kind"],
            move_text=data["move_text"],
            resume_from_sequence=data["resume_from_sequence"],
        )
        if supplied != intent.intent_id:
            raise MultiplayerContractError("game intent id does not match content")
        return intent


def validate_game_intent(
    snapshot: MultiplayerGameSnapshot,
    intent: GameIntent,
) -> None:
    if not isinstance(snapshot, MultiplayerGameSnapshot) or not isinstance(intent, GameIntent):
        raise MultiplayerContractError("game intent validation requires typed values")
    if snapshot.game_id != intent.game_id:
        raise MultiplayerContractError("game intent targets a different game")
    if snapshot.sequence != intent.expected_sequence:
        raise MultiplayerContractError("game intent is stale")
    actor_side = snapshot.side_for(intent.actor_id)
    active_only = {
        GameIntentKind.MOVE,
        GameIntentKind.OFFER_DRAW,
        GameIntentKind.ACCEPT_DRAW,
        GameIntentKind.DECLINE_DRAW,
        GameIntentKind.RESIGN,
    }
    if intent.kind in active_only and snapshot.lifecycle.status is not GameStatus.ACTIVE:
        raise MultiplayerContractError("game intent requires an active game")
    if intent.kind is GameIntentKind.MOVE and actor_side != snapshot.side_to_move:
        raise MultiplayerContractError("only the side to move may submit a move")
    if intent.kind in {GameIntentKind.ACCEPT_DRAW, GameIntentKind.DECLINE_DRAW}:
        offered = snapshot.lifecycle.draw_offered_by
        if offered is None:
            raise MultiplayerContractError("there is no pending draw offer")
        if offered == actor_side:
            raise MultiplayerContractError("a player cannot answer their own draw offer")
    if intent.kind is GameIntentKind.OFFER_DRAW and snapshot.lifecycle.draw_offered_by is not None:
        raise MultiplayerContractError("a draw offer is already pending")
    if intent.kind in {GameIntentKind.REQUEST_REMATCH, GameIntentKind.ACCEPT_REMATCH}:
        if snapshot.lifecycle.status is not GameStatus.FINISHED:
            raise MultiplayerContractError("rematch intent requires a finished game")
    if intent.kind is GameIntentKind.REQUEST_REMATCH:
        if snapshot.rematch_requested_by is not None:
            raise MultiplayerContractError("a rematch request is already pending")
    if intent.kind is GameIntentKind.ACCEPT_REMATCH:
        requester = snapshot.rematch_requested_by
        if requester is None:
            raise MultiplayerContractError("there is no pending rematch request")
        if requester == intent.actor_id:
            raise MultiplayerContractError("a player cannot accept their own rematch request")


class MultiplayerSnapshotTracker:
    """Monotonic server-snapshot tracker; canonical Board/GameTree remains external."""

    def __init__(self, initial: MultiplayerGameSnapshot | None = None) -> None:
        if initial is not None and not isinstance(initial, MultiplayerGameSnapshot):
            raise MultiplayerContractError("initial game snapshot must be typed")
        self._snapshot = initial

    @property
    def snapshot(self) -> MultiplayerGameSnapshot | None:
        return self._snapshot

    def apply(self, incoming: MultiplayerGameSnapshot) -> bool:
        if not isinstance(incoming, MultiplayerGameSnapshot):
            raise MultiplayerContractError("incoming game snapshot must be typed")
        current = self._snapshot
        if current is None:
            self._snapshot = incoming
            return True
        if incoming.game_id != current.game_id:
            raise MultiplayerContractError("game snapshot belongs to a different game")
        _assert_game_identity_stable(current, incoming)
        if incoming.sequence < current.sequence:
            raise MultiplayerContractError("stale multiplayer game snapshot")
        if incoming.sequence == current.sequence:
            if incoming == current:
                return False
            raise MultiplayerContractError("conflicting game snapshot at same server sequence")
        self._snapshot = incoming
        return True

    def to_record(self) -> dict[str, object]:
        body: dict[str, object] = {
            "version": MULTIPLAYER_SCHEMA_VERSION,
            "snapshot": None if self._snapshot is None else self._snapshot.to_record(),
        }
        body["digest"] = _digest(body)
        return body

    def to_json(self) -> str:
        text = _json(self.to_record())
        if len(text.encode("utf-8")) > MAX_WIRE_BYTES:
            raise MultiplayerContractError("multiplayer recovery record exceeds size limit")
        return text

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "MultiplayerSnapshotTracker":
        data = _mapping(value, "multiplayer recovery record")
        _exact_keys(data, {"version", "snapshot", "digest"}, "multiplayer recovery record")
        _version(data["version"])
        supplied = _digest_text(data["digest"])
        unsigned = {"version": data["version"], "snapshot": data["snapshot"]}
        if supplied != _digest(unsigned):
            raise MultiplayerContractError("multiplayer recovery digest mismatch")
        raw = data["snapshot"]
        return cls(None if raw is None else MultiplayerGameSnapshot.from_record(raw))

    @classmethod
    def from_json(cls, text: str) -> "MultiplayerSnapshotTracker":
        if not isinstance(text, str):
            raise MultiplayerContractError("multiplayer recovery JSON must be text")
        if len(text.encode("utf-8")) > MAX_WIRE_BYTES:
            raise MultiplayerContractError("multiplayer recovery record exceeds size limit")
        try:
            value = json.loads(
                text,
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=_reject_constant,
                parse_int=_parse_int,
            )
        except json.JSONDecodeError as exc:
            raise MultiplayerContractError("invalid multiplayer recovery JSON") from exc
        except RecursionError as exc:
            raise MultiplayerContractError("multiplayer recovery JSON exceeds nesting limit") from exc
        return cls.from_record(value)


def _assert_challenge_identity_stable(
    current: ChallengeSnapshot,
    incoming: ChallengeSnapshot,
) -> None:
    if (
        incoming.challenger_id != current.challenger_id
        or incoming.opponent_id != current.opponent_id
        or incoming.time_control != current.time_control
    ):
        raise MultiplayerContractError("challenge identity changed across server revisions")


def _assert_game_identity_stable(
    current: MultiplayerGameSnapshot,
    incoming: MultiplayerGameSnapshot,
) -> None:
    if (
        incoming.white_player_id != current.white_player_id
        or incoming.black_player_id != current.black_player_id
        or incoming.time_control != current.time_control
        or incoming.rematch_of != current.rematch_of
    ):
        raise MultiplayerContractError("game identity changed across server snapshots")
    if current.lifecycle.status is GameStatus.FINISHED and incoming.lifecycle.status is GameStatus.ACTIVE:
        raise MultiplayerContractError("finished game cannot return to active state")


def _validate_game_clock(
    control: TimeControl,
    side_to_move: str,
    clock: ClockSnapshot,
    lifecycle: LifecycleSnapshot,
) -> None:
    if control.untimed:
        if clock != ClockSnapshot(0, 0, None, ClockState.STOPPED):
            raise MultiplayerContractError("untimed multiplayer game requires stopped zero clock")
    elif lifecycle.status is GameStatus.ACTIVE:
        if clock.state not in {ClockState.RUNNING, ClockState.PAUSED}:
            raise MultiplayerContractError("active timed multiplayer game requires active clock")
        if clock.active != side_to_move:
            raise MultiplayerContractError("active clock must match server side to move")
    elif clock.state in {ClockState.RUNNING, ClockState.PAUSED}:
        raise MultiplayerContractError("finished multiplayer game cannot carry active clock")
    if lifecycle.status is GameStatus.ACTIVE and clock.flagged is not None:
        raise MultiplayerContractError("active multiplayer lifecycle cannot carry flagged clock")


def _time_control_record(control: TimeControl) -> dict[str, int]:
    return {"initial_ms": control.initial_ms, "increment_ms": control.increment_ms}


def _time_control_from_record(value: object) -> TimeControl:
    data = _mapping(value, "time control")
    _exact_keys(data, {"initial_ms", "increment_ms"}, "time control")
    try:
        return TimeControl(data["initial_ms"], data["increment_ms"])
    except (TypeError, ValueError) as exc:
        raise MultiplayerContractError("invalid time control") from exc


def _clock_record(snapshot: ClockSnapshot) -> dict[str, object]:
    return {
        "white_ms": snapshot.white_ms,
        "black_ms": snapshot.black_ms,
        "active": snapshot.active,
        "state": snapshot.state.value,
        "flagged": snapshot.flagged,
    }


def _clock_from_record(value: object) -> ClockSnapshot:
    data = _mapping(value, "clock snapshot")
    _exact_keys(data, {"white_ms", "black_ms", "active", "state", "flagged"}, "clock snapshot")
    try:
        state = ClockState(data["state"])
        return ClockSnapshot(
            white_ms=data["white_ms"],
            black_ms=data["black_ms"],
            active=data["active"],
            state=state,
            flagged=data["flagged"],
        )
    except (TypeError, ValueError) as exc:
        raise MultiplayerContractError("invalid clock snapshot") from exc


def _lifecycle_record(snapshot: LifecycleSnapshot) -> dict[str, object]:
    outcome = snapshot.outcome
    return {
        "status": snapshot.status.value,
        "outcome": None
        if outcome is None
        else {
            "result": outcome.result,
            "reason": outcome.reason.value,
            "winner": outcome.winner,
        },
        "draw_offered_by": snapshot.draw_offered_by,
        "takeback_requested_by": snapshot.takeback_requested_by,
    }


def _lifecycle_from_record(value: object) -> LifecycleSnapshot:
    data = _mapping(value, "lifecycle snapshot")
    _exact_keys(
        data,
        {"status", "outcome", "draw_offered_by", "takeback_requested_by"},
        "lifecycle snapshot",
    )
    try:
        status = GameStatus(data["status"])
        raw_outcome = data["outcome"]
        outcome = None
        if raw_outcome is not None:
            item = _mapping(raw_outcome, "game outcome")
            _exact_keys(item, {"result", "reason", "winner"}, "game outcome")
            outcome = GameOutcome(
                result=item["result"],
                reason=EndReason(item["reason"]),
                winner=item["winner"],
            )
        return LifecycleSnapshot(
            status=status,
            outcome=outcome,
            draw_offered_by=data["draw_offered_by"],
            takeback_requested_by=data["takeback_requested_by"],
        )
    except (TypeError, ValueError) as exc:
        raise MultiplayerContractError("invalid lifecycle snapshot") from exc


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MultiplayerContractError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise MultiplayerContractError(f"{label} keys must be text")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise MultiplayerContractError(f"{label} schema mismatch")


def _id(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise MultiplayerContractError(f"{label} must be a bounded opaque identifier")
    text = value.strip().lower()
    if not _ID_RE.fullmatch(text):
        raise MultiplayerContractError(f"{label} must be a bounded opaque identifier")
    return text


def _position_revision(value: object) -> str:
    if not isinstance(value, str):
        raise MultiplayerContractError("position revision must be bounded opaque text")
    text = value.strip()
    if not _REVISION_RE.fullmatch(text):
        raise MultiplayerContractError("position revision must be bounded opaque text")
    return text


def _side(value: object) -> str:
    if value not in {"w", "b"}:
        raise MultiplayerContractError("side_to_move must be 'w' or 'b'")
    return value


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 2**63 - 1:
        raise MultiplayerContractError(f"{label} must be a bounded non-negative integer")
    return value


def _version(value: object) -> int:
    if type(value) is not int or value != MULTIPLAYER_SCHEMA_VERSION:
        raise MultiplayerContractError("unsupported multiplayer schema version")
    return value


def _digest_text(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise MultiplayerContractError("digest must be canonical SHA-256 hex")
    return value


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MultiplayerContractError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise MultiplayerContractError("non-finite JSON constants are not allowed")


def _parse_int(value: str) -> int:
    if len(value) > 20:
        raise MultiplayerContractError("JSON integer exceeds length limit")
    try:
        return int(value)
    except ValueError as exc:
        raise MultiplayerContractError("invalid JSON integer") from exc
