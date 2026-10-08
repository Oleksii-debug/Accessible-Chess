from __future__ import annotations

"""Privacy-bounded server-authoritative player directory and social graph.

This module deliberately does *not* own authentication, local profile persistence,
multiplayer game/challenge state, clocks, chess legality, classroom membership, or
network transport. It models only public/discoverable directory data and friendship
state received from an authoritative service, plus idempotent client intents.
"""

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping


PLAYER_DIRECTORY_SCHEMA_VERSION = 1
MAX_DIRECTORY_PLAYERS = 5_000
MAX_FRIEND_RELATIONSHIPS = 10_000
MAX_SEARCH_RESULTS = 100
MAX_DISPLAY_NAME = 80
MAX_TITLE = 32
MAX_QUERY = 80
MAX_WIRE_BYTES = 2_000_000
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
_COUNTRY_RE = re.compile(r"^[A-Za-z]{2}$")


class PlayerDirectoryContractError(ValueError):
    """Stable failure for malformed, stale, or contradictory directory data."""


class DirectoryPresenceState(str, Enum):
    """Public discoverability state, not a transport/session connection state."""

    OFFLINE = "offline"
    AVAILABLE = "available"
    AWAY = "away"
    BUSY = "busy"
    IN_GAME = "in_game"


class FriendshipState(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    REMOVED = "removed"
    BLOCKED = "blocked"


class FriendIntentKind(str, Enum):
    ACCEPT = "accept"
    DECLINE = "decline"
    CANCEL = "cancel"
    REMOVE = "remove"
    BLOCK = "block"
    UNBLOCK = "unblock"


_TERMINAL_FRIENDSHIP_STATES = {
    FriendshipState.DECLINED,
    FriendshipState.CANCELLED,
    FriendshipState.REMOVED,
}
_ALLOWED_FRIENDSHIP_TRANSITIONS: dict[FriendshipState, frozenset[FriendshipState]] = {
    FriendshipState.PENDING: frozenset(
        {
            FriendshipState.ACCEPTED,
            FriendshipState.DECLINED,
            FriendshipState.CANCELLED,
            FriendshipState.BLOCKED,
        }
    ),
    FriendshipState.ACCEPTED: frozenset(
        {FriendshipState.REMOVED, FriendshipState.BLOCKED}
    ),
    FriendshipState.BLOCKED: frozenset({FriendshipState.REMOVED}),
    FriendshipState.DECLINED: frozenset(),
    FriendshipState.CANCELLED: frozenset(),
    FriendshipState.REMOVED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class PlayerDirectoryEntry:
    player_id: str
    display_name: str
    revision: int = 0
    country_code: str | None = None
    language_tag: str | None = None
    fide_rating: int | None = None
    national_rating: int | None = None
    app_rating: int | None = None
    chess_title: str | None = None
    version: int = PLAYER_DIRECTORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _version(self.version)
        player_id = _id(self.player_id, "player id")
        display_name = _text(
            self.display_name,
            "display name",
            max_len=MAX_DISPLAY_NAME,
        )
        revision = _non_negative_int(self.revision, "player revision")
        country = _country(self.country_code)
        language = _language(self.language_tag)
        fide = _rating(self.fide_rating, "FIDE rating", maximum=4_000)
        national = _rating(self.national_rating, "national rating", maximum=4_000)
        app = _rating(self.app_rating, "application rating", maximum=10_000)
        title = _optional_text(self.chess_title, "chess title", max_len=MAX_TITLE)
        object.__setattr__(self, "player_id", player_id)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "country_code", country)
        object.__setattr__(self, "language_tag", language)
        object.__setattr__(self, "fide_rating", fide)
        object.__setattr__(self, "national_rating", national)
        object.__setattr__(self, "app_rating", app)
        object.__setattr__(self, "chess_title", title)
        object.__setattr__(self, "version", PLAYER_DIRECTORY_SCHEMA_VERSION)

    def to_record(self) -> dict[str, object]:
        return {
            "version": self.version,
            "player_id": self.player_id,
            "display_name": self.display_name,
            "revision": self.revision,
            "country_code": self.country_code,
            "language_tag": self.language_tag,
            "fide_rating": self.fide_rating,
            "national_rating": self.national_rating,
            "app_rating": self.app_rating,
            "chess_title": self.chess_title,
        }

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "PlayerDirectoryEntry":
        data = _mapping(value, "player directory entry")
        _exact_keys(
            data,
            {
                "version",
                "player_id",
                "display_name",
                "revision",
                "country_code",
                "language_tag",
                "fide_rating",
                "national_rating",
                "app_rating",
                "chess_title",
            },
            "player directory entry",
        )
        return cls(**data)


@dataclass(frozen=True, slots=True)
class DirectoryPresenceSnapshot:
    player_id: str
    state: DirectoryPresenceState = DirectoryPresenceState.OFFLINE
    revision: int = 0
    version: int = PLAYER_DIRECTORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _version(self.version)
        player_id = _id(self.player_id, "presence player id")
        revision = _non_negative_int(self.revision, "presence revision")
        try:
            state = DirectoryPresenceState(self.state)
        except (TypeError, ValueError) as exc:
            raise PlayerDirectoryContractError("unsupported directory presence state") from exc
        object.__setattr__(self, "player_id", player_id)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "version", PLAYER_DIRECTORY_SCHEMA_VERSION)

    def to_record(self) -> dict[str, object]:
        return {
            "version": self.version,
            "player_id": self.player_id,
            "state": self.state.value,
            "revision": self.revision,
        }

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "DirectoryPresenceSnapshot":
        data = _mapping(value, "directory presence snapshot")
        _exact_keys(
            data,
            {"version", "player_id", "state", "revision"},
            "directory presence snapshot",
        )
        return cls(**data)


