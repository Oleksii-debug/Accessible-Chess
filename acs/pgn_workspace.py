from __future__ import annotations

"""Practical collection/navigation services over the canonical PGN GameTree.

This module deliberately does not parse chess legality or duplicate storage
repositories.  ``acs.gametree`` remains the only PGN tree source of truth;
this layer provides collection-scale import/export, stable references,
search/indexing, diagnostics, fingerprints, navigation and bulk reporting for
UI/database/book adapters.
"""

from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Iterable, Iterator, Mapping, Sequence

from .game_references import (
    BranchContext,
    GameReferenceError,
    MoveRef,
    PositionRef,
    VariationRef,
    branch_context,
    child_variation,
    resolve_move,
    resolve_position,
    resolve_variation,
)
from .gametree import (
    Comment,
    MoveNode,
    PgnGame,
    VariationLine,
    iter_variations,
    parse_games,
    serialize_game,
    serialize_games,
    structural_signature,
)
from .pgn_semantics import DiagnosticSeverity, PgnSemanticRecord, analyze_game


@dataclass(frozen=True, slots=True)
class PgnCollectionStats:
    games: int
    mainline_plies: int
    recursive_plies: int
    variations: int
    comments: int
    nags: int
    unsupported_tokens: int
    warnings: int
    errors: int


@dataclass(frozen=True, slots=True)
class PgnImportGameReport:
    source_index: int
    fingerprint: str
    usable: bool
    warning_count: int
    error_count: int
    mainline_plies: int
    recursive_plies: int
    variation_count: int


@dataclass(frozen=True, slots=True)
class PgnImportReport:
    games: tuple[PgnImportGameReport, ...]
    stats: PgnCollectionStats

    @property
    def usable_games(self) -> int:
        return sum(item.usable for item in self.games)

    @property
    def rejected_games(self) -> int:
        return len(self.games) - self.usable_games


@dataclass(frozen=True, slots=True)
class PgnQuery:
    """Case-insensitive metadata/mainline query for collection browsing."""

    text: str | None = None
    white: str | None = None
    black: str | None = None
    player: str | None = None
    event: str | None = None
    site: str | None = None
    result: str | None = None
    eco: str | None = None
    date_prefix: str | None = None
    min_ply: int | None = None
    max_ply: int | None = None
    has_variations: bool | None = None
    has_comments: bool | None = None
    usable_only: bool = False


@dataclass(frozen=True, slots=True)
class PgnSearchHit:
    source_index: int
    fingerprint: str
    white: str
    black: str
    event: str
    site: str
    date: str
    result: str
    eco: str
    ply_count: int
    variation_count: int
    warning_count: int
    error_count: int


@dataclass(frozen=True, slots=True)
class NavigationItem:
    """One deterministic structural reading item.

    ``kind`` is one of ``move``, ``variation_enter``, ``variation_exit`` or
    ``result``.  Move items always carry a stable ``MoveRef``.  Branch markers
    carry the child variation ref and exact branch context.
    """

    kind: str
    variation: VariationRef
    move: MoveRef | None = None
    branch: BranchContext | None = None
    san: str | None = None
    result: str | None = None
    depth: int = 0


class PgnWorkspaceError(ValueError):
    pass


def _fold(value: str | None) -> str:
    return (value or "").casefold()


def _contains(value: str | None, needle: str | None) -> bool:
    return needle is None or _fold(needle) in _fold(value)


def _count_line(line: VariationLine) -> tuple[int, int, int, int, int]:
    recursive_plies = len(line.moves)
    variations = 0
    comments = len(line.leading_comments) + len(line.trailing_comments)
    nags = 0
    unsupported = len(line.unsupported_tokens)
    for move in line.moves:
        comments += len(move.comments_before) + len(move.comments_after)
        nags += len(move.nags)
        for child in move.variations:
            variations += 1
            child_plies, child_vars, child_comments, child_nags, child_unsupported = _count_line(child)
            recursive_plies += child_plies
            variations += child_vars
            comments += child_comments
            nags += child_nags
            unsupported += child_unsupported
    return recursive_plies, variations, comments, nags, unsupported


def game_fingerprint(game: PgnGame) -> str:
    """Stable content fingerprint independent of source_index and warnings."""
    canonical = serialize_game(game).encode("utf-8")
    return sha256(canonical).hexdigest()


