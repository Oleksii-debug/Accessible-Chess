from __future__ import annotations

"""Provider-neutral live structured-broadcast ingestion.

The adapter layer deliberately treats PGN as opaque provider evidence. It does
not parse SAN, FEN, UCI, moves, positions, or legality. A caller must inject a
canonical application service that consumes the PGN and returns opaque
``chess_ref`` identities owned by Accessible Chess' existing chess/GameTree
authority.

The module also contains the public Lichess Broadcast stream request contract.
It builds only the documented endpoint; transport, OAuth storage, retries, and
HTTP I/O stay outside this module so they can be bounded and replaced without
creating another chess or networking authority here.
"""

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
from typing import Protocol, runtime_checkable

from .media_core import (
    MediaChessLink,
    MediaEvidence,
    MediaEvidenceField,
    MediaEvidenceKind,
    MediaLinkStatus,
    MediaReconciliationState,
)


LICHESS_BROADCAST_PROVIDER = "lichess"
LICHESS_BROADCAST_REQUIRED_SCOPE = "study:read"
LICHESS_BROADCAST_MEDIA_TYPE = "application/x-chess-pgn"
MAX_BROADCAST_PGN_BYTES = 8 * 1024 * 1024
MAX_BROADCAST_GAMES = 4096
MAX_BROADCAST_IDENTIFIER_CHARS = 512
MAX_BROADCAST_CHECKPOINT_BYTES = 8 * 1024 * 1024
BROADCAST_CHECKPOINT_SCHEMA = 1
DEFAULT_STALE_AFTER_MS = 30_000
DEFAULT_RECONNECT_BASE_MS = 1_000
DEFAULT_RECONNECT_MAX_MS = 30_000


class BroadcastErrorCode(str, Enum):
    INVALID_TEXT = "invalid_text"
    INVALID_ROUND_ID = "invalid_round_id"
    INVALID_TIMESTAMP = "invalid_timestamp"
    INVALID_SEQUENCE = "invalid_sequence"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    SOURCE_MISMATCH = "source_mismatch"
    OUT_OF_ORDER = "out_of_order"
    REVISION_CONFLICT = "revision_conflict"
    CANONICAL_REJECTED = "canonical_rejected"
    INVALID_CANONICAL_RESULT = "invalid_canonical_result"
    DUPLICATE_GAME = "duplicate_game"
    GAME_NOT_FOUND = "game_not_found"
    INVALID_CHECKPOINT = "invalid_checkpoint"


class BroadcastContractError(ValueError):
    """Stable fail-closed error at the live-broadcast application boundary."""

    def __init__(self, message: str, *, code: BroadcastErrorCode) -> None:
        super().__init__(message)
        self.code = BroadcastErrorCode(code)


class BroadcastConnectionState(str, Enum):
    CONNECTED = "connected"
    STALE = "stale"
    DISCONNECTED = "disconnected"


class BroadcastApplyKind(str, Enum):
    APPLIED = "applied"
    NO_CHANGE = "no_change"


def _require_text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise BroadcastContractError(
            f"{field_name} must be non-empty exact text",
            code=BroadcastErrorCode.INVALID_TEXT,
        )
    if "\x00" in value or any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        raise BroadcastContractError(
            f"{field_name} contains unsafe text",
            code=BroadcastErrorCode.INVALID_TEXT,
        )
    return value


def _require_identifier_text(value: object, field_name: str) -> str:
    text = _require_text(value, field_name)
    if len(text) > MAX_BROADCAST_IDENTIFIER_CHARS:
        raise BroadcastContractError(
            f"{field_name} exceeds the identifier safety limit",
            code=BroadcastErrorCode.INVALID_TEXT,
        )
    return text


def _require_nonnegative_int(
    value: object,
    field_name: str,
    *,
    code: BroadcastErrorCode = BroadcastErrorCode.INVALID_TIMESTAMP,
) -> int:
    if type(value) is not int or value < 0:
        raise BroadcastContractError(
            f"{field_name} must be a non-negative exact integer",
            code=code,
        )
    return value