@dataclass(frozen=True, slots=True)
class PlayerDirectorySnapshot:
    revision: int
    players: tuple[PlayerDirectoryEntry, ...] = ()
    presences: tuple[DirectoryPresenceSnapshot, ...] = ()
    version: int = PLAYER_DIRECTORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _version(self.version)
        revision = _non_negative_int(self.revision, "directory revision")
        players = _typed_tuple(
            self.players,
            PlayerDirectoryEntry,
            "directory players",
            max_items=MAX_DIRECTORY_PLAYERS,
        )
        presences = _typed_tuple(
            self.presences,
            DirectoryPresenceSnapshot,
            "directory presences",
            max_items=MAX_DIRECTORY_PLAYERS,
        )
        player_ids = _unique_by(players, lambda value: value.player_id, "player id")
        presence_ids = _unique_by(
            presences, lambda value: value.player_id, "presence player id"
        )
        unknown = presence_ids.difference(player_ids)
        if unknown:
            raise PlayerDirectoryContractError(
                "directory presence references a player outside the snapshot"
            )
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "players", players)
        object.__setattr__(self, "presences", presences)
        object.__setattr__(self, "version", PLAYER_DIRECTORY_SCHEMA_VERSION)
        _wire_size(self.to_record(), "player directory snapshot")

    def player(self, player_id: str) -> PlayerDirectoryEntry | None:
        key = _id(player_id, "player id")
        return next((entry for entry in self.players if entry.player_id == key), None)

    def presence(self, player_id: str) -> DirectoryPresenceSnapshot:
        key = _id(player_id, "player id")
        if self.player(key) is None:
            raise PlayerDirectoryContractError("player is outside the directory snapshot")
        found = next((item for item in self.presences if item.player_id == key), None)
        return found or DirectoryPresenceSnapshot(player_id=key)

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
        country_code: str | None = None,
        language_tag: str | None = None,
        exclude_player_ids: tuple[str, ...] = (),
    ) -> tuple[PlayerDirectoryEntry, ...]:
        if not isinstance(query, str):
            raise TypeError("directory search query must be text")
        normalized_query = query.strip().casefold()
        if len(normalized_query) > MAX_QUERY:
            raise PlayerDirectoryContractError("directory search query is too long")
        if type(limit) is not int or not 1 <= limit <= MAX_SEARCH_RESULTS:
            raise PlayerDirectoryContractError(
                f"directory search limit must be in 1..{MAX_SEARCH_RESULTS}"
            )
        country = _country(country_code)
        language = _language(language_tag)
        excluded = {_id(value, "excluded player id") for value in exclude_player_ids}

        matches: list[PlayerDirectoryEntry] = []
        for entry in self.players:
            if entry.player_id in excluded:
                continue
            if country is not None and entry.country_code != country:
                continue
            if language is not None and entry.language_tag != language:
                continue
            searchable = " ".join(
                value
                for value in (
                    entry.display_name,
                    entry.chess_title,
                    entry.country_code,
                    entry.language_tag,
                )
                if value
            ).casefold()
            if normalized_query and normalized_query not in searchable:
                continue
            matches.append(entry)
        matches.sort(key=lambda entry: (entry.display_name.casefold(), entry.player_id))
        return tuple(matches[:limit])

    def to_record(self) -> dict[str, object]:
        return {
            "version": self.version,
            "revision": self.revision,
            "players": [entry.to_record() for entry in self.players],
            "presences": [presence.to_record() for presence in self.presences],
        }

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "PlayerDirectorySnapshot":
        data = _mapping(value, "player directory snapshot")
        _exact_keys(
            data,
            {"version", "revision", "players", "presences"},
            "player directory snapshot",
        )
        players_raw = _record_list(data["players"], "directory players")
        presences_raw = _record_list(data["presences"], "directory presences")
        return cls(
            version=data["version"],
            revision=data["revision"],
            players=tuple(PlayerDirectoryEntry.from_record(item) for item in players_raw),
            presences=tuple(
                DirectoryPresenceSnapshot.from_record(item) for item in presences_raw
            ),
        )


