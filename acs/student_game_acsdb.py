from __future__ import annotations

"""Canonical D10 StudentGame -> ACSDB identity binding.

The Classroom schema intentionally keeps ``StudentGame.game_id`` as an opaque
bounded identifier.  This module gives that field one versioned Product meaning
when a student game points at canonical ACSDB content without changing either
wire schema.

A token binds the current ACSDB row id to the source index and to a SHA-256
fingerprint of the immutable source identity plus the exact stored PGN text.
Resolution is therefore fail-closed: a deleted/replaced row, changed source,
changed source index, or changed canonical PGN cannot silently retarget an
education record.
"""

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Mapping

from .acsdb import AcsDatabase
from .classroom_domain import StudentGame


_SQLITE_INTEGER_MAX = (1 << 63) - 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_RE = re.compile(r"^ag1:([1-9][0-9]{0,18}):([0-9]{1,19}):([0-9a-f]{64})$")
_MAX_SOURCE_FORMAT = 64


class StudentGameIdentityError(ValueError):
    """Raised when a StudentGame cannot be proven to name current ACSDB content."""


@dataclass(frozen=True, slots=True)
class ResolvedStudentGameIdentity:
    """Detached canonical identity returned after a successful fail-closed resolve."""

    token: str
    game_id: int
    source_id: int
    source_index: int
    source_format: str
    source_sha256: str
    pgn_revision: str


def _sqlite_integer(value: object, *, name: str, minimum: int) -> int:
    if type(value) is not int:
        raise StudentGameIdentityError(f"{name} must be an integer")
    if value < minimum or value > _SQLITE_INTEGER_MAX:
        raise StudentGameIdentityError(f"{name} is outside the supported SQLite integer range")
    return value


def _mapping_integer(record: Mapping[str, object], key: str, *, minimum: int) -> int:
    if key not in record:
        raise StudentGameIdentityError(f"ACSDB {key} is missing")
    return _sqlite_integer(record[key], name=f"ACSDB {key}", minimum=minimum)


def _source_sha256(value: object) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise StudentGameIdentityError("ACSDB source must have an exact lowercase SHA-256 identity")
    return value


def _source_format(value: object) -> str:
    if type(value) is not str:
        raise StudentGameIdentityError("ACSDB source format must be text")
    if not value or len(value) > _MAX_SOURCE_FORMAT:
        raise StudentGameIdentityError("ACSDB source format must be bounded non-empty text")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise StudentGameIdentityError("ACSDB source format must not contain control characters")
    return value


def _pgn_text(value: object) -> str:
    if type(value) is not str or not value:
        raise StudentGameIdentityError("ACSDB game must contain canonical PGN text")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise StudentGameIdentityError("ACSDB game PGN is not valid Unicode text") from exc
    return value


def _pgn_revision(pgn_text: str) -> str:
    return hashlib.sha256(pgn_text.encode("utf-8")).hexdigest()


def _identity_digest(
    *,
    source_format: str,
    source_sha256: str,
    source_index: int,
    pgn_revision: str,
) -> str:
    payload = json.dumps(
        {
            "pgn_revision": pgn_revision,
            "source_format": source_format,
            "source_index": source_index,
            "source_sha256": source_sha256,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _load_identity(database: AcsDatabase, game_id: int) -> ResolvedStudentGameIdentity:
    if not isinstance(database, AcsDatabase):
        raise TypeError("database must be AcsDatabase")
    game_id = _sqlite_integer(game_id, name="game_id", minimum=1)
    game = database.get_game(game_id)
    if game is None:
        raise StudentGameIdentityError("StudentGame references a missing ACSDB game")

    stored_game_id = _mapping_integer(game, "id", minimum=1)
    if stored_game_id != game_id:
        raise StudentGameIdentityError("ACSDB returned a mismatched game identity")
    source_id = _mapping_integer(game, "source_id", minimum=1)
    source_index = _mapping_integer(game, "source_index", minimum=0)
    pgn_revision = _pgn_revision(_pgn_text(game.get("pgn_text")))

    source = database.get_source(source_id)
    if source is None:
        raise StudentGameIdentityError("StudentGame references a missing ACSDB source")
    stored_source_id = _mapping_integer(source, "id", minimum=1)
    if stored_source_id != source_id:
        raise StudentGameIdentityError("ACSDB returned a mismatched source identity")
    source_format = _source_format(source.get("source_format"))
    source_sha256 = _source_sha256(source.get("sha256"))

    digest = _identity_digest(
        source_format=source_format,
        source_sha256=source_sha256,
        source_index=source_index,
        pgn_revision=pgn_revision,
    )
    token = f"ag1:{game_id}:{source_index}:{digest}"
    # Classroom identifiers are capped at 128 ASCII-safe characters.  The token
    # remains below that bound even for maximum SQLite integer values.
    if len(token) > 128:
        raise StudentGameIdentityError("canonical StudentGame token exceeds Classroom identifier limit")

    return ResolvedStudentGameIdentity(
        token=token,
        game_id=game_id,
        source_id=source_id,
        source_index=source_index,
        source_format=source_format,
        source_sha256=source_sha256,
        pgn_revision=pgn_revision,
    )


def canonical_student_game_token(database: AcsDatabase, game_id: int) -> str:
    """Return a versioned opaque token for one exact current ACSDB game."""

    return _load_identity(database, game_id).token


def bind_student_game(
    database: AcsDatabase,
    *,
    student_game_id: str,
    student_id: str,
    game_id: int,
    assignment_id: str | None = None,
) -> StudentGame:
    """Create a D10 StudentGame bound to current canonical ACSDB provenance."""

    return StudentGame(
        student_game_id=student_game_id,
        student_id=student_id,
        game_id=canonical_student_game_token(database, game_id),
        assignment_id=assignment_id,
    )


def resolve_student_game(
    database: AcsDatabase,
    student_game: StudentGame,
) -> ResolvedStudentGameIdentity:
    """Resolve a StudentGame only if its exact ACSDB provenance still matches.

    Legacy arbitrary ``game_id`` strings intentionally fail closed.  There is no
    heuristic migration because guessing which current library row an old opaque
    identifier meant can silently attach a student's record to the wrong game.
    """

    if not isinstance(student_game, StudentGame):
        raise TypeError("student_game must be StudentGame")
    token = student_game.game_id
    if type(token) is not str:
        raise StudentGameIdentityError("StudentGame game_id must be text")
    match = _TOKEN_RE.fullmatch(token)
    if match is None:
        raise StudentGameIdentityError("StudentGame game_id is not a canonical ACSDB identity token")

    game_id = _sqlite_integer(int(match.group(1)), name="token game_id", minimum=1)
    expected_source_index = _sqlite_integer(
        int(match.group(2)), name="token source_index", minimum=0
    )
    expected_digest = match.group(3)

    current = _load_identity(database, game_id)
    if current.source_index != expected_source_index:
        raise StudentGameIdentityError("StudentGame ACSDB source index changed")
    if current.token != token or not hashlib.compare_digest(
        current.token.rsplit(":", 1)[1], expected_digest
    ):
        raise StudentGameIdentityError("StudentGame ACSDB provenance or canonical PGN changed")
    return current
