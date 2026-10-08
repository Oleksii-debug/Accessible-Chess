from __future__ import annotations

"""Canonical PGN/GameTree application adapter for structured live broadcasts.

Provider PGN remains evidence until it passes the existing strict D06 PGN
boundary and the existing canonical GameTree legality projection. This module
does not parse SAN/FEN itself and does not implement chess rules.

The resulting chess_ref values are opaque media/application references. They
identify one canonical mainline position history and can be resolved back to
the already-validated final FEN by this application adapter. Media code never
needs to inspect that FEN.
"""

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
from urllib.parse import urlsplit

from .gametree import PgnGame
from .gametree_legality import GameTreeLegalityReport, validate_game_legality
from .pgn_roundtrip import parse_pgn_text
from .structured_broadcast import (
    CanonicalBroadcastGame,
    LICHESS_BROADCAST_PROVIDER,
    LichessBroadcastRound,
    MAX_BROADCAST_GAMES,
    MAX_BROADCAST_IDENTIFIER_CHARS,
    MAX_BROADCAST_PGN_BYTES,
)


MAX_CANONICAL_BROADCAST_POSITIONS = 8192
MAX_LICHESS_GAME_URL_CHARS = 2048


class BroadcastApplicationErrorCode(str, Enum):
    INVALID_INPUT = "invalid_input"
    UNSUPPORTED_PROVIDER = "unsupported_provider"
    INVALID_PROVIDER_GAME_ID = "invalid_provider_game_id"
    DUPLICATE_PROVIDER_GAME = "duplicate_provider_game"
    CANONICAL_PGN_REJECTED = "canonical_pgn_rejected"
    ILLEGAL_GAME = "illegal_game"
    UNKNOWN_CHESS_REF = "unknown_chess_ref"
    UNKNOWN_PROVIDER_GAME = "unknown_provider_game"


class BroadcastApplicationError(ValueError):
    """Stable fail-closed error for the canonical broadcast application seam."""

    def __init__(self, message: str, *, code: BroadcastApplicationErrorCode) -> None:
        super().__init__(message)
        self.code = BroadcastApplicationErrorCode(code)


def _exact_text(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or "\x00" in value
        or any(0xD800 <= ord(character) <= 0xDFFF for character in value)
    ):
        raise BroadcastApplicationError(
            f"{name} must be safe non-empty exact text",
            code=BroadcastApplicationErrorCode.INVALID_INPUT,
        )
    return value


def _lichess_game_id_from_url(value: object, round_id: str) -> str:
    url = _exact_text(value, "Lichess GameURL")
    if len(url) > MAX_LICHESS_GAME_URL_CHARS:
        raise BroadcastApplicationError(
            "Lichess broadcast game URL exceeds the safety limit",
            code=BroadcastApplicationErrorCode.INVALID_PROVIDER_GAME_ID,
        )
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "lichess.org"
        or parsed.query
        or parsed.fragment
    ):
        raise BroadcastApplicationError(
            "Lichess broadcast game URL is invalid",
            code=BroadcastApplicationErrorCode.INVALID_PROVIDER_GAME_ID,
        )
    parts = tuple(part for part in parsed.path.split("/") if part)
    if (
        len(parts) < 4
        or parts[0] != "broadcast"
        or parts[-2] != round_id
        or len(parts[-1]) != 8
        or not parts[-1].isascii()
        or not parts[-1].isalnum()
    ):
        raise BroadcastApplicationError(
            "Lichess broadcast game URL does not match the selected round",
            code=BroadcastApplicationErrorCode.INVALID_PROVIDER_GAME_ID,
        )
    return parts[-1]