def _game_report(game: PgnGame) -> PgnImportGameReport:
    semantic = analyze_game(game)
    recursive_plies, variations, _comments, _nags, _unsupported = _count_line(game.line)
    return PgnImportGameReport(
        source_index=game.source_index,
        fingerprint=game_fingerprint(game),
        usable=semantic.usable,
        warning_count=semantic.warning_count,
        error_count=semantic.error_count,
        mainline_plies=game.ply_count,
        recursive_plies=recursive_plies,
        variation_count=variations,
    )


def collection_stats(games: Iterable[PgnGame]) -> PgnCollectionStats:
    items = tuple(games)
    mainline = recursive = variations = comments = nags = unsupported = warnings = errors = 0
    for game in items:
        mainline += game.ply_count
        r, v, c, n, u = _count_line(game.line)
        recursive += r
        variations += v
        comments += c
        nags += n
        unsupported += u
        semantic = analyze_game(game)
        warnings += semantic.warning_count
        errors += semantic.error_count
    return PgnCollectionStats(
        games=len(items),
        mainline_plies=mainline,
        recursive_plies=recursive,
        variations=variations,
        comments=comments,
        nags=nags,
        unsupported_tokens=unsupported,
        warnings=warnings,
        errors=errors,
    )


def build_import_report(games: Iterable[PgnGame]) -> PgnImportReport:
    items = tuple(games)
    return PgnImportReport(tuple(_game_report(game) for game in items), collection_stats(items))


def _walk_navigation(
    game: PgnGame,
    variation: VariationRef,
    *,
    depth: int,
) -> Iterator[NavigationItem]:
    line = resolve_variation(game, variation)
    for move_index, move in enumerate(line.moves):
        move_ref = MoveRef(variation, move_index)
        yield NavigationItem("move", variation, move=move_ref, san=move.san, depth=depth)
        for variation_index, _child in enumerate(move.variations):
            child_ref = child_variation(variation, move_index, variation_index)
            context = branch_context(game, child_ref)
            yield NavigationItem(
                "variation_enter",
                child_ref,
                branch=context,
                depth=depth + 1,
            )
            yield from _walk_navigation(game, child_ref, depth=depth + 1)
            yield NavigationItem(
                "variation_exit",
                child_ref,
                branch=context,
                depth=depth + 1,
            )
    if line.result:
        yield NavigationItem("result", variation, result=line.result, depth=depth)


def navigation_items(game: PgnGame) -> tuple[NavigationItem, ...]:
    return tuple(_walk_navigation(game, VariationRef(game.source_index), depth=0))