class PlayerDirectorySnapshotTracker:
    """Keep only monotonic server snapshots; never synthesize directory truth."""

    def __init__(self, initial: PlayerDirectorySnapshot | None = None) -> None:
        if initial is not None and not isinstance(initial, PlayerDirectorySnapshot):
            raise PlayerDirectoryContractError("initial directory snapshot must be typed")
        self._snapshot = initial

    @property
    def snapshot(self) -> PlayerDirectorySnapshot | None:
        return self._snapshot

    def apply(self, incoming: PlayerDirectorySnapshot) -> bool:
        if not isinstance(incoming, PlayerDirectorySnapshot):
            raise PlayerDirectoryContractError("incoming directory snapshot must be typed")
        current = self._snapshot
        if current is None:
            self._snapshot = incoming
            return True
        if incoming.revision < current.revision:
            raise PlayerDirectoryContractError("stale player directory snapshot")
        if incoming.revision == current.revision:
            if incoming == current:
                return False
            raise PlayerDirectoryContractError(
                "conflicting player directory snapshot at same revision"
            )
        old_players = {entry.player_id: entry for entry in current.players}
        for entry in incoming.players:
            prior = old_players.get(entry.player_id)
            if prior is not None and entry.revision < prior.revision:
                raise PlayerDirectoryContractError("player entry revision regressed")
        old_presence = {item.player_id: item for item in current.presences}
        for presence in incoming.presences:
            prior = old_presence.get(presence.player_id)
            if prior is not None and presence.revision < prior.revision:
                raise PlayerDirectoryContractError("directory presence revision regressed")
        self._snapshot = incoming
        return True