@dataclass(frozen=True, slots=True)
class LichessBroadcastRound:
    """Documented Lichess broadcast-round stream request identity.

    Lichess currently specifies an eight-character ``broadcastRoundId`` and
    the OAuth ``study:read`` scope for this endpoint. This value object performs
    no network access and stores no token.
    """

    round_id: str
    include_clocks: bool = True
    include_comments: bool = True

    def __post_init__(self) -> None:
        round_id = _require_text(self.round_id, "round_id")
        if len(round_id) != 8 or not round_id.isascii() or not round_id.isalnum():
            raise BroadcastContractError(
                "Lichess broadcast round id must be exactly 8 ASCII alphanumeric characters",
                code=BroadcastErrorCode.INVALID_ROUND_ID,
            )
        if type(self.include_clocks) is not bool or type(self.include_comments) is not bool:
            raise BroadcastContractError(
                "Lichess broadcast options must be exact booleans",
                code=BroadcastErrorCode.INVALID_TEXT,
            )

    @property
    def required_oauth_scopes(self) -> tuple[str, ...]:
        return (LICHESS_BROADCAST_REQUIRED_SCOPE,)

    @property
    def expected_media_type(self) -> str:
        return LICHESS_BROADCAST_MEDIA_TYPE

    def stream_url(self) -> str:
        clocks = "true" if self.include_clocks else "false"
        comments = "true" if self.include_comments else "false"
        return (
            "https://lichess.org/api/stream/broadcast/round/"
            f"{self.round_id}.pgn?clocks={clocks}&comments={comments}"
        )


@dataclass(frozen=True, slots=True)
class BroadcastReconnectPolicy:
    """Pure bounded reconnect/rate-limit policy; performs no sleeping or I/O."""

    base_delay_ms: int = DEFAULT_RECONNECT_BASE_MS
    max_delay_ms: int = DEFAULT_RECONNECT_MAX_MS

    def __post_init__(self) -> None:
        base = _require_nonnegative_int(self.base_delay_ms, "base_delay_ms")
        maximum = _require_nonnegative_int(self.max_delay_ms, "max_delay_ms")
        if base == 0 or maximum == 0 or base > maximum:
            raise BroadcastContractError(
                "reconnect delay bounds are invalid",
                code=BroadcastErrorCode.INVALID_TIMESTAMP,
            )

    def delay_ms(self, attempt: int, *, retry_after_ms: int | None = None) -> int:
        number = _require_nonnegative_int(
            attempt,
            "attempt",
            code=BroadcastErrorCode.INVALID_SEQUENCE,
        )
        shift = min(number, 30)
        calculated = min(self.max_delay_ms, self.base_delay_ms * (1 << shift))
        if retry_after_ms is None:
            return calculated
        provider_delay = _require_nonnegative_int(retry_after_ms, "retry_after_ms")
        return min(self.max_delay_ms, max(calculated, provider_delay))


@dataclass(frozen=True, slots=True)
class StructuredBroadcastEnvelope:
    """One complete provider PGN update delivered by a transport/framing layer.

    A Lichess stream sends the full PGN for a game whenever that game changes.
    The lower-level transport must deliver a complete provider update; this
    application layer never tries to infer PGN boundaries from arbitrary HTTP
    byte chunks.
    """

    provider: str
    round_id: str
    source_id: str
    sequence: int
    observed_at_ms: int
    pgn_text: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provider", _require_identifier_text(self.provider, "provider")
        )
        object.__setattr__(
            self, "round_id", _require_identifier_text(self.round_id, "round_id")
        )
        object.__setattr__(
            self, "source_id", _require_identifier_text(self.source_id, "source_id")
        )
        object.__setattr__(
            self,
            "sequence",
            _require_nonnegative_int(
                self.sequence,
                "sequence",
                code=BroadcastErrorCode.INVALID_SEQUENCE,
            ),
        )
        object.__setattr__(
            self,
            "observed_at_ms",
            _require_nonnegative_int(self.observed_at_ms, "observed_at_ms"),
        )
        pgn_text = _require_text(self.pgn_text, "pgn_text")
        if len(pgn_text.encode("utf-8")) > MAX_BROADCAST_PGN_BYTES:
            raise BroadcastContractError(
                f"broadcast PGN exceeds {MAX_BROADCAST_PGN_BYTES} UTF-8 bytes",
                code=BroadcastErrorCode.PAYLOAD_TOO_LARGE,
            )
        object.__setattr__(self, "pgn_text", pgn_text)

    @property
    def payload_sha256(self) -> str:
        return sha256(self.pgn_text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CanonicalBroadcastGame:
    """Canonical application-service result for one provider game.

    ``chess_ref`` and ``canonical_revision`` are opaque. This module never
    opens them or derives chess state from them.
    """

    provider_game_id: str
    chess_ref: str
    canonical_revision: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_game_id",
            _require_identifier_text(self.provider_game_id, "provider_game_id"),
        )
        object.__setattr__(
            self, "chess_ref", _require_identifier_text(self.chess_ref, "chess_ref")
        )
        object.__setattr__(
            self,
            "canonical_revision",
            _require_identifier_text(self.canonical_revision, "canonical_revision"),
        )