class PgnWorkspace:
    """In-memory working set for PGN import/browse/export.

    The workspace intentionally owns only the collection list.  Every game is
    still the canonical ``PgnGame`` tree from :mod:`acs.gametree`.  Storage
    adapters may consume reports/fingerprints/references without gaining a
    second mutable representation of moves or branches.
    """

    def __init__(self, games: Sequence[PgnGame] = ()) -> None:
        self._games = list(games)
        self._validate_source_indices()

    @classmethod
    def from_text(cls, text: str) -> "PgnWorkspace":
        return cls(parse_games(text))

    @property
    def games(self) -> tuple[PgnGame, ...]:
        return tuple(self._games)

    def __len__(self) -> int:
        return len(self._games)

    def _validate_source_indices(self) -> None:
        seen: set[int] = set()
        for game in self._games:
            if game.source_index < 0:
                raise PgnWorkspaceError("source_index must be non-negative")
            if game.source_index in seen:
                raise PgnWorkspaceError(f"duplicate source_index {game.source_index}")
            seen.add(game.source_index)

    def game(self, source_index: int) -> PgnGame:
        for game in self._games:
            if game.source_index == source_index:
                return game
        raise GameReferenceError(f"unknown game source_index {source_index}")

    def semantic_record(self, source_index: int) -> PgnSemanticRecord:
        return analyze_game(self.game(source_index))

    def fingerprint(self, source_index: int) -> str:
        return game_fingerprint(self.game(source_index))

    def report(self) -> PgnImportReport:
        return build_import_report(self._games)

    def stats(self) -> PgnCollectionStats:
        return collection_stats(self._games)

    def export_text(self, source_indices: Iterable[int] | None = None) -> str:
        if source_indices is None:
            return serialize_games(self._games)
        selected = [self.game(index) for index in source_indices]
        return serialize_games(selected)

    def append_text(self, text: str) -> tuple[int, ...]:
        """Append parsed games while allocating non-colliding source indices."""
        incoming = parse_games(text)
        next_index = max((game.source_index for game in self._games), default=-1) + 1
        allocated: list[int] = []
        for offset, game in enumerate(incoming):
            new_index = next_index + offset
            game.source_index = new_index
            self._games.append(game)
            allocated.append(new_index)
        return tuple(allocated)

    def remove(self, source_index: int) -> PgnGame:
        game = self.game(source_index)
        self._games.remove(game)
        return game

    def resolve_variation(self, ref: VariationRef) -> VariationLine:
        return resolve_variation(self.game(ref.source_index), ref)

    def resolve_move(self, ref: MoveRef) -> MoveNode:
        return resolve_move(self.game(ref.variation.source_index), ref)

    def resolve_position(self, ref: PositionRef) -> PositionRef:
        return resolve_position(self.game(ref.variation.source_index), ref)

    def branch_context(self, ref: VariationRef) -> BranchContext:
        return branch_context(self.game(ref.source_index), ref)

    def navigation(self, source_index: int) -> tuple[NavigationItem, ...]:
        return navigation_items(self.game(source_index))

    def search(self, query: PgnQuery) -> tuple[PgnSearchHit, ...]:
        hits: list[PgnSearchHit] = []
        for game in self._games:
            tags = game.tags
            semantic = analyze_game(game)
            recursive, variation_count, comment_count, _nags, _unsupported = _count_line(game.line)
            del recursive
            if query.usable_only and not semantic.usable:
                continue
            if not _contains(tags.get("White"), query.white):
                continue
            if not _contains(tags.get("Black"), query.black):
                continue
            if query.player is not None and not (
                _contains(tags.get("White"), query.player) or _contains(tags.get("Black"), query.player)
            ):
                continue
            if not _contains(tags.get("Event"), query.event):
                continue
            if not _contains(tags.get("Site"), query.site):
                continue
            if query.result is not None and game.result != query.result:
                continue
            if not _contains(tags.get("ECO"), query.eco):
                continue
            if query.date_prefix is not None and not (tags.get("Date", "").startswith(query.date_prefix)):
                continue
            if query.min_ply is not None and game.ply_count < query.min_ply:
                continue
            if query.max_ply is not None and game.ply_count > query.max_ply:
                continue
            if query.has_variations is not None and (variation_count > 0) != query.has_variations:
                continue
            if query.has_comments is not None and (comment_count > 0) != query.has_comments:
                continue
            if query.text:
                haystack = "\n".join(
                    [*tags.values(), *(move.san for move in game.iter_moves(recursive=True))]
                ).casefold()
                if query.text.casefold() not in haystack:
                    continue
            hits.append(
                PgnSearchHit(
                    source_index=game.source_index,
                    fingerprint=game_fingerprint(game),
                    white=tags.get("White", ""),
                    black=tags.get("Black", ""),
                    event=tags.get("Event", ""),
                    site=tags.get("Site", ""),
                    date=tags.get("Date", ""),
                    result=game.result,
                    eco=tags.get("ECO", ""),
                    ply_count=game.ply_count,
                    variation_count=variation_count,
                    warning_count=semantic.warning_count,
                    error_count=semantic.error_count,
                )
            )
        return tuple(hits)

    def duplicate_groups(self) -> tuple[tuple[int, ...], ...]:
        by_fingerprint: dict[str, list[int]] = {}
        for game in self._games:
            by_fingerprint.setdefault(game_fingerprint(game), []).append(game.source_index)
        return tuple(
            tuple(indices)
            for _fingerprint, indices in sorted(by_fingerprint.items())
            if len(indices) > 1
        )

    def assert_round_trip(self) -> None:
        """Fail if deterministic export/import changes structural semantics."""
        rendered = self.export_text()
        reparsed = parse_games(rendered)
        if len(reparsed) != len(self._games):
            raise PgnWorkspaceError("round-trip changed game count")
        for original, again in zip(self._games, reparsed):
            if structural_signature(original) != structural_signature(again):
                raise PgnWorkspaceError(
                    f"round-trip structural mismatch at source_index {original.source_index}"
                )


def import_pgn(text: str) -> tuple[PgnWorkspace, PgnImportReport]:
    workspace = PgnWorkspace.from_text(text)
    return workspace, workspace.report()