@dataclass(frozen=True, slots=True)
class FriendshipSnapshot:
    relation_id: str
    requester_id: str
    addressee_id: str
    revision: int = 0
    state: FriendshipState = FriendshipState.PENDING
    blocked_by_id: str | None = None
    version: int = PLAYER_DIRECTORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _version(self.version)
        relation_id = _id(self.relation_id, "friend relation id")
        requester = _id(self.requester_id, "friend requester id")
        addressee = _id(self.addressee_id, "friend addressee id")
        if requester == addressee:
            raise PlayerDirectoryContractError("friendship participants must be distinct")
        revision = _non_negative_int(self.revision, "friendship revision")
        try:
            state = FriendshipState(self.state)
        except (TypeError, ValueError) as exc:
            raise PlayerDirectoryContractError("unsupported friendship state") from exc
        blocked_by = (
            None
            if self.blocked_by_id is None
            else _id(self.blocked_by_id, "friendship blocker id")
        )
        if state is FriendshipState.BLOCKED:
            if blocked_by not in {requester, addressee}:
                raise PlayerDirectoryContractError(
                    "blocked friendship must identify one participating blocker"
                )
        elif blocked_by is not None:
            raise PlayerDirectoryContractError(
                "blocked_by_id is only valid for blocked friendships"
            )
        object.__setattr__(self, "relation_id", relation_id)
        object.__setattr__(self, "requester_id", requester)
        object.__setattr__(self, "addressee_id", addressee)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "blocked_by_id", blocked_by)
        object.__setattr__(self, "version", PLAYER_DIRECTORY_SCHEMA_VERSION)

    def participants(self) -> frozenset[str]:
        return frozenset((self.requester_id, self.addressee_id))

    def to_record(self) -> dict[str, object]:
        return {
            "version": self.version,
            "relation_id": self.relation_id,
            "requester_id": self.requester_id,
            "addressee_id": self.addressee_id,
            "revision": self.revision,
            "state": self.state.value,
            "blocked_by_id": self.blocked_by_id,
        }

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "FriendshipSnapshot":
        data = _mapping(value, "friendship snapshot")
        _exact_keys(
            data,
            {
                "version",
                "relation_id",
                "requester_id",
                "addressee_id",
                "revision",
                "state",
                "blocked_by_id",
            },
            "friendship snapshot",
        )
        return cls(**data)


@dataclass(frozen=True, slots=True)
class FriendRequestIntent:
    """Idempotent request to create a new server-issued friendship relation."""

    requester_id: str
    addressee_id: str
    client_nonce: str
    version: int = PLAYER_DIRECTORY_SCHEMA_VERSION
    intent_id: str = field(init=False)

    def __post_init__(self) -> None:
        _version(self.version)
        requester = _id(self.requester_id, "friend requester id")
        addressee = _id(self.addressee_id, "friend addressee id")
        nonce = _id(self.client_nonce, "friend request client nonce")
        if requester == addressee:
            raise PlayerDirectoryContractError("friend request participants must be distinct")
        canonical = {
            "version": PLAYER_DIRECTORY_SCHEMA_VERSION,
            "requester_id": requester,
            "addressee_id": addressee,
            "client_nonce": nonce,
        }
        object.__setattr__(self, "requester_id", requester)
        object.__setattr__(self, "addressee_id", addressee)
        object.__setattr__(self, "client_nonce", nonce)
        object.__setattr__(self, "version", PLAYER_DIRECTORY_SCHEMA_VERSION)
        object.__setattr__(self, "intent_id", _digest(canonical))


@dataclass(frozen=True, slots=True)
class FriendRelationIntent:
    relation_id: str
    actor_id: str
    expected_revision: int
    kind: FriendIntentKind
    version: int = PLAYER_DIRECTORY_SCHEMA_VERSION
    intent_id: str = field(init=False)

    def __post_init__(self) -> None:
        _version(self.version)
        relation_id = _id(self.relation_id, "friend relation id")
        actor_id = _id(self.actor_id, "friend intent actor id")
        revision = _non_negative_int(self.expected_revision, "expected friendship revision")
        try:
            kind = FriendIntentKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise PlayerDirectoryContractError("unsupported friend intent kind") from exc
        canonical = {
            "version": PLAYER_DIRECTORY_SCHEMA_VERSION,
            "relation_id": relation_id,
            "actor_id": actor_id,
            "expected_revision": revision,
            "kind": kind.value,
        }
        object.__setattr__(self, "relation_id", relation_id)
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "expected_revision", revision)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "version", PLAYER_DIRECTORY_SCHEMA_VERSION)
        object.__setattr__(self, "intent_id", _digest(canonical))


