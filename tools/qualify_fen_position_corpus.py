from __future__ import annotations

"""Qualify canonical FEN/Position behavior against a lawful PGN corpus.

This tool does not introduce a second chess authority.  It projects source PGN
through the canonical GameTree legality service and then requires every emitted
canonical FEN to round-trip identically through both chesscore.Board and the
editable PositionState representation.
"""

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path

from acs.chesscore import Board
from acs.gametree_legality import validate_game_legality
from acs.pgn_roundtrip import MAX_PGN_SOURCE_BYTES, PgnRoundTripError, parse_pgn_text
from acs.position_editor import PositionState, PositionValidationError


class FenCorpusQualificationError(RuntimeError):
    """Raised when corpus-backed FEN qualification cannot be claimed."""


@dataclass(frozen=True, slots=True)
class FenCorpusQualificationReport:
    source_sha256: str
    game_count: int
    legal_move_count: int
    position_count: int
    unique_fen_count: int
    white_to_move_count: int
    black_to_move_count: int
    castling_rights_count: int
    no_castling_rights_count: int
    en_passant_count: int
    halfmove_nonzero_count: int
    fullmove_gt_one_count: int

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _read_bounded_utf8(path: Path) -> tuple[str, str]:
    try:
        source, payload = read_source_snapshot(
            path,
            max_bytes=MAX_PGN_SOURCE_BYTES,
        )
    except (OSError, ValueError) as exc:
        raise FenCorpusQualificationError(
            f"PGN corpus could not be read through the canonical source boundary: {exc}"
        ) from exc
    if not payload:
        raise FenCorpusQualificationError("PGN corpus is empty")
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise FenCorpusQualificationError("PGN corpus must be strict UTF-8") from exc
    return text, source.sha256


def _canonical_position(fen: str) -> tuple[str, tuple[str, ...]]:
    fields = fen.split()
    if len(fields) != 6:
        raise FenCorpusQualificationError("canonical legality projection emitted a non-six-field FEN")
    try:
        board_fen = Board(fen).fen()
        position_fen = PositionState.from_fen(fen).to_fen()
        repeated_position_fen = PositionState.from_fen(position_fen).to_fen()
    except (ValueError, PositionValidationError) as exc:
        raise FenCorpusQualificationError(f"canonical FEN was rejected by a Position authority: {fen}") from exc
    if board_fen != fen:
        raise FenCorpusQualificationError(
            f"Board changed canonical FEN during round-trip: expected={fen!r} actual={board_fen!r}"
        )
    if position_fen != fen or repeated_position_fen != fen:
        raise FenCorpusQualificationError(
            f"PositionState changed canonical FEN during round-trip: expected={fen!r} actual={position_fen!r}"
        )
    return fen, tuple(fields)


