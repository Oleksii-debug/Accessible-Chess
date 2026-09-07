from __future__ import annotations

"""Machine-checkable semantic qualification for the blocked CBF/CBI lane.

This module does not register CBF/CBI as a user-facing format.  It exists so a
lawfully reusable authentic CBF+CBI family can be compared against an
independent PGN oracle without adding another ad-hoc decoder or comparison
path.  Qualification is intentionally strict: the multiset of canonical
``GameIdentity.record_digest`` values must match exactly, including duplicate
multiplicity.  PGN whitespace and tag ordering therefore do not matter, while
semantic tags, start position, moves, comments, annotations, variations and
results do.
"""

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path

from .cbf_cbi_external import (
    CbfCbiReadResult,
    ExternalCbfCbiReaderConfig,
    read_cbf_cbi_external,
)
from .game_identity import IDENTITY_SCHEMA_VERSION, identity_for_game
from .gametree import PgnGame, parse_games, serialize_games


class CbfCbiOracleCode(str, Enum):
    ORACLE_INVALID = "oracle_invalid"
    ORACLE_RESOURCE_LIMIT = "oracle_resource_limit"
    ORACLE_SEMANTIC_MISMATCH = "oracle_semantic_mismatch"


class CbfCbiOracleQualificationError(RuntimeError):
    def __init__(self, message: str, *, code: CbfCbiOracleCode) -> None:
        super().__init__(message)
        self.code = CbfCbiOracleCode(code)


@dataclass(frozen=True, slots=True)
class CbfCbiOracleQualificationResult:
    """Evidence returned only after an exact canonical record match."""

    source_family_sha256: str
    oracle_sha256: str
    decoded_game_count: int
    oracle_game_count: int
    identity_schema_version: int
    semantic_multiset_sha256: str
    cbh2si4_sha256: str
    tcscid_sha256: str
    scidpgn_sha256: str
    canonical_roundtrip_verified: bool
    exact_semantic_match: bool


def _error(message: str, code: CbfCbiOracleCode) -> CbfCbiOracleQualificationError:
    return CbfCbiOracleQualificationError(message, code=code)


def _canonical_oracle_games(
    payload: bytes,
    *,
    encoding: str,
    max_games: int,
) -> tuple[PgnGame, ...]:
    if not isinstance(payload, bytes):
        raise TypeError("oracle_pgn must be bytes")
    if not isinstance(encoding, str) or not encoding.strip():
        raise TypeError("oracle_encoding must be non-empty text")
    if type(max_games) is not int or max_games < 1:
        raise ValueError("max_games must be a positive integer")
    try:
        text = payload.decode(encoding, errors="strict")
        games = tuple(parse_games(text))
    except Exception as exc:
        raise _error(
            "CBF/CBI independent PGN oracle is not valid canonical PGN",
            CbfCbiOracleCode.ORACLE_INVALID,
        ) from exc
    if len(games) > max_games:
        raise _error(
            "CBF/CBI independent PGN oracle exceeds the configured game limit",
            CbfCbiOracleCode.ORACLE_RESOURCE_LIMIT,
        )
    try:
        initial = tuple(identity_for_game(game).record_digest for game in games)
        reopened = tuple(parse_games(serialize_games(games)))
        reopened_identities = tuple(
            identity_for_game(game).record_digest for game in reopened
        )
    except Exception as exc:
        raise _error(
            "CBF/CBI independent PGN oracle failed canonical reopen validation",
            CbfCbiOracleCode.ORACLE_INVALID,
        ) from exc
    if initial != reopened_identities:
        raise _error(
            "CBF/CBI independent PGN oracle changes semantic identity on canonical reopen",
            CbfCbiOracleCode.ORACLE_INVALID,
        )
    return games


def _identity_counter(games: tuple[PgnGame, ...]) -> Counter[str]:
    return Counter(identity_for_game(game).record_digest for game in games)


def _semantic_multiset_sha256(identities: Counter[str]) -> str:
    digest = sha256(b"Accessible-Chess-CBF-oracle-record-multiset-v1\0")
    for record_digest, count in sorted(identities.items()):
        digest.update(record_digest.encode("ascii"))
        digest.update(b"\0")
        digest.update(str(count).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def qualify_cbf_cbi_against_pgn_oracle(
    path: str | Path,
    oracle_pgn: bytes,
    config: ExternalCbfCbiReaderConfig,
    *,
    oracle_encoding: str = "utf-8",
) -> CbfCbiOracleQualificationResult:
    """Decode CBF/CBI and require exact semantic equality with PGN oracle bytes.

    No result object is returned for malformed, over-limit or semantically
    different oracle input.  The comparison is order-independent but preserves
    duplicate multiplicity, preventing database ordering from becoming a false
    mismatch while still rejecting missing or duplicated games.
    """

    decoded: CbfCbiReadResult = read_cbf_cbi_external(path, config)
    oracle_games = _canonical_oracle_games(
        oracle_pgn,
        encoding=oracle_encoding,
        max_games=config.max_games,
    )
    try:
        decoded_identities = _identity_counter(decoded.games)
        oracle_identities = _identity_counter(oracle_games)
    except Exception as exc:
        raise _error(
            "CBF/CBI semantic oracle identity calculation failed",
            CbfCbiOracleCode.ORACLE_INVALID,
        ) from exc
    if decoded_identities != oracle_identities:
        raise _error(
            "CBF/CBI decoded games do not exactly match the independent PGN oracle",
            CbfCbiOracleCode.ORACLE_SEMANTIC_MISMATCH,
        )

    return CbfCbiOracleQualificationResult(
        source_family_sha256=decoded.source_family_sha256,
        oracle_sha256=sha256(oracle_pgn).hexdigest(),
        decoded_game_count=len(decoded.games),
        oracle_game_count=len(oracle_games),
        identity_schema_version=IDENTITY_SCHEMA_VERSION,
        semantic_multiset_sha256=_semantic_multiset_sha256(decoded_identities),
        cbh2si4_sha256=decoded.cbh2si4_sha256,
        tcscid_sha256=decoded.tcscid_sha256,
        scidpgn_sha256=decoded.scidpgn_sha256,
        canonical_roundtrip_verified=decoded.canonical_roundtrip_verified,
        exact_semantic_match=True,
    )