def validate_friend_intent(
    snapshot: FriendshipSnapshot,
    intent: FriendRelationIntent,
) -> None:
    if not isinstance(snapshot, FriendshipSnapshot) or not isinstance(
        intent, FriendRelationIntent
    ):
        raise PlayerDirectoryContractError("friend intent validation requires typed values")
    if snapshot.relation_id != intent.relation_id:
        raise PlayerDirectoryContractError("friend intent targets a different relation")
    if snapshot.revision != intent.expected_revision:
        raise PlayerDirectoryContractError("friend intent is stale")
    if intent.actor_id not in snapshot.participants():
        raise PlayerDirectoryContractError("friend intent actor is not a participant")

    state = snapshot.state
    kind = intent.kind
    if kind in {FriendIntentKind.ACCEPT, FriendIntentKind.DECLINE}:
        if state is not FriendshipState.PENDING or intent.actor_id != snapshot.addressee_id:
            raise PlayerDirectoryContractError(
                "only the pending request addressee may accept or decline"
            )
        return
    if kind is FriendIntentKind.CANCEL:
        if state is not FriendshipState.PENDING or intent.actor_id != snapshot.requester_id:
            raise PlayerDirectoryContractError(
                "only the pending request sender may cancel"
            )
        return
    if kind is FriendIntentKind.REMOVE:
        if state not in {FriendshipState.ACCEPTED, FriendshipState.BLOCKED}:
            raise PlayerDirectoryContractError(
                "only accepted or blocked relationships may be removed"
            )
        return
    if kind is FriendIntentKind.BLOCK:
        if state not in {FriendshipState.PENDING, FriendshipState.ACCEPTED}:
            raise PlayerDirectoryContractError(
                "only pending or accepted relationships may be blocked"
            )
        return
    if kind is FriendIntentKind.UNBLOCK:
        if (
            state is not FriendshipState.BLOCKED
            or snapshot.blocked_by_id != intent.actor_id
        ):
            raise PlayerDirectoryContractError(
                "only the participant who blocked the relationship may unblock"
            )
        return
    raise PlayerDirectoryContractError("unsupported friend intent")


class FriendshipSnapshotTracker:
    """Apply monotonic server snapshots with fail-closed transition checks."""

    def __init__(self, initial: FriendshipSnapshot | None = None) -> None:
        if initial is not None and not isinstance(initial, FriendshipSnapshot):
            raise PlayerDirectoryContractError("initial friendship snapshot must be typed")
        self._snapshot = initial

    @property
    def snapshot(self) -> FriendshipSnapshot | None:
        return self._snapshot

    def apply(self, incoming: FriendshipSnapshot) -> bool:
        if not isinstance(incoming, FriendshipSnapshot):
            raise PlayerDirectoryContractError("incoming friendship snapshot must be typed")
        current = self._snapshot
        if current is None:
            self._snapshot = incoming
            return True
        if incoming.relation_id != current.relation_id:
            raise PlayerDirectoryContractError(
                "friendship snapshot belongs to a different relation"
            )
        if incoming.participants() != current.participants():
            raise PlayerDirectoryContractError("friendship participants changed")
        if incoming.requester_id != current.requester_id:
            raise PlayerDirectoryContractError("friendship request direction changed")
        if incoming.revision < current.revision:
            raise PlayerDirectoryContractError("stale friendship snapshot")
        if incoming.revision == current.revision:
            if incoming == current:
                return False
            raise PlayerDirectoryContractError(
                "conflicting friendship snapshot at same revision"
            )
        if incoming.state is current.state:
            raise PlayerDirectoryContractError(
                "friendship revision advanced without a state transition"
            )
        if current.state in _TERMINAL_FRIENDSHIP_STATES:
            raise PlayerDirectoryContractError("terminal friendship cannot transition")
        if incoming.state not in _ALLOWED_FRIENDSHIP_TRANSITIONS[current.state]:
            raise PlayerDirectoryContractError("invalid friendship state transition")
        if incoming.revision != current.revision + 1:
            raise PlayerDirectoryContractError("friendship revision must advance by one")
        self._snapshot = incoming
        return True


