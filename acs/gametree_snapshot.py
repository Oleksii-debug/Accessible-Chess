from __future__ import annotations

"""Versioned, identity-bound snapshot/restore for the canonical GameTree.

The snapshot stores canonical PGN exchange text plus semantic identity digests.
An additional exact PGN digest protects loss-aware evidence such as move-number
spelling and whitespace that is intentionally outside semantic GameIdentity.
Restore always reparses through the existing structural parser and rejects any
corruption before exposing a PgnGame.  This module does not create a second
chess/tree representation.
"""

from dataclasses import dataclass
from enum import Enum
import hashlib
import re

from .game_identity import GameIdentityContractError, identity_for_game
from .gametree import PgnGame, parse_games, serialize_game

GAMETREE_SNAPSHOT_SCHEMA_VERSION = 1
MAX_SNAPSHOT_TEXT_BYTES = 16 * 1024 * 1024
MAX_SNAPSHOT_WARNINGS = 10_000
MAX_WARNING_CHARS = 16_384
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_SNAPSHOT_RECORD_FIELDS = frozenset(
    {
        "schema_version",
        "pgn_text",
        "pgn_digest",
        "tree_digest",
        "record_digest",
        "source_index",
        "warnings",
    }
)


class GameTreeSnapshotCode(str, Enum):
    INVALID_SNAPSHOT = "invalid_snapshot"
    UNSUPPORTED_VERSION = "unsupported_version"
    RESOURCE_LIMIT = "resource_limit"
    PARSE_FAILURE = "parse_failure"
    IDENTITY_MISMATCH = "identity_mismatch"
    PAYLOAD_MISMATCH = "payload_mismatch"


class GameTreeSnapshotError(ValueError):
    def __init__(self, message: str, *, code: GameTreeSnapshotCode) -> None:
        super().__init__(message)
        self.code = GameTreeSnapshotCode(code)


