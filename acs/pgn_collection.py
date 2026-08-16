from __future__ import annotations

"""Collection-scale operations over the canonical PGN workspace.

This module adds deterministic merge/dedup/page/integrity behavior without
creating a second game representation. ``PgnGame``/``VariationLine`` from
``acs.gametree`` remain the only tree source of truth and ``PgnWorkspace``
remains the working collection owner.
"""

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Iterable

from .game_references import MoveRef, PositionRef, VariationRef
from .gametree import PgnGame, parse_games, serialize_games
from .pgn_semantics import analyze_game
from .pgn_workspace import PgnQuery, PgnSearchHit, PgnWorkspace, game_fingerprint


class DuplicatePolicy(str, Enum):
    KEEP = "keep"
    SKIP_EXISTING = "skip_existing"
    SKIP_ALL = "skip_all"


@dataclass(frozen=True, slots=True)
class MergeDecision:
    incoming_index: int
    fingerprint: str
    action: str
    assigned_source_index: int | None
    duplicate_of: int | None
    usable: bool
    warning_count: int
    error_count: int


@dataclass(frozen=True, slots=True)
class MergeReport:
    decisions: tuple[MergeDecision, ...]
    before_count: int
    after_count: int

    @property
    def added(self) -> int:
        return sum(item.action == "added" for item in self.decisions)

    @property
    def skipped_duplicate(self) -> int:
        return sum(item.action == "skipped_duplicate" for item in self.decisions)

    @property
    def skipped_unusable(self) -> int:
        return sum(item.action == "skipped_unusable" for item in self.decisions)


@dataclass(frozen=True, slots=True)
class SearchPage:
    offset: int
    limit: int
    total: int
    hits: tuple[PgnSearchHit, ...]

    @property
    def next_offset(self) -> int | None:
        candidate = self.offset + len(self.hits)
        return candidate if candidate < self.total else None


@dataclass(frozen=True, slots=True)
class ReferenceAudit:
    games: int
    moves: int
    positions: int
    variations: int


def collection_digest(workspace: PgnWorkspace) -> str:
    """Return an order-sensitive digest of canonical collection content."""

    return sha256(workspace.export_text().encode("utf-8")).hexdigest()


def _next_source_index(games: Iterable[PgnGame]) -> int:
    return max((game.source_index for game in games), default=-1) + 1


def merge_text(
    workspace: PgnWorkspace,
    text: str,
    *,
    duplicate_policy: DuplicatePolicy = DuplicatePolicy.SKIP_EXISTING,
    usable_only: bool = False,
) -> tuple[PgnWorkspace, MergeReport]:
    """Return a new workspace with one deterministic atomic merge applied.

    Parsing happens before any output workspace is constructed. The supplied
    workspace is never mutated. Duplicate checks use canonical PGN fingerprints.
    ``SKIP_EXISTING`` rejects content already present but keeps duplicate records
    that occur more than once inside the same incoming batch. ``SKIP_ALL`` also
    collapses duplicates within the incoming batch. ``KEEP`` retains everything.
    """

    incoming = tuple(parse_games(text))
    existing = list(workspace.games)
    next_index = _next_source_index(existing)
    existing_by_fp: dict[str, int] = {}
    for game in existing:
        existing_by_fp.setdefault(game_fingerprint(game), game.source_index)

    accepted: list[PgnGame] = []
    seen_incoming: dict[str, int] = {}
    decisions: list[MergeDecision] = []

    for incoming_index, game in enumerate(incoming):
        fingerprint = game_fingerprint(game)
        semantic = analyze_game(game)
        duplicate_of = existing_by_fp.get(fingerprint)
        if duplicate_of is None and duplicate_policy == DuplicatePolicy.SKIP_ALL:
            duplicate_of = seen_incoming.get(fingerprint)

        if usable_only and not semantic.usable:
            decisions.append(
                MergeDecision(
                    incoming_index,
                    fingerprint,
                    "skipped_unusable",
                    None,
                    duplicate_of,
                    semantic.usable,
                    semantic.warning_count,
                    semantic.error_count,
                )
            )
            continue

        skip_duplicate = (
            duplicate_policy != DuplicatePolicy.KEEP
            and duplicate_of is not None
        )
        if skip_duplicate:
            decisions.append(
                MergeDecision(
                    incoming_index,
                    fingerprint,
                    "skipped_duplicate",
                    None,
                    duplicate_of,
                    semantic.usable,
                    semantic.warning_count,
                    semantic.error_count,
                )
            )
            continue

        assigned = next_index
        next_index += 1
        game.source_index = assigned
        accepted.append(game)
        seen_incoming.setdefault(fingerprint, assigned)
        decisions.append(
            MergeDecision(
                incoming_index,
                fingerprint,
                "added",
                assigned,
                duplicate_of,
                semantic.usable,
                semantic.warning_count,
                semantic.error_count,
            )
        )

    merged = PgnWorkspace((*existing, *accepted))
    return merged, MergeReport(tuple(decisions), len(existing), len(merged))


def search_page(
    workspace: PgnWorkspace,
    query: PgnQuery,
    *,
    offset: int = 0,
    limit: int = 100,
) -> SearchPage:
    if offset < 0:
        raise ValueError("offset must be non-negative")
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be in range 1..1000")
    hits = workspace.search(query)
    return SearchPage(offset, limit, len(hits), hits[offset : offset + limit])


def export_pages(workspace: PgnWorkspace, *, games_per_page: int = 1000) -> tuple[str, ...]:
    """Split a large collection into deterministic canonical PGN chunks."""

    if games_per_page < 1:
        raise ValueError("games_per_page must be positive")
    games = workspace.games
    return tuple(
        serialize_games(games[index : index + games_per_page])
        for index in range(0, len(games), games_per_page)
    )


def audit_references(workspace: PgnWorkspace) -> ReferenceAudit:
    """Resolve every structural navigation reference fail-closed.

    This is intentionally legality-neutral: it proves Game/Variation/Move/Position
    identity and branch traversal consistency, not whether SAN is legal on a
    chess board.
    """

    games = moves = positions = variations = 0
    for game in workspace.games:
        games += 1
        root = VariationRef(game.source_index)
        workspace.resolve_variation(root)
        variations += 1
        positions += 1  # root position before ply 1

        for item in workspace.navigation(game.source_index):
            if item.kind == "move" and item.move is not None:
                workspace.resolve_move(item.move)
                moves += 1
                workspace.resolve_position(PositionRef(item.move.variation, item.move.move_index))
                workspace.resolve_position(PositionRef(item.move.variation, item.move.move_index + 1))
                positions += 1
            elif item.kind == "variation_enter":
                workspace.resolve_variation(item.variation)
                workspace.branch_context(item.variation)
                variations += 1

    return ReferenceAudit(games, moves, positions, variations)