@dataclass(frozen=True, slots=True)
class FriendListSnapshot:
    owner_id: str
    revision: int
    relationships: tuple[FriendshipSnapshot, ...] = ()
    version: int = PLAYER_DIRECTORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _version(self.version)
        owner_id = _id(self.owner_id, "friend-list owner id")
        revision = _non_negative_int(self.revision, "friend-list revision")
        relationships = _typed_tuple(
            self.relationships,
            FriendshipSnapshot,
            "friend relationships",
            max_items=MAX_FRIEND_RELATIONSHIPS,
        )
        _unique_by(
            relationships, lambda value: value.relation_id, "friend relation id"
        )
        pairs: set[frozenset[str]] = set()
        for relation in relationships:
            if owner_id not in relation.participants():
                raise PlayerDirectoryContractError(
                    "friend list contains a relationship that does not involve its owner"
                )
            pair = relation.participants()
            if pair in pairs:
                raise PlayerDirectoryContractError(
                    "friend list contains duplicate participant pair"
                )
            pairs.add(pair)
        object.__setattr__(self, "owner_id", owner_id)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "relationships", relationships)
        object.__setattr__(self, "version", PLAYER_DIRECTORY_SCHEMA_VERSION)
        _wire_size(self.to_record(), "friend list snapshot")

    def accepted_friend_ids(self) -> tuple[str, ...]:
        ids: list[str] = []
        for relation in self.relationships:
            if relation.state is not FriendshipState.ACCEPTED:
                continue
            other = (
                relation.addressee_id
                if relation.requester_id == self.owner_id
                else relation.requester_id
            )
            ids.append(other)
        return tuple(sorted(ids))

    def to_record(self) -> dict[str, object]:
        return {
            "version": self.version,
            "owner_id": self.owner_id,
            "revision": self.revision,
            "relationships": [item.to_record() for item in self.relationships],
        }

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "FriendListSnapshot":
        data = _mapping(value, "friend list snapshot")
        _exact_keys(
            data,
            {"version", "owner_id", "revision", "relationships"},
            "friend list snapshot",
        )
        relationships = _record_list(data["relationships"], "friend relationships")
        return cls(
            version=data["version"],
            owner_id=data["owner_id"],
            revision=data["revision"],
            relationships=tuple(FriendshipSnapshot.from_record(item) for item in relationships),
        )


class FriendListSnapshotTracker:
    """Keep an owner-scoped friend list monotonic across reconnect/sync."""

    def __init__(self, initial: FriendListSnapshot | None = None) -> None:
        if initial is not None and not isinstance(initial, FriendListSnapshot):
            raise PlayerDirectoryContractError("initial friend list snapshot must be typed")
        self._snapshot = initial

    @property
    def snapshot(self) -> FriendListSnapshot | None:
        return self._snapshot

    def apply(self, incoming: FriendListSnapshot) -> bool:
        if not isinstance(incoming, FriendListSnapshot):
            raise PlayerDirectoryContractError("incoming friend list snapshot must be typed")
        current = self._snapshot
        if current is None:
            self._snapshot = incoming
            return True
        if incoming.owner_id != current.owner_id:
            raise PlayerDirectoryContractError("friend list belongs to a different owner")
        if incoming.revision < current.revision:
            raise PlayerDirectoryContractError("stale friend list snapshot")
        if incoming.revision == current.revision:
            if incoming == current:
                return False
            raise PlayerDirectoryContractError("conflicting friend list snapshot at same revision")
        old = {relation.relation_id: relation for relation in current.relationships}
        for relation in incoming.relationships:
            prior = old.get(relation.relation_id)
            if prior is None:
                continue
            if relation.participants() != prior.participants() or relation.requester_id != prior.requester_id:
                raise PlayerDirectoryContractError("friend relation identity changed in friend list")
            if relation.revision < prior.revision:
                raise PlayerDirectoryContractError("friend relation revision regressed in friend list")
        self._snapshot = incoming
        return True