def _require_digest(value: object, name: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise GameTreeSnapshotError(
            f"{name} must be a lowercase SHA-256 digest",
            code=GameTreeSnapshotCode.INVALID_SNAPSHOT,
        )
    return value


def _pgn_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require_warning_tuple(value: object) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise GameTreeSnapshotError(
            "warnings must be an exact tuple",
            code=GameTreeSnapshotCode.INVALID_SNAPSHOT,
        )
    if len(value) > MAX_SNAPSHOT_WARNINGS:
        raise GameTreeSnapshotError(
            "warning count exceeds the snapshot safety limit",
            code=GameTreeSnapshotCode.RESOURCE_LIMIT,
        )
    for warning in value:
        if not isinstance(warning, str):
            raise GameTreeSnapshotError(
                "warnings must contain only text values",
                code=GameTreeSnapshotCode.INVALID_SNAPSHOT,
            )
        if len(warning) > MAX_WARNING_CHARS:
            raise GameTreeSnapshotError(
                "warning text exceeds the snapshot safety limit",
                code=GameTreeSnapshotCode.RESOURCE_LIMIT,
            )
    return value


@dataclass(frozen=True, slots=True)
class GameTreeSnapshot:
    schema_version: int
    pgn_text: str
    pgn_digest: str
    tree_digest: str
    record_digest: str
    source_index: int
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int:
            raise GameTreeSnapshotError(
                "schema_version must be an exact integer",
                code=GameTreeSnapshotCode.INVALID_SNAPSHOT,
            )
        if self.schema_version != GAMETREE_SNAPSHOT_SCHEMA_VERSION:
            raise GameTreeSnapshotError(
                "snapshot schema version is unsupported",
                code=GameTreeSnapshotCode.UNSUPPORTED_VERSION,
            )
        if not isinstance(self.pgn_text, str) or not self.pgn_text:
            raise GameTreeSnapshotError(
                "pgn_text must be non-empty text",
                code=GameTreeSnapshotCode.INVALID_SNAPSHOT,
            )
        if len(self.pgn_text.encode("utf-8")) > MAX_SNAPSHOT_TEXT_BYTES:
            raise GameTreeSnapshotError(
                "snapshot PGN exceeds the safety limit",
                code=GameTreeSnapshotCode.RESOURCE_LIMIT,
            )
        _require_digest(self.pgn_digest, "pgn_digest")
        if _pgn_digest(self.pgn_text) != self.pgn_digest:
            raise GameTreeSnapshotError(
                "snapshot PGN payload digest does not match",
                code=GameTreeSnapshotCode.PAYLOAD_MISMATCH,
            )
        _require_digest(self.tree_digest, "tree_digest")
        _require_digest(self.record_digest, "record_digest")
        if type(self.source_index) is not int or self.source_index < 0:
            raise GameTreeSnapshotError(
                "source_index must be a non-negative exact integer",
                code=GameTreeSnapshotCode.INVALID_SNAPSHOT,
            )
        _require_warning_tuple(self.warnings)


def snapshot_game(game: PgnGame) -> GameTreeSnapshot:
    if not isinstance(game, PgnGame):
        raise TypeError("snapshot_game requires a PgnGame")
    try:
        identity = identity_for_game(game)
        pgn_text = serialize_game(game)
    except (GameIdentityContractError, ValueError, TypeError) as exc:
        raise GameTreeSnapshotError(
            f"cannot snapshot invalid GameTree: {exc}",
            code=GameTreeSnapshotCode.INVALID_SNAPSHOT,
        ) from exc
    warnings = tuple(game.warnings)
    _require_warning_tuple(warnings)
    return GameTreeSnapshot(
        schema_version=GAMETREE_SNAPSHOT_SCHEMA_VERSION,
        pgn_text=pgn_text,
        pgn_digest=_pgn_digest(pgn_text),
        tree_digest=identity.tree_digest,
        record_digest=identity.record_digest,
        source_index=game.source_index,
        warnings=warnings,
    )


def snapshot_to_record(snapshot: GameTreeSnapshot) -> dict[str, object]:
    """Return a detached JSON-safe record for persisted/exchanged snapshots."""

    if not isinstance(snapshot, GameTreeSnapshot):
        raise TypeError("snapshot_to_record requires a GameTreeSnapshot")
    return {
        "schema_version": snapshot.schema_version,
        "pgn_text": snapshot.pgn_text,
        "pgn_digest": snapshot.pgn_digest,
        "tree_digest": snapshot.tree_digest,
        "record_digest": snapshot.record_digest,
        "source_index": snapshot.source_index,
        "warnings": list(snapshot.warnings),
    }


def snapshot_from_record(record: object) -> GameTreeSnapshot:
    """Validate an external record and rebuild the exact versioned snapshot.

    Version 1 is intentionally closed-world: missing or unknown fields are
    rejected rather than silently normalized.  A future schema must opt into a
    migration policy explicitly instead of changing v1 semantics in place.
    """

    if type(record) is not dict:
        raise GameTreeSnapshotError(
            "snapshot record must be an exact object",
            code=GameTreeSnapshotCode.INVALID_SNAPSHOT,
        )
    fields = set(record)
    if fields != _SNAPSHOT_RECORD_FIELDS:
        missing = sorted(_SNAPSHOT_RECORD_FIELDS - fields)
        unknown = sorted(str(field) for field in fields - _SNAPSHOT_RECORD_FIELDS)
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unknown:
            details.append("unknown=" + ",".join(unknown))
        raise GameTreeSnapshotError(
            "snapshot record fields are not canonical" + (
                ": " + "; ".join(details) if details else ""
            ),
            code=GameTreeSnapshotCode.INVALID_SNAPSHOT,
        )
    warnings = record["warnings"]
    if type(warnings) is not list:
        raise GameTreeSnapshotError(
            "snapshot record warnings must be an exact list",
            code=GameTreeSnapshotCode.INVALID_SNAPSHOT,
        )
    warning_tuple = tuple(warnings)
    _require_warning_tuple(warning_tuple)
    return GameTreeSnapshot(
        schema_version=record["schema_version"],
        pgn_text=record["pgn_text"],
        pgn_digest=record["pgn_digest"],
        tree_digest=record["tree_digest"],
        record_digest=record["record_digest"],
        source_index=record["source_index"],
        warnings=warning_tuple,
    )


def restore_game(snapshot: GameTreeSnapshot) -> PgnGame:
    if not isinstance(snapshot, GameTreeSnapshot):
        raise TypeError("restore_game requires a GameTreeSnapshot")
    try:
        parsed = parse_games(snapshot.pgn_text)
    except (ValueError, TypeError) as exc:
        raise GameTreeSnapshotError(
            f"snapshot PGN cannot be parsed: {exc}",
            code=GameTreeSnapshotCode.PARSE_FAILURE,
        ) from exc
    if len(parsed) != 1:
        raise GameTreeSnapshotError(
            "snapshot PGN must contain exactly one game",
            code=GameTreeSnapshotCode.PARSE_FAILURE,
        )
    game = parsed[0]
    try:
        identity = identity_for_game(game)
    except (GameIdentityContractError, ValueError, TypeError) as exc:
        raise GameTreeSnapshotError(
            f"restored GameTree is invalid: {exc}",
            code=GameTreeSnapshotCode.PARSE_FAILURE,
        ) from exc
    if (
        identity.tree_digest != snapshot.tree_digest
        or identity.record_digest != snapshot.record_digest
    ):
        raise GameTreeSnapshotError(
            "snapshot identity does not match restored GameTree",
            code=GameTreeSnapshotCode.IDENTITY_MISMATCH,
        )
    game.source_index = snapshot.source_index
    game.warnings = list(snapshot.warnings)
    return game