def _lichess_game_id(game: PgnGame, round_id: str) -> str:
    if type(game.tags) is not dict:
        raise BroadcastApplicationError(
            "canonical PGN tags are invalid",
            code=BroadcastApplicationErrorCode.CANONICAL_PGN_REJECTED,
        )
    game_url = game.tags.get("GameURL")
    site = game.tags.get("Site")
    candidates: list[str] = []
    for value in (game_url, site):
        if value is None:
            continue
        candidates.append(_lichess_game_id_from_url(value, round_id))
    if not candidates:
        raise BroadcastApplicationError(
            "Lichess broadcast PGN has no canonical game URL identity",
            code=BroadcastApplicationErrorCode.INVALID_PROVIDER_GAME_ID,
        )
    if len(set(candidates)) != 1:
        raise BroadcastApplicationError(
            "Lichess broadcast PGN contains conflicting game identities",
            code=BroadcastApplicationErrorCode.INVALID_PROVIDER_GAME_ID,
        )
    return candidates[0]


def _mainline_revision(
    report: GameTreeLegalityReport,
    game: PgnGame,
) -> tuple[str, str]:
    if not report.complete or report.issues or type(report.start_fen) is not str:
        raise BroadcastApplicationError(
            "broadcast game is not fully legal under the canonical board",
            code=BroadcastApplicationErrorCode.ILLEGAL_GAME,
        )

    mainline = {
        move.address.move_index: move
        for move in report.moves
        if move.address.line_path == ()
    }
    if len(mainline) != len(game.line.moves) or set(mainline) != set(range(len(game.line.moves))):
        raise BroadcastApplicationError(
            "canonical legality projection does not cover the complete mainline",
            code=BroadcastApplicationErrorCode.ILLEGAL_GAME,
        )

    ordered = [mainline[index] for index in range(len(game.line.moves))]
    payload = {
        "schema": 1,
        "start_fen": report.start_fen,
        "mainline": [
            {
                "ply": index + 1,
                "san": move.san_canonical,
                "fen_after": move.fen_after,
            }
            for index, move in enumerate(ordered)
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    revision = sha256(b"accessible-chess-live-position-v1\0" + encoded).hexdigest()
    final_fen = ordered[-1].fen_after if ordered else report.start_fen
    return revision, final_fen


@dataclass(frozen=True, slots=True)
class ResolvedBroadcastPosition:
    """Application-owned canonical position referenced opaquely by media."""

    chess_ref: str
    canonical_revision: str
    final_fen: str


class LichessCanonicalBroadcastAdapter:
    """Bind official Lichess Broadcast PGN to canonical Accessible Chess state.

    The adapter has no HTTP/OAuth responsibility. It accepts the complete PGN
    text already delivered by a provider transport, validates it through the
    existing canonical PGN and legality services, and publishes opaque
    references for Media Core.
    """

    def __init__(
        self,
        *,
        position_cache_limit: int = MAX_CANONICAL_BROADCAST_POSITIONS,
    ) -> None:
        if (
            type(position_cache_limit) is not int
            or position_cache_limit < 1
            or position_cache_limit > MAX_CANONICAL_BROADCAST_POSITIONS
        ):
            raise BroadcastApplicationError(
                "position cache limit is outside the supported bound",
                code=BroadcastApplicationErrorCode.INVALID_INPUT,
            )
        self._position_cache_limit = position_cache_limit
        self._positions: OrderedDict[str, ResolvedBroadcastPosition] = OrderedDict()
        self._latest_games: dict[str, PgnGame] = {}

    def ingest_broadcast_pgn(
        self,
        *,
        provider: str,
        round_id: str,
        source_id: str,
        pgn_text: str,
    ) -> tuple[CanonicalBroadcastGame, ...]:
        provider_value = _exact_text(provider, "provider")
        round_value = _exact_text(round_id, "round_id")
        source_value = _exact_text(source_id, "source_id")
        text = _exact_text(pgn_text, "pgn_text")
        if (
            len(provider_value) > MAX_BROADCAST_IDENTIFIER_CHARS
            or len(round_value) > MAX_BROADCAST_IDENTIFIER_CHARS
            or len(source_value) > MAX_BROADCAST_IDENTIFIER_CHARS
        ):
            raise BroadcastApplicationError(
                "broadcast identity exceeds the structured-ingress safety limit",
                code=BroadcastApplicationErrorCode.INVALID_INPUT,
            )
        if len(text.encode("utf-8")) > MAX_BROADCAST_PGN_BYTES:
            raise BroadcastApplicationError(
                "broadcast PGN exceeds the structured-ingress byte limit",
                code=BroadcastApplicationErrorCode.INVALID_INPUT,
            )
        if provider_value != LICHESS_BROADCAST_PROVIDER:
            raise BroadcastApplicationError(
                "structured broadcast provider is not supported by this adapter",
                code=BroadcastApplicationErrorCode.UNSUPPORTED_PROVIDER,
            )
        try:
            LichessBroadcastRound(round_value)
        except Exception:
            raise BroadcastApplicationError(
                "Lichess broadcast round identity is invalid",
                code=BroadcastApplicationErrorCode.INVALID_INPUT,
            ) from None

        try:
            games = parse_pgn_text(text, strict=True)
        except Exception:
            raise BroadcastApplicationError(
                "broadcast PGN was rejected by the canonical PGN boundary",
                code=BroadcastApplicationErrorCode.CANONICAL_PGN_REJECTED,
            ) from None
        if not games:
            raise BroadcastApplicationError(
                "broadcast PGN contains no canonical game",
                code=BroadcastApplicationErrorCode.CANONICAL_PGN_REJECTED,
            )

        staged: list[
            tuple[str, CanonicalBroadcastGame, ResolvedBroadcastPosition, PgnGame]
        ] = []
        seen: set[str] = set()
        for game in games:
            game_id = _lichess_game_id(game, round_value)
            if game_id in seen:
                raise BroadcastApplicationError(
                    "broadcast PGN repeats one provider game identity",
                    code=BroadcastApplicationErrorCode.DUPLICATE_PROVIDER_GAME,
                )
            seen.add(game_id)

            report = validate_game_legality(game)
            revision, final_fen = _mainline_revision(report, game)
            ref_material = "\0".join(
                (provider_value, round_value, source_value, game_id, revision)
            ).encode("utf-8")
            chess_ref = "ac-live-v1:" + sha256(ref_material).hexdigest()
            resolved = ResolvedBroadcastPosition(
                chess_ref=chess_ref,
                canonical_revision="position-v1:" + revision,
                final_fen=final_fen,
            )
            staged.append(
                (
                    game_id,
                    CanonicalBroadcastGame(
                        provider_game_id=game_id,
                        chess_ref=resolved.chess_ref,
                        canonical_revision=resolved.canonical_revision,
                    ),
                    resolved,
                    deepcopy(game),
                )
            )

        if len(set(self._latest_games) | seen) > MAX_BROADCAST_GAMES:
            raise BroadcastApplicationError(
                "broadcast exceeds the canonical game-count bound",
                code=BroadcastApplicationErrorCode.CANONICAL_PGN_REJECTED,
            )

        # Publish only after every game in the provider update has passed the
        # complete canonical parse/legality/identity transaction.
        for game_id, _, resolved, game in staged:
            existing = self._positions.get(resolved.chess_ref)
            if existing is None:
                self._positions[resolved.chess_ref] = resolved
            else:
                self._positions.move_to_end(resolved.chess_ref)
            while len(self._positions) > self._position_cache_limit:
                self._positions.popitem(last=False)
            self._latest_games[game_id] = game

        return tuple(item[1] for item in staged)

    def resolve_chess_ref(self, chess_ref: str) -> ResolvedBroadcastPosition:
        ref = _exact_text(chess_ref, "chess_ref")
        try:
            return self._positions[ref]
        except KeyError:
            raise BroadcastApplicationError(
                "broadcast chess reference is not available",
                code=BroadcastApplicationErrorCode.UNKNOWN_CHESS_REF,
            ) from None

    def current_game(self, provider_game_id: str) -> PgnGame:
        game_id = _exact_text(provider_game_id, "provider_game_id")
        try:
            game = self._latest_games[game_id]
        except KeyError:
            raise BroadcastApplicationError(
                "broadcast game is not available",
                code=BroadcastApplicationErrorCode.UNKNOWN_PROVIDER_GAME,
            ) from None
        return deepcopy(game)