def _version(value: object) -> int:
    if type(value) is not int or value != PLAYER_DIRECTORY_SCHEMA_VERSION:
        raise PlayerDirectoryContractError("unsupported player-directory schema version")
    return value


def _id(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise PlayerDirectoryContractError(f"{label} must be text")
    text = value.strip().lower()
    if text != value or _ID_RE.fullmatch(text) is None:
        raise PlayerDirectoryContractError(f"{label} must be a canonical stable id")
    return text


def _text(value: object, label: str, *, max_len: int) -> str:
    if not isinstance(value, str):
        raise PlayerDirectoryContractError(f"{label} must be text")
    if value != value.strip() or not value or len(value) > max_len:
        raise PlayerDirectoryContractError(f"{label} is not canonical bounded text")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise PlayerDirectoryContractError(f"{label} contains control characters")
    return value


def _optional_text(value: object, label: str, *, max_len: int) -> str | None:
    if value is None:
        return None
    return _text(value, label, max_len=max_len)


def _country(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _COUNTRY_RE.fullmatch(value) is None:
        raise PlayerDirectoryContractError("country code must be a two-letter code")
    return value.upper()


def _language(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _LANGUAGE_RE.fullmatch(value) is None:
        raise PlayerDirectoryContractError("language tag must be a bounded BCP47-like tag")
    parts = value.split("-")
    return "-".join([parts[0].lower(), *parts[1:]])


def _rating(value: object, label: str, *, maximum: int) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= maximum:
        raise PlayerDirectoryContractError(f"{label} must be an integer in 0..{maximum}")
    return value


def _non_negative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0 or value > (1 << 53) - 1:
        raise PlayerDirectoryContractError(f"{label} must be a non-negative safe integer")
    return value


def _typed_tuple(
    values: object,
    expected_type: type,
    label: str,
    *,
    max_items: int,
) -> tuple[Any, ...]:
    if not isinstance(values, tuple):
        raise PlayerDirectoryContractError(f"{label} must be a tuple")
    if len(values) > max_items:
        raise PlayerDirectoryContractError(f"{label} exceeds item limit")
    if any(not isinstance(value, expected_type) for value in values):
        raise PlayerDirectoryContractError(f"{label} contains an invalid value")
    return values


def _unique_by(values: tuple[Any, ...], key, label: str) -> set[Any]:
    found: set[Any] = set()
    for value in values:
        current = key(value)
        if current in found:
            raise PlayerDirectoryContractError(f"duplicate {label}")
        found.add(current)
    return found


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PlayerDirectoryContractError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise PlayerDirectoryContractError(f"{label} keys must be text")
    return dict(value)


def _record_list(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise PlayerDirectoryContractError(f"{label} must be an array")
    if any(not isinstance(item, Mapping) for item in value):
        raise PlayerDirectoryContractError(f"{label} must contain objects")
    return value


def _exact_keys(data: Mapping[str, Any], expected: set[str], label: str) -> None:
    keys = set(data)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        detail = []
        if missing:
            detail.append("missing=" + ",".join(missing))
        if extra:
            detail.append("extra=" + ",".join(extra))
        raise PlayerDirectoryContractError(
            f"{label} has invalid fields ({'; '.join(detail)})"
        )


def _wire_size(record: Mapping[str, object], label: str) -> None:
    encoded = json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded) > MAX_WIRE_BYTES:
        raise PlayerDirectoryContractError(f"{label} exceeds wire-size limit")


def _digest(record: Mapping[str, object]) -> str:
    encoded = json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