def qualify_pgn_position_corpus(
    text: str,
    *,
    source_sha256: str = "",
    min_games: int = 1,
    min_positions: int = 1,
    require_edge_coverage: bool = False,
) -> FenCorpusQualificationReport:
    if type(text) is not str:
        raise TypeError("text must be exact str")
    if type(min_games) is not int or min_games < 1:
        raise ValueError("min_games must be a positive integer")
    if type(min_positions) is not int or min_positions < 1:
        raise ValueError("min_positions must be a positive integer")
    if type(require_edge_coverage) is not bool:
        raise TypeError("require_edge_coverage must be boolean")

    try:
        games = parse_pgn_text(text, strict=True)
    except PgnRoundTripError as exc:
        raise FenCorpusQualificationError(f"strict PGN parse failed: {exc}") from exc
    if len(games) < min_games:
        raise FenCorpusQualificationError(
            f"lawful corpus game floor not met: {len(games)} < {min_games}"
        )

    seen: set[str] = set()
    position_count = 0
    legal_move_count = 0
    white_to_move_count = 0
    black_to_move_count = 0
    castling_rights_count = 0
    no_castling_rights_count = 0
    en_passant_count = 0
    halfmove_nonzero_count = 0
    fullmove_gt_one_count = 0

    def record(fen: str) -> None:
        nonlocal position_count
        nonlocal white_to_move_count, black_to_move_count
        nonlocal castling_rights_count, no_castling_rights_count
        nonlocal en_passant_count, halfmove_nonzero_count, fullmove_gt_one_count
        canonical, fields = _canonical_position(fen)
        position_count += 1
        seen.add(canonical)
        if fields[1] == "w":
            white_to_move_count += 1
        elif fields[1] == "b":
            black_to_move_count += 1
        else:
            raise FenCorpusQualificationError("canonical FEN has an invalid side-to-move field")
        if fields[2] == "-":
            no_castling_rights_count += 1
        else:
            castling_rights_count += 1
        if fields[3] != "-":
            en_passant_count += 1
        if int(fields[4]) > 0:
            halfmove_nonzero_count += 1
        if int(fields[5]) > 1:
            fullmove_gt_one_count += 1

    for game_index, game in enumerate(games):
        legality = validate_game_legality(game)
        if not legality.complete or legality.issues or legality.start_fen is None:
            details = "; ".join(
                f"{issue.code.value}:{issue.message}" for issue in legality.issues[:5]
            )
            raise FenCorpusQualificationError(
                f"game {game_index} did not produce a complete legal projection"
                + (f": {details}" if details else "")
            )
        record(legality.start_fen)
        for move in legality.moves:
            record(move.fen_after)
        legal_move_count += legality.legal_move_count

    if position_count < min_positions:
        raise FenCorpusQualificationError(
            f"lawful corpus position floor not met: {position_count} < {min_positions}"
        )

    report = FenCorpusQualificationReport(
        source_sha256=source_sha256,
        game_count=len(games),
        legal_move_count=legal_move_count,
        position_count=position_count,
        unique_fen_count=len(seen),
        white_to_move_count=white_to_move_count,
        black_to_move_count=black_to_move_count,
        castling_rights_count=castling_rights_count,
        no_castling_rights_count=no_castling_rights_count,
        en_passant_count=en_passant_count,
        halfmove_nonzero_count=halfmove_nonzero_count,
        fullmove_gt_one_count=fullmove_gt_one_count,
    )

    if require_edge_coverage:
        missing = [
            name
            for name, value in (
                ("white_to_move", report.white_to_move_count),
                ("black_to_move", report.black_to_move_count),
                ("castling_rights_present", report.castling_rights_count),
                ("castling_rights_cleared", report.no_castling_rights_count),
                ("en_passant_target", report.en_passant_count),
                ("nonzero_halfmove", report.halfmove_nonzero_count),
                ("fullmove_gt_one", report.fullmove_gt_one_count),
            )
            if value < 1
        ]
        if missing:
            raise FenCorpusQualificationError(
                "lawful corpus lacks required FEN edge coverage: " + ", ".join(missing)
            )
    return report


def qualify_pgn_position_corpus_file(
    path: str | Path,
    *,
    min_games: int = 1,
    min_positions: int = 1,
    require_edge_coverage: bool = False,
) -> FenCorpusQualificationReport:
    source = Path(path)
    text, digest = _read_bounded_utf8(source)
    return qualify_pgn_position_corpus(
        text,
        source_sha256=digest,
        min_games=min_games,
        min_positions=min_positions,
        require_edge_coverage=require_edge_coverage,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pgn", type=Path)
    parser.add_argument("--min-games", type=int, default=1)
    parser.add_argument("--min-positions", type=int, default=1)
    parser.add_argument("--require-edge-coverage", action="store_true")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    report = qualify_pgn_position_corpus_file(
        args.pgn,
        min_games=args.min_games,
        min_positions=args.min_positions,
        require_edge_coverage=args.require_edge_coverage,
    )
    rendered = report.to_json()
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