@runtime_checkable
class CanonicalBroadcastIngestPort(Protocol):
    """Existing chess/application authority consumed by live media."""

    def ingest_broadcast_pgn(
        self,
        *,
        provider: str,
        round_id: str,
        source_id: str,
        pgn_text: str,
    ) -> tuple[CanonicalBroadcastGame, ...]: ...


@dataclass(frozen=True, slots=True)
class BroadcastApplyResult:
    kind: BroadcastApplyKind
    sequence: int
    observed_at_ms: int
    payload_sha256: str
    changed_game_ids: tuple[str, ...]
    games: tuple[CanonicalBroadcastGame, ...]


class StructuredBroadcastSession:
    """Deterministic state for one selected structured broadcast round."""

    __slots__ = (
        "provider",
        "round_id",
        "source_id",
        "_connection_state",
        "_last_sequence",
        "_last_observed_at_ms",
        "_last_payload_sha256",
        "_games",
    )

    def __init__(self, *, provider: str, round_id: str, source_id: str) -> None:
        self.provider = _require_identifier_text(provider, "provider")
        self.round_id = _require_identifier_text(round_id, "round_id")
        self.source_id = _require_identifier_text(source_id, "source_id")
        self._connection_state = BroadcastConnectionState.DISCONNECTED
        self._last_sequence: int | None = None
        self._last_observed_at_ms: int | None = None
        self._last_payload_sha256: str | None = None
        self._games: dict[str, CanonicalBroadcastGame] = {}

    @property
    def connection_state(self) -> BroadcastConnectionState:
        return self._connection_state

    @property
    def last_sequence(self) -> int | None:
        return self._last_sequence

    @property
    def last_observed_at_ms(self) -> int | None:
        return self._last_observed_at_ms

    @property
    def games(self) -> tuple[CanonicalBroadcastGame, ...]:
        return tuple(self._games[key] for key in sorted(self._games))

    def _validate_envelope_identity(self, envelope: StructuredBroadcastEnvelope) -> None:
        if (
            envelope.provider != self.provider
            or envelope.round_id != self.round_id
            or envelope.source_id != self.source_id
        ):
            raise BroadcastContractError(
                "broadcast update does not match the selected session",
                code=BroadcastErrorCode.SOURCE_MISMATCH,
            )

    @staticmethod
    def _canonical_games(value: object) -> tuple[CanonicalBroadcastGame, ...]:
        if type(value) is not tuple or not value or len(value) > MAX_BROADCAST_GAMES:
            raise BroadcastContractError(
                "canonical broadcast result has an invalid game collection",
                code=BroadcastErrorCode.INVALID_CANONICAL_RESULT,
            )
        seen: set[str] = set()
        result: list[CanonicalBroadcastGame] = []
        for game in value:
            if type(game) is not CanonicalBroadcastGame:
                raise BroadcastContractError(
                    "canonical broadcast result contains an invalid game",
                    code=BroadcastErrorCode.INVALID_CANONICAL_RESULT,
                )
            if game.provider_game_id in seen:
                raise BroadcastContractError(
                    "canonical broadcast result contains a duplicate provider game",
                    code=BroadcastErrorCode.DUPLICATE_GAME,
                )
            seen.add(game.provider_game_id)
            result.append(game)
        return tuple(result)

    def apply(
        self,
        envelope: StructuredBroadcastEnvelope,
        canonical: CanonicalBroadcastIngestPort,
    ) -> BroadcastApplyResult:
        if type(envelope) is not StructuredBroadcastEnvelope:
            raise BroadcastContractError(
                "broadcast update must be a StructuredBroadcastEnvelope",
                code=BroadcastErrorCode.INVALID_CANONICAL_RESULT,
            )
        self._validate_envelope_identity(envelope)

        digest = envelope.payload_sha256
        if self._last_sequence is not None:
            if envelope.sequence < self._last_sequence:
                raise BroadcastContractError(
                    "broadcast update sequence moved backwards",
                    code=BroadcastErrorCode.OUT_OF_ORDER,
                )
            if envelope.sequence == self._last_sequence:
                if digest != self._last_payload_sha256:
                    raise BroadcastContractError(
                        "same broadcast sequence carries different PGN bytes",
                        code=BroadcastErrorCode.REVISION_CONFLICT,
                    )
                if (
                    self._last_observed_at_ms is not None
                    and envelope.observed_at_ms < self._last_observed_at_ms
                ):
                    raise BroadcastContractError(
                        "broadcast observation time moved backwards",
                        code=BroadcastErrorCode.OUT_OF_ORDER,
                    )
                self._last_observed_at_ms = envelope.observed_at_ms
                self._connection_state = BroadcastConnectionState.CONNECTED
                return BroadcastApplyResult(
                    kind=BroadcastApplyKind.NO_CHANGE,
                    sequence=envelope.sequence,
                    observed_at_ms=envelope.observed_at_ms,
                    payload_sha256=digest,
                    changed_game_ids=(),
                    games=self.games,
                )
            if (
                self._last_observed_at_ms is not None
                and envelope.observed_at_ms < self._last_observed_at_ms
            ):
                raise BroadcastContractError(
                    "broadcast observation time moved backwards",
                    code=BroadcastErrorCode.OUT_OF_ORDER,
                )

        try:
            canonical_value = canonical.ingest_broadcast_pgn(
                provider=envelope.provider,
                round_id=envelope.round_id,
                source_id=envelope.source_id,
                pgn_text=envelope.pgn_text,
            )
        except Exception:
            raise BroadcastContractError(
                "canonical chess service rejected the broadcast PGN",
                code=BroadcastErrorCode.CANONICAL_REJECTED,
            ) from None

        canonical_games = self._canonical_games(canonical_value)
        candidate_games = dict(self._games)
        changed: list[str] = []
        for game in canonical_games:
            previous = candidate_games.get(game.provider_game_id)
            if previous != game:
                changed.append(game.provider_game_id)
            candidate_games[game.provider_game_id] = game
        if len(candidate_games) > MAX_BROADCAST_GAMES:
            raise BroadcastContractError(
                "canonical broadcast state exceeds the game-count safety limit",
                code=BroadcastErrorCode.INVALID_CANONICAL_RESULT,
            )

        # A state accepted here must remain serializable by the restart contract.
        # Preflight the exact candidate checkpoint before publishing any state so
        # an adversarial-but-bounded opaque identifier cannot create a session
        # that is valid in memory but impossible to recover after restart.
        try:
            self._checkpoint_json_for_state(
                games=tuple(candidate_games[key] for key in sorted(candidate_games)),
                last_sequence=envelope.sequence,
                last_observed_at_ms=envelope.observed_at_ms,
                last_payload_sha256=digest,
            )
        except BroadcastContractError:
            raise BroadcastContractError(
                "canonical broadcast state exceeds the restart-safety limit",
                code=BroadcastErrorCode.INVALID_CANONICAL_RESULT,
            ) from None

        self._games = candidate_games
        self._last_sequence = envelope.sequence
        self._last_observed_at_ms = envelope.observed_at_ms
        self._last_payload_sha256 = digest
        self._connection_state = BroadcastConnectionState.CONNECTED
        return BroadcastApplyResult(
            kind=BroadcastApplyKind.APPLIED,
            sequence=envelope.sequence,
            observed_at_ms=envelope.observed_at_ms,
            payload_sha256=digest,
            changed_game_ids=tuple(sorted(changed)),
            games=self.games,
        )

    @staticmethod
    def _checkpoint_payload_digest(payload: dict[str, object]) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(b"accessible-chess-broadcast-checkpoint-v1\0" + encoded).hexdigest()

    def _checkpoint_payload_for_state(
        self,
        *,
        games: tuple[CanonicalBroadcastGame, ...],
        last_sequence: int | None,
        last_observed_at_ms: int | None,
        last_payload_sha256: str | None,
    ) -> dict[str, object]:
        return {
            "provider": self.provider,
            "round_id": self.round_id,
            "source_id": self.source_id,
            "last_sequence": last_sequence,
            "last_observed_at_ms": last_observed_at_ms,
            "last_payload_sha256": last_payload_sha256,
            "games": [
                {
                    "provider_game_id": game.provider_game_id,
                    "chess_ref": game.chess_ref,
                    "canonical_revision": game.canonical_revision,
                }
                for game in games
            ],
        }

    @classmethod
    def _checkpoint_json_from_payload(cls, payload: dict[str, object]) -> str:
        checkpoint = {
            "schema": BROADCAST_CHECKPOINT_SCHEMA,
            "payload": payload,
            "payload_sha256": cls._checkpoint_payload_digest(payload),
        }
        text = json.dumps(
            checkpoint,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(text.encode("utf-8")) > MAX_BROADCAST_CHECKPOINT_BYTES:
            raise BroadcastContractError(
                "broadcast checkpoint exceeds the safety limit",
                code=BroadcastErrorCode.INVALID_CHECKPOINT,
            )
        return text

    def _checkpoint_json_for_state(
        self,
        *,
        games: tuple[CanonicalBroadcastGame, ...],
        last_sequence: int | None,
        last_observed_at_ms: int | None,
        last_payload_sha256: str | None,
    ) -> str:
        return self._checkpoint_json_from_payload(
            self._checkpoint_payload_for_state(
                games=games,
                last_sequence=last_sequence,
                last_observed_at_ms=last_observed_at_ms,
                last_payload_sha256=last_payload_sha256,
            )
        )

    def to_checkpoint_json(self) -> str:
        """Return deterministic bounded restart state without claiming connectivity."""

        return self._checkpoint_json_for_state(
            games=self.games,
            last_sequence=self._last_sequence,
            last_observed_at_ms=self._last_observed_at_ms,
            last_payload_sha256=self._last_payload_sha256,
        )

    @classmethod
    def from_checkpoint_json(cls, value: object) -> "StructuredBroadcastSession":
        """Restore monotonic/replay guards; network state always restarts disconnected."""

        if type(value) is not str or not value or "\x00" in value:
            raise BroadcastContractError(
                "broadcast checkpoint must be safe exact JSON text",
                code=BroadcastErrorCode.INVALID_CHECKPOINT,
            )
        if len(value.encode("utf-8")) > MAX_BROADCAST_CHECKPOINT_BYTES:
            raise BroadcastContractError(
                "broadcast checkpoint exceeds the safety limit",
                code=BroadcastErrorCode.INVALID_CHECKPOINT,
            )

        def no_duplicate_keys(pairs):
            result = {}
            for key, item in pairs:
                if key in result:
                    raise BroadcastContractError(
                        "broadcast checkpoint contains duplicate keys",
                        code=BroadcastErrorCode.INVALID_CHECKPOINT,
                    )
                result[key] = item
            return result

        try:
            checkpoint = json.loads(value, object_pairs_hook=no_duplicate_keys)
        except BroadcastContractError:
            raise
        except Exception:
            raise BroadcastContractError(
                "broadcast checkpoint JSON is invalid",
                code=BroadcastErrorCode.INVALID_CHECKPOINT,
            ) from None

        if type(checkpoint) is not dict or set(checkpoint) != {
            "schema",
            "payload",
            "payload_sha256",
        }:
            raise BroadcastContractError(
                "broadcast checkpoint shape is invalid",
                code=BroadcastErrorCode.INVALID_CHECKPOINT,
            )
        if checkpoint["schema"] != BROADCAST_CHECKPOINT_SCHEMA:
            raise BroadcastContractError(
                "broadcast checkpoint schema is unsupported",
                code=BroadcastErrorCode.INVALID_CHECKPOINT,
            )
        payload = checkpoint["payload"]
        digest = checkpoint["payload_sha256"]
        if type(payload) is not dict or set(payload) != {
            "provider",
            "round_id",
            "source_id",
            "last_sequence",
            "last_observed_at_ms",
            "last_payload_sha256",
            "games",
        }:
            raise BroadcastContractError(
                "broadcast checkpoint payload shape is invalid",
                code=BroadcastErrorCode.INVALID_CHECKPOINT,
            )
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or digest != cls._checkpoint_payload_digest(payload)
        ):
            raise BroadcastContractError(
                "broadcast checkpoint integrity check failed",
                code=BroadcastErrorCode.INVALID_CHECKPOINT,
            )

        try:
            session = cls(
                provider=payload["provider"],
                round_id=payload["round_id"],
                source_id=payload["source_id"],
            )
        except Exception:
            raise BroadcastContractError(
                "broadcast checkpoint identity is invalid",
                code=BroadcastErrorCode.INVALID_CHECKPOINT,
            ) from None

        last_sequence = payload["last_sequence"]
        last_observed_at_ms = payload["last_observed_at_ms"]
        last_payload_sha256 = payload["last_payload_sha256"]
        if last_sequence is None:
            if (
                last_observed_at_ms is not None
                or last_payload_sha256 is not None
                or payload["games"] not in ([], ())
            ):
                raise BroadcastContractError(
                    "empty broadcast checkpoint carries applied state",
                    code=BroadcastErrorCode.INVALID_CHECKPOINT,
                )
        else:
            try:
                last_sequence = _require_nonnegative_int(
                    last_sequence,
                    "last_sequence",
                    code=BroadcastErrorCode.INVALID_CHECKPOINT,
                )
                last_observed_at_ms = _require_nonnegative_int(
                    last_observed_at_ms,
                    "last_observed_at_ms",
                    code=BroadcastErrorCode.INVALID_CHECKPOINT,
                )
            except BroadcastContractError:
                raise
            if (
                type(last_payload_sha256) is not str
                or len(last_payload_sha256) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in last_payload_sha256
                )
            ):
                raise BroadcastContractError(
                    "broadcast checkpoint payload digest is invalid",
                    code=BroadcastErrorCode.INVALID_CHECKPOINT,
                )

        games_raw = payload["games"]
        if type(games_raw) is not list or len(games_raw) > MAX_BROADCAST_GAMES:
            raise BroadcastContractError(
                "broadcast checkpoint game collection is invalid",
                code=BroadcastErrorCode.INVALID_CHECKPOINT,
            )
        games: dict[str, CanonicalBroadcastGame] = {}
        for item in games_raw:
            if type(item) is not dict or set(item) != {
                "provider_game_id",
                "chess_ref",
                "canonical_revision",
            }:
                raise BroadcastContractError(
                    "broadcast checkpoint game entry is invalid",
                    code=BroadcastErrorCode.INVALID_CHECKPOINT,
                )
            try:
                game = CanonicalBroadcastGame(
                    provider_game_id=item["provider_game_id"],
                    chess_ref=item["chess_ref"],
                    canonical_revision=item["canonical_revision"],
                )
            except Exception:
                raise BroadcastContractError(
                    "broadcast checkpoint canonical game is invalid",
                    code=BroadcastErrorCode.INVALID_CHECKPOINT,
                ) from None
            if game.provider_game_id in games:
                raise BroadcastContractError(
                    "broadcast checkpoint repeats a provider game",
                    code=BroadcastErrorCode.INVALID_CHECKPOINT,
                )
            games[game.provider_game_id] = game

        if last_sequence is not None and not games:
            raise BroadcastContractError(
                "applied broadcast checkpoint has no canonical games",
                code=BroadcastErrorCode.INVALID_CHECKPOINT,
            )

        session._last_sequence = last_sequence
        session._last_observed_at_ms = last_observed_at_ms
        session._last_payload_sha256 = last_payload_sha256
        session._games = games
        session._connection_state = BroadcastConnectionState.DISCONNECTED
        return session


    def media_evidence_for_game(
        self,
        provider_game_id: str,
        *,
        timestamp_ms: int,
    ) -> MediaEvidence:
        """Return typed provider evidence without promoting it to chess truth."""

        game_id = _require_text(provider_game_id, "provider_game_id")
        timestamp = _require_nonnegative_int(timestamp_ms, "timestamp_ms")
        game = self._games.get(game_id)
        if game is None:
            raise BroadcastContractError(
                "broadcast game is not available",
                code=BroadcastErrorCode.GAME_NOT_FOUND,
            )
        if self._last_sequence is None or self._last_payload_sha256 is None:
            raise BroadcastContractError(
                "broadcast evidence requires an applied provider revision",
                code=BroadcastErrorCode.INVALID_CANONICAL_RESULT,
            )
        source_revision = (
            f"sequence:{self._last_sequence}:sha256:{self._last_payload_sha256}"
        )
        evidence_id = (
            f"structured:{self.provider}:{self.round_id}:{game.provider_game_id}:"
            f"{self._last_sequence}:{self._last_payload_sha256[:16]}"
        )
        return MediaEvidence(
            evidence_id=evidence_id,
            source_id=self.source_id,
            kind=MediaEvidenceKind.STRUCTURED_CHESS,
            start_ms=timestamp,
            end_ms=timestamp,
            fields=(
                MediaEvidenceField("provider_game_id", game.provider_game_id),
                MediaEvidenceField(
                    "payload_sha256",
                    self._last_payload_sha256,
                ),
            ),
            confidence=1.0,
            source_authoritative=True,
            source_revision=source_revision,
            provider_id=self.provider,
            producer_revision="structured-broadcast-v1",
            provenance=(
                f"structured broadcast round {self.round_id}; "
                "canonical chess acceptance remains application-owned"
            ),
            raw_candidate_ref=game.provider_game_id,
        )

    def media_link_for_game(
        self,
        provider_game_id: str,
        *,
        timestamp_ms: int,
    ) -> MediaChessLink:
        """Project verified structured truth into Media Core without parsing chess.

        The caller chooses the media-clock timestamp. The chess reference comes
        only from the injected canonical service and is therefore confirmed
        evidence rather than an inferred provider/vision guess.
        """

        game_id = _require_text(provider_game_id, "provider_game_id")
        timestamp = _require_nonnegative_int(timestamp_ms, "timestamp_ms")
        game = self._games.get(game_id)
        if game is None:
            raise BroadcastContractError(
                "broadcast game is not available",
                code=BroadcastErrorCode.GAME_NOT_FOUND,
            )
        evidence = self.media_evidence_for_game(
            game_id,
            timestamp_ms=timestamp,
        )
        return MediaChessLink(
            source_id=self.source_id,
            timestamp_ms=timestamp,
            chess_ref=game.chess_ref,
            status=MediaLinkStatus.CONFIRMED,
            confidence=1.0,
            evidence=evidence.evidence_id,
            qualification=MediaReconciliationState.VERIFIED,
            evidence_ids=(evidence.evidence_id,),
        )

    def mark_disconnected(self) -> BroadcastConnectionState:
        self._connection_state = BroadcastConnectionState.DISCONNECTED
        return self._connection_state

    def refresh_staleness(
        self,
        now_ms: int,
        *,
        stale_after_ms: int = DEFAULT_STALE_AFTER_MS,
    ) -> BroadcastConnectionState:
        now = _require_nonnegative_int(now_ms, "now_ms")
        threshold = _require_nonnegative_int(stale_after_ms, "stale_after_ms")
        if self._connection_state is BroadcastConnectionState.DISCONNECTED:
            return self._connection_state
        if self._last_observed_at_ms is None:
            self._connection_state = BroadcastConnectionState.STALE
            return self._connection_state
        if now < self._last_observed_at_ms:
            raise BroadcastContractError(
                "staleness clock moved backwards",
                code=BroadcastErrorCode.OUT_OF_ORDER,
            )
        self._connection_state = (
            BroadcastConnectionState.STALE
            if now - self._last_observed_at_ms > threshold
            else BroadcastConnectionState.CONNECTED
        )
        return self._connection_state
